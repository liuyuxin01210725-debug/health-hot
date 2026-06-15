#!/usr/bin/env python3
"""待核管理面板（私有运营视图）——把「待核说法」issue 堆变成可处理的选题池。

数据源：GitHub issue（label「待核说法」），由提交端 Worker 创建。读取用 `gh` CLI。
- 默认（无参数）：拉取 → 解析 → 按归一化说法分组 → 终端摘要 + 生成本地 HTML 面板。
- 面板不进 docs/、不公开（写到 /tmp）；每次运行重生成。
- 「被提交 N 次」= 同一归一化说法的各 issue 提交次数之和；单条 issue 次数 = 1 + 以「🔁」开头的评论数。
  这样无论提交端是否开了 KV 去重（去重前=多条 issue，去重后=1 条+🔁评论）口径都一致。

用法：
  python3 scripts/pending_dashboard.py                      # 看板（只读）
  python3 scripts/pending_dashboard.py --mark <issue#> ingested   # 标「已入库」并关闭
  python3 scripts/pending_dashboard.py --mark <issue#> rejected   # 标「已拒绝」并关闭

退出码：0 正常；1 运行错误（如 gh 不可用）；2 参数错误。
纯标准库；只依赖本机已认证的 `gh`。
"""
import json
import os
import re
import sys
import html
import subprocess
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("HEALTH_HOT_REPO", "liuyuxin01210725-debug/health-hot")
LABEL = "待核说法"
LABEL_INGESTED = "已入库"
LABEL_REJECTED = "已拒绝"
OUT_HTML = "/tmp/health_pending_dashboard.html"
TITLE_PREFIX = "待核说法："

# 状态展示顺序（待处理优先露出）
STATUS_PENDING = "待处理"
STATUS_INGESTED = "已入库"
STATUS_REJECTED = "已拒绝"
STATUS_CLOSED_UNMARKED = "已关闭(未标注)"
STATUS_ORDER = [STATUS_PENDING, STATUS_INGESTED, STATUS_REJECTED, STATUS_CLOSED_UNMARKED]
STATUS_COLOR = {
    STATUS_PENDING: "#b45309",
    STATUS_INGESTED: "#0e8a16",
    STATUS_REJECTED: "#b91c1c",
    STATUS_CLOSED_UNMARKED: "#6b7280",
}


def e(s):
    """HTML 转义（与 build.e 同义，本脚本自包含不引 build）。"""
    return html.escape(str(s if s is not None else ""))


# ---------- gh 调用 ----------

def _gh(args, check=True):
    """跑 gh，返回 stdout。check=True 时失败抛 CalledProcessError。"""
    return subprocess.run(["gh", *args], capture_output=True, text=True,
                          timeout=60, check=check)


def fetch_issues():
    """拉取全部「待核说法」issue（含已关闭），返回列表。gh 缺失/未认证 → 抛 RuntimeError。"""
    try:
        out = _gh([
            "issue", "list", "--repo", REPO, "--label", LABEL, "--state", "all",
            "--json", "number,title,body,url,createdAt,state,labels,comments",
            "--limit", "200",
        ])
    except FileNotFoundError:
        raise RuntimeError("未找到 `gh` CLI。请先安装 GitHub CLI 并 `gh auth login`。")
    except subprocess.CalledProcessError as ex:
        raise RuntimeError(f"`gh issue list` 失败（是否已 `gh auth login`？）：{ex.stderr.strip() or ex}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("`gh issue list` 超时。")
    try:
        return json.loads(out.stdout or "[]")
    except json.JSONDecodeError as ex:
        raise RuntimeError(f"gh 输出非合法 JSON：{ex}")


# ---------- 纯解析函数（可单测，不依赖 gh）----------

def strip_title(title):
    """去掉「待核说法：」前缀。"""
    return (title or "").replace(TITLE_PREFIX, "").strip()


def parse_body(body):
    """从 issue body 提取 {claim, source_page, submitted_at}（按 `- 字段：值` 行）。"""
    body = body or ""

    def grab(field):
        m = re.search(rf'^-\s*{field}：(.*)$', body, re.M)
        return m.group(1).strip() if m else ""

    return {
        "claim": grab("说法"),
        "source_page": grab("来源页面"),
        "submitted_at": grab("提交时间"),
    }


def missed_query(source_page):
    """从来源页面 URL 的 q= 参数解码出「用户搜了但没命中」的原词。"""
    if not source_page:
        return ""
    try:
        query = urllib.parse.urlsplit(source_page).query
        vals = urllib.parse.parse_qs(query).get("q") or []
        return vals[0].strip() if vals else ""
    except Exception:
        return ""


def classify_status(state, label_names):
    """据 issue state + labels 判定运营状态。标签优先于开关状态。"""
    names = set(label_names or [])
    if LABEL_INGESTED in names:
        return STATUS_INGESTED
    if LABEL_REJECTED in names:
        return STATUS_REJECTED
    if (state or "").upper() == "OPEN":
        return STATUS_PENDING
    return STATUS_CLOSED_UNMARKED


def resubmit_count(comments):
    """以「🔁」开头的评论数 = 该 issue 被重复提交的次数（提交端去重时累加的标记）。"""
    n = 0
    for c in comments or []:
        if str(c.get("body", "")).lstrip().startswith("🔁"):
            n += 1
    return n


def group_key(claim):
    """归一化说法做分组键，与 worker.js normalizeForHash 同口径（小写 + 去标点空白）。"""
    return re.sub(r'[，。！？,.!?、\s]+', '', (claim or "").lower())


# ---------- 富集 + 分组 ----------

def enrich(issue):
    parsed = parse_body(issue.get("body"))
    claim = parsed["claim"] or strip_title(issue.get("title"))
    label_names = [l.get("name", "") for l in issue.get("labels", [])]
    return {
        "number": issue.get("number"),
        "url": issue.get("url", ""),
        "claim": claim,
        "missed_query": missed_query(parsed["source_page"]),
        "submitted_at": parsed["submitted_at"] or issue.get("createdAt", ""),
        "status": classify_status(issue.get("state"), label_names),
        "count": 1 + resubmit_count(issue.get("comments")),
        "key": group_key(claim),
    }


def build_groups(enriched):
    """按归一化说法聚合。组状态优先级：待处理 > 已入库 > 已拒绝 > 已关闭未标注。"""
    by_key = {}
    for it in enriched:
        by_key.setdefault(it["key"], []).append(it)
    rows = []
    for key, items in by_key.items():
        statuses = {i["status"] for i in items}
        status = next((s for s in STATUS_ORDER if s in statuses), STATUS_CLOSED_UNMARKED)
        rows.append({
            "claim": next((i["claim"] for i in items if i["claim"]), ""),
            "missed_query": next((i["missed_query"] for i in items if i["missed_query"]), ""),
            "count": sum(i["count"] for i in items),
            "latest": max((i["submitted_at"] for i in items), default=""),
            "status": status,
            "issues": sorted(items, key=lambda i: i["submitted_at"], reverse=True),
        })
    rows.sort(key=lambda r: (r["count"], r["latest"]), reverse=True)
    return rows


# ---------- 渲染 ----------

def render_terminal(rows):
    counts = {s: 0 for s in STATUS_ORDER}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"✓ 待核管理面板：{len(rows)} 组说法 · "
          + " · ".join(f"{s} {counts[s]}" for s in STATUS_ORDER))
    pending = [r for r in rows if r["status"] == STATUS_PENDING]
    if pending:
        print("\n待处理（按热度/时间）：")
        for r in pending:
            q = f" · 搜「{r['missed_query']}」未命中" if r["missed_query"] else ""
            nums = "、".join(f"#{i['number']}" for i in r["issues"])
            print(f"  · {r['claim']}（被提交 {r['count']} 次{q}） {nums}")
    print(f"\n面板已生成：{OUT_HTML}")


def _issue_links_html(issues):
    return "、".join(
        f'<a href="{e(i["url"])}" target="_blank">#{e(i["number"])}</a>' for i in issues
    )


def _mark_cmds_html(issues, status):
    open_issues = [i for i in issues if i["status"] == STATUS_PENDING]
    if not open_issues:
        return ""
    lines = []
    for i in open_issues:
        lines.append(
            f'<code>python3 scripts/pending_dashboard.py --mark {e(i["number"])} ingested</code>'
            f' / <code>rejected</code>'
        )
    return '<div class="cmds">' + "<br>".join(lines) + "</div>"


def render_html(rows):
    sections = []
    for status in STATUS_ORDER:
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        items_html = []
        for r in group:
            q = (f'<span class="q">搜「{e(r["missed_query"])}」未命中</span>'
                 if r["missed_query"] else "")
            badge = (f'<span class="count">被提交 {e(r["count"])} 次</span>'
                     if r["count"] > 1 else "")
            items_html.append(
                '<div class="row">'
                f'<div class="claim">{e(r["claim"]) or "（无说法）"} {badge}</div>'
                f'<div class="meta">{q}<span class="t">{e(r["latest"])}</span>'
                f'<span class="links">{_issue_links_html(r["issues"])}</span></div>'
                f'{_mark_cmds_html(r["issues"], status)}'
                '</div>'
            )
        color = STATUS_COLOR[status]
        sections.append(
            f'<section><h2 style="border-color:{color}"><span style="color:{color}">●</span> '
            f'{e(status)} <span class="n">{len(group)}</span></h2>'
            + "".join(items_html) + "</section>"
        )
    total = len(rows)
    body = "".join(sections) or '<p class="empty">暂无待核说法。</p>'
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>待核管理面板 · 查过再信</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font: 15px/1.6 -apple-system,system-ui,"PingFang SC",sans-serif; max-width: 860px;
         margin: 0 auto; padding: 24px 18px 64px; color: #1f2328; background: #fff; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #6b7280; font-size: 13px; margin: 0 0 24px; }}
  section {{ margin: 0 0 28px; }}
  h2 {{ font-size: 15px; margin: 0 0 10px; padding-left: 10px; border-left: 4px solid; }}
  h2 .n {{ color: #6b7280; font-weight: normal; }}
  .row {{ padding: 10px 12px; margin: 0 0 8px; border: 1px solid #e5e7eb; border-radius: 8px; }}
  .claim {{ font-weight: 600; }}
  .count {{ display: inline-block; font-size: 12px; font-weight: 600; color: #b45309;
            background: #fef3c7; border-radius: 999px; padding: 1px 8px; margin-left: 6px; }}
  .meta {{ font-size: 13px; color: #6b7280; margin-top: 4px; display: flex; gap: 12px; flex-wrap: wrap; }}
  .q {{ color: #b45309; }}
  .links a {{ color: #0c7560; text-decoration: none; margin-right: 4px; }}
  .cmds {{ margin-top: 6px; font-size: 12px; }}
  code {{ background: #f3f4f6; border-radius: 4px; padding: 1px 5px; font-size: 12px; }}
  .empty {{ color: #6b7280; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e6edf3; background: #0d1117; }}
    .row {{ border-color: #30363d; }} code {{ background: #21262d; }}
    .count {{ background: #3a2d0a; }}
  }}
</style></head>
<body>
<h1>待核管理面板</h1>
<p class="sub">{e(total)} 组说法 · 来源 GitHub issue「{e(LABEL)}」· 私有运营视图（本地生成，未公开）</p>
{body}
</body></html>
"""
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(page)


# ---------- 写模式 ----------

def _ensure_label(name, color):
    # 标签不存在则创建；已存在时 gh 返回非 0，吞掉即可
    _gh(["label", "create", name, "--repo", REPO, "--color", color], check=False)


def do_mark(issue_number, status):
    if status not in ("ingested", "rejected"):
        print("✗ --mark 状态必须是 ingested 或 rejected")
        return 2
    label, color = ((LABEL_INGESTED, "0E8A16") if status == "ingested"
                    else (LABEL_REJECTED, "B91C1C"))
    try:
        _ensure_label(label, color)
        _gh(["issue", "edit", str(issue_number), "--repo", REPO, "--add-label", label])
        _gh(["issue", "close", str(issue_number), "--repo", REPO, "--reason", "completed"])
    except FileNotFoundError:
        print("✗ 未找到 `gh` CLI。")
        return 1
    except subprocess.CalledProcessError as ex:
        print(f"✗ 标注失败：{ex.stderr.strip() or ex}")
        return 1
    print(f"✓ 已把 #{issue_number} 标为「{label}」并关闭。")
    return 0


# ---------- main ----------

def main(argv):
    if "--mark" in argv:
        rest = argv[argv.index("--mark") + 1:]
        if len(rest) < 2 or not rest[0].lstrip("#").isdigit():
            print("用法：pending_dashboard.py --mark <issue#> <ingested|rejected>")
            return 2
        return do_mark(int(rest[0].lstrip("#")), rest[1])

    try:
        issues = fetch_issues()
    except RuntimeError as ex:
        print(f"✗ {ex}")
        return 1
    rows = build_groups([enrich(i) for i in issues])
    render_html(rows)
    render_terminal(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
