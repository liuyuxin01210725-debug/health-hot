const MAX_CLAIM_CHARS = 120;
const MAX_BODY_CHARS = 1200;
const DAILY_LIMIT_PER_IP = 10;
const DUPLICATE_TTL_SECONDS = 60 * 60 * 24 * 90;
const RATE_TTL_SECONDS = 60 * 60 * 48;
const EVENT_TERM_MAX_CHARS = 60;
const EVENT_TTL_SECONDS = 60 * 60 * 24 * 180; // 站内搜索词计数保留 180 天；"近期"由打分时按 ts 衰减，不在 KV 里做
const DEFAULT_EVENT_DAILY_LIMIT_PER_IP = 300;
const EVENT_STATS_DEFAULT_LIMIT = 200;
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
    if (request.method === "POST" && url.pathname === "/event") {
      return handleSearchEvent(request, env, cors);
    }
    if (request.method === "GET" && url.pathname === "/event/stats") {
      return handleEventStats(request, env, cors);
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
        const issueNumber = Number(existing) || null;
        // best-effort：去重命中时给原 issue 补一条「🔁」标记评论，供运营面板统计「被提交 N 次」。
        // 失败不阻断去重响应（评论失败不应让用户看到错误）。
        if (issueNumber) {
          await addResubmitComment(repo, issueNumber, page, env.GITHUB_TOKEN).catch(() => {});
        }
        return json({ ok: true, status: "duplicate", issue: issueNumber }, 200, cors);
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

// 站内搜索计数端点。记录 {term, hit} 的命中/未命中次数，作为"精选热点度"的需求信号。
// 隐私：只存规范化搜索词 + 计数 + 末次日期；不存 IP（仅哈希用于软限流，48h TTL）、不存用户、不记单条历史。
// 全程 fire-and-forget：任何不合法/超限/出错都静默返回 204，前端无感。
async function handleSearchEvent(request, env, cors) {
  const noop = new Response(null, { status: 204, headers: cors });
  const origin = request.headers.get("Origin") || "";
  if (!isAllowedOrigin(origin, env) || !env.PENDING_KV) return noop;
  const raw = await request.text();
  if (raw.length > MAX_BODY_CHARS) return noop;
  let payload;
  try { payload = JSON.parse(raw || "{}"); } catch { return noop; }
  const term = normalizeClaim(payload.term).slice(0, EVENT_TERM_MAX_CHARS);
  if (normalizeForHash(term).length < 2) return noop; // 去掉过短/纯标点的噪声
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const limit = Number(env.EVENT_DAILY_LIMIT_PER_IP) || DEFAULT_EVENT_DAILY_LIMIT_PER_IP;
  if (!(await enforceEventRateLimit(env.PENDING_KV, ip, limit))) return noop; // 防刷，静默丢弃
  await recordSearchEvent(env.PENDING_KV, term, payload.hit === true).catch(() => {});
  return noop;
}

async function enforceEventRateLimit(kv, ip, limit) {
  // 与 /submit 限流分开计：单独 evtrate: 键，独立上限，互不消耗。
  const day = new Date().toISOString().slice(0, 10);
  const key = `evtrate:${await sha256(ip)}:${day}`;
  const count = Number(await kv.get(key) || "0");
  if (count >= limit) return false;
  await kv.put(key, String(count + 1), { expirationTtl: RATE_TTL_SECONDS });
  return true;
}

async function recordSearchEvent(kv, term, hit) {
  // 键按"标点不敏感"的哈希分组（"维C 长结石" 与 "维C长结石" 归一条）；值存可读规范化词 + 命中/未命中计数 + 末次日期。
  // 读-改-写自增，与现有 rate 计数器同款非原子；小流量可接受（偶发竞态只丢个别计数，不影响热度排序）。
  const key = `evt:q:${await sha256(normalizeForHash(term))}`;
  let rec = null;
  try { rec = await kv.get(key, { type: "json" }); } catch { rec = null; }
  if (!rec || typeof rec !== "object") rec = { t: term, h: 0, m: 0, ts: "" };
  if (hit) rec.h = (Number(rec.h) || 0) + 1;
  else rec.m = (Number(rec.m) || 0) + 1;
  rec.t = term;
  rec.ts = new Date().toISOString().slice(0, 10);
  await kv.put(key, JSON.stringify(rec), { expirationTtl: EVENT_TTL_SECONDS });
}

// 读回聚合统计（给构建期/打分步用）。token 保护，不公开裸搜索词。
// 注意：list + 逐键 get 是 N+1 读，词量达数千时会慢/触达子请求上限；当前小流量可接受。
async function handleEventStats(request, env, cors) {
  const url = new URL(request.url);
  const token = url.searchParams.get("token")
    || (request.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "").trim();
  if (!env.EVENT_STATS_TOKEN || token !== env.EVENT_STATS_TOKEN) {
    return json({ error: "forbidden" }, 403, cors);
  }
  if (!env.PENDING_KV) return json({ count: 0, terms: [] }, 200, cors);
  const out = [];
  let cursor;
  do {
    const res = await env.PENDING_KV.list({ prefix: "evt:q:", cursor, limit: 1000 });
    for (const k of res.keys) {
      let rec = null;
      try { rec = await env.PENDING_KV.get(k.name, { type: "json" }); } catch { rec = null; }
      if (rec && typeof rec === "object") {
        out.push({ term: rec.t || "", h: Number(rec.h) || 0, m: Number(rec.m) || 0, ts: rec.ts || "" });
      }
    }
    cursor = res.list_complete ? undefined : res.cursor;
  } while (cursor);
  out.sort((a, b) => (b.h + b.m) - (a.h + a.m));
  const limit = Math.min(Number(url.searchParams.get("limit")) || EVENT_STATS_DEFAULT_LIMIT, 1000);
  return json({ count: out.length, terms: out.slice(0, limit) }, 200, cors);
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

async function addResubmitComment(repo, issueNumber, page, token) {
  // 去重命中时在原 issue 上追加一条标记评论。运营面板按「🔁」开头的评论数统计重复提交次数。
  const body = `🔁 同一说法再次提交 · ${new Date().toISOString()}` + (page ? ` · 来源 ${page}` : "");
  const response = await fetch(`https://api.github.com/repos/${repo}/issues/${issueNumber}/comments`, {
    method: "POST",
    headers: {
      "Accept": "application/vnd.github+json",
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
      "User-Agent": "health-hot-submit-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ body }),
  });
  if (!response.ok) {
    throw new Error(`resubmit comment failed: ${response.status}`);
  }
}

function allowedOrigins(env) {
  const configured = String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return [...new Set([...DEFAULT_ALLOWED_ORIGINS, ...configured])];
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
