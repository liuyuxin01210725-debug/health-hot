const MAX_CLAIM_CHARS = 120;
const MAX_BODY_CHARS = 1200;
const DAILY_LIMIT_PER_IP = 10;
const DUPLICATE_TTL_SECONDS = 60 * 60 * 24 * 90;
const RATE_TTL_SECONDS = 60 * 60 * 48;
const DEFAULT_ALLOWED_ORIGINS = [
  "https://health-hot.vercel.app",
  "https://liuyuxin01210725-debug.github.io",
  "http://localhost:8000",
  "http://127.0.0.1:8000",
];

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }

    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") {
      return json({ ok: true }, 200, cors);
    }
    if (request.method !== "POST" || url.pathname !== "/submit") {
      return json({ error: "not_found" }, 404, cors);
    }

    const origin = request.headers.get("Origin") || "";
    if (!isAllowedOrigin(origin, env)) {
      return json({ error: "origin_not_allowed" }, 403, cors);
    }
    if (!env.GITHUB_TOKEN) {
      return json({ error: "server_not_configured" }, 500, cors);
    }

    const raw = await request.text();
    if (raw.length > MAX_BODY_CHARS) {
      return json({ error: "payload_too_large" }, 413, cors);
    }

    let payload;
    try {
      payload = JSON.parse(raw || "{}");
    } catch {
      return json({ error: "invalid_json" }, 400, cors);
    }

    if (String(payload.website || "").trim()) {
      return json({ error: "spam_rejected" }, 400, cors);
    }

    const claim = normalizeClaim(payload.claim);
    if (claim.length < 2) {
      return json({ error: "claim_too_short" }, 400, cors);
    }
    if (claim.length > MAX_CLAIM_CHARS) {
      return json({ error: "claim_too_long" }, 400, cors);
    }

    const repo = env.GITHUB_REPO || "liuyuxin01210725-debug/health-hot";
    const label = env.GITHUB_LABEL || "待核说法";
    const page = safeUrl(payload.page);

    if (env.PENDING_KV) {
      const ip = request.headers.get("CF-Connecting-IP") || "unknown";
      const allowed = await enforceRateLimit(env.PENDING_KV, ip);
      if (!allowed) {
        return json({ error: "rate_limited" }, 429, cors);
      }
      const duplicateKey = `claim:${await sha256(normalizeForHash(claim))}`;
      const existing = await env.PENDING_KV.get(duplicateKey);
      if (existing) {
        return json({ ok: true, status: "duplicate", issue: Number(existing) || null }, 200, cors);
      }
      const issue = await createIssue(repo, label, claim, page, env.GITHUB_TOKEN).catch((error) => error);
      if (issue && issue.error) {
        return json(issue, 502, cors);
      }
      await env.PENDING_KV.put(duplicateKey, String(issue.number), { expirationTtl: DUPLICATE_TTL_SECONDS });
      return json({ ok: true, status: "created", issue: issue.number, url: issue.html_url }, 201, cors);
    }

    const issue = await createIssue(repo, label, claim, page, env.GITHUB_TOKEN).catch((error) => error);
    if (issue && issue.error) {
      return json(issue, 502, cors);
    }
    return json({ ok: true, status: "created", issue: issue.number, url: issue.html_url }, 201, cors);
  },
};

function normalizeClaim(value) {
  return String(value || "")
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeForHash(value) {
  return value.toLowerCase().replace(/[，。！？,.!?、\s]+/g, "");
}

function safeUrl(value) {
  const raw = String(value || "").trim();
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" && url.protocol !== "http:") return "";
    return url.toString().slice(0, 300);
  } catch {
    return "";
  }
}

async function enforceRateLimit(kv, ip) {
  const day = new Date().toISOString().slice(0, 10);
  const key = `rate:${await sha256(ip)}:${day}`;
  const count = Number(await kv.get(key) || "0");
  if (count >= DAILY_LIMIT_PER_IP) {
    return false;
  }
  await kv.put(key, String(count + 1), { expirationTtl: RATE_TTL_SECONDS });
  return true;
}

async function createIssue(repo, label, claim, page, token) {
  return createIssueRequest(repo, label, claim, page, token).catch((error) => {
    if (label && error.status === 422) {
      return createIssueRequest(repo, "", claim, page, token);
    }
    throw error;
  });
}

async function createIssueRequest(repo, label, claim, page, token) {
  const title = `待核说法：${claim.slice(0, 70)}`;
  const body = [
    "用户在站内搜索无结果后主动提交了这条待核说法。",
    "",
    `- 说法：${claim}`,
    page ? `- 来源页面：${page}` : "",
    `- 提交时间：${new Date().toISOString()}`,
    "",
    "隐私边界：前端只发送用户主动点击提交的说法，不自动记录搜索历史；请勿在 issue 中加入个人病史。",
  ].filter(Boolean).join("\n");
  const response = await fetch(`https://api.github.com/repos/${repo}/issues`, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "health-hot-submit-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify(label ? { title, body, labels: [label] } : { title, body }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw {
      error: "github_issue_failed",
      detail: data.message || response.statusText,
      status: response.status,
    };
  }
  return data;
}

function allowedOrigins(env) {
  const configured = String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return configured.length ? configured : DEFAULT_ALLOWED_ORIGINS;
}

function isAllowedOrigin(origin, env) {
  return allowedOrigins(env).includes(origin);
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowOrigin = isAllowedOrigin(origin, env) ? origin : "null";
  return {
    "Access-Control-Allow-Origin": allowOrigin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...headers,
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

async function sha256(value) {
  const input = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", input);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}
