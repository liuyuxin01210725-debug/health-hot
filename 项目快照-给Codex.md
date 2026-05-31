# 查过再信 / health-hot — 项目快照 v2（供 Codex 复审）

> 上一轮 Codex 评审后已重构：从"卡片列表"升级为**健康说法核验库**——独立详情页 + 结构化字段 + 发布闸门。
> 本轮按你的 7 点做了**验收**（结果见第 7 节），并补了 SEO 字段与预排日期标注。
> 本轮约定**不扩功能**；`tags`/`confidence`/自动草稿 PR 留到下一轮。

---

## 1. 这是什么
**健康说法核验库**：把流行健康说法逐条查到原始证据、标证据强度、写清适用人群与注意事项。资讯流是入口，核心是分清「听来的」与「有据的」。无后端、无数据库、纯 Python 标准库静态站，部署在 GitHub Pages。

## 2. 线上 / 仓库
- 线上：https://liuyuxin01210725-debug.github.io/health-hot/
- 详情页示例：https://liuyuxin01210725-debug.github.io/health-hot/claims/seed-oils.html
- 仓库：`liuyuxin01210725-debug/health-hot`（公开）；本地：`~/Documents/AI health/`

## 3. 架构与数据流
```
data/sources.json  信源（youtube=channel_id / rss=url / pubmed=query）
   ▼ collect.py     抓取+去重（RSS/Atom；PubMed=免费 E-utilities）→ /tmp/health_candidates.json
   ▼ [人工/Claude 按 7 铁律 摘要 + 结构化]   ← 质量关口
data/items/*.json  每条 = 一条核验（结构化字段）
   ▼ build.py       ① 发布闸门校验 ② 生成 docs/{index,all,about}.html + docs/claims/<slug>.html
   ▼ git push → GitHub Pages（main /docs）
```

## 4. 文件结构
```
build.py            生成器：闸门 + 首页/全部/关于 + 每条独立详情页
collect.py          收集引擎（含 PubMed E-utilities）
data/sources.json   信源
data/items/*.json   22 条核验
docs/               产物：index/all/about.html + claims/<slug>.html ×22 + styles.css + .nojekyll
README.md / .gitignore
```

## 5. 数据模型（item 字段）
- 基本：`title` `source` `source_url`(必有) `category` `evidence`(rct/meta/observational/expert/blogger) `featured` `rank` `summary`
- 结构化（本轮新增）：`slug`(URL) `status`(reviewed) `conclusion`(一句话结论) `population`(适用于谁) `caveats`(需要注意)
- 日期三件套（**刻意分开，避免混淆**）：
  - `date` = 本站 feed 日期（排序+闸门用；通常=原文日期，原文为预排/未来时取收录日，保证 feed 无未来日期）
  - `source_published_at` = 原文真实发布日期（**可为期刊预排的未来日期**，仅元数据展示，不参与闸门；详情页对未来值标注「期刊预排」）
  - `reviewed_at` = 本站复核日期

## 6. 7 铁律（内容安全约束）
证据分级 / 引用追溯(必有 source_url) / 不给具体剂量 / 医疗免责 / 不暗示治疗 / 标注不确定 / 只摘要+回链不搬全文。

## 7. 本轮验收结果（按你列的 7 点，附实测）⭐
1. **发布闸门**：✅ 喂 6 种坏数据实测全拦——未来日期 / 缺 source_url / status≠reviewed / 缺 slug / 重复 slug / 重复 source_url；正常条目放行。（见 `build.py` 的 `validate()`）
2. **22 详情页 + 相关链接**：✅ 22 个全生成；42 条「相关核验」链接经脚本核对 **0 断链**。
3. **无编造适用人群**：✅ `population` 多为「未特别限定，见原文」；具体值（绝经后女性 / 心梗患者 n=19 / 慢性失眠）均可在原文摘要溯源，无凭空编造。
4. **返回路径/移动端/SEO**：返回路径(面包屑)✅、`lang=zh-CN`✅、移动端媒体查询✅；**本轮补：每页加 `meta description` + `og:title/description/url` + `canonical`**（已验证生成）。
5. **docs/README/实现一致**：✅ README `public/` 残留=0、已对齐 `docs/` 与详情页；docs 产物与实现一致。
6. **GitHub Issues 纠错入口**：✅ 关于页有 `…/issues` 链接，仓库 `has_issues=true`，可用。
7. **预排 vs 收录日**：✅ 未混淆——`date`/`source_published_at`/`reviewed_at` 分开存、详情页分别显示；creatine 的期刊预排日（2026-12-01）已标注「期刊预排，未到见刊日」，并 clamp `date` 为收录日通过闸门。

## 8. 设计决策
浅色健康风（非 AI HOT 深色）；知识库优先 + 轻量更新流；信源求权威不求量；PubMed 作证据地基（免费，能出 RCT/荟萃级）。

## 9. 下一轮（已与 owner 约定推迟，本轮勿动）
- 跨类 `tags` + 主题集合页（如"跳绳"横跨骨骼/运动/关节）
- 独立 `confidence` 字段（当前用 `evidence` 证据等级代替）
- 自动草稿 PR 流水线：`collect.py → LLM 草稿 → 人工审 → 合并 → Pages`（需 `workflow` 授权 + LLM key）

---

（以下为本轮最新源码与全部内容，供逐行复审）

## 10. `build.py`（生成器 + 发布闸门 + 详情页 + SEO）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查过再信 · 健康说法核验库 — 静态站生成器（v4）。

读 data/items/*.json → 生成：
- docs/index.html          首页（重点核验 = 精选）
- docs/all.html            全部核验（按分类成组 + 搜索 + 筛选）
- docs/about.html          关于（方法论 + 复核 + 纠错入口）
- docs/claims/<slug>.html  每条结论的独立详情页（可收藏/可分享/可被收录）

发布闸门：构建前校验，未来日期 / 缺来源 / 缺必填 / 未审核 的条目**不发布**并报警。
纯标准库，无依赖。用法：python3 build.py
"""
import json, glob, os, html, shutil, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "items")
OUT = os.path.join(ROOT, "docs")
CLAIMS = os.path.join(OUT, "claims")
TODAY = datetime.date.today().isoformat()

SITE_TITLE = "查过再信"
SITE_URL = "https://liuyuxin01210725-debug.github.io/health-hot/"
HERO_Q = "听到一个健康说法？先查一下证据。"

# 日期字段语义（避免把"期刊预排日期"与"本站收录日"混为一谈）：
#   date                = 本站 feed 日期，用于排序与发布闸门；通常等于原文日期，
#                         但当原文为"预排/未来日期"时取收录日，确保 feed 不出现未来日期。
#   source_published_at = 原文/源的真实发布日期（可为期刊预排的未来日期，仅作元数据展示，不参与闸门）。
#   reviewed_at         = 本站复核日期。
HERO_SUB = "每条结论都标注证据强度、适用人群和原始出处——把「听来的」和「有据的」分开。"
REPO = "https://github.com/liuyuxin01210725-debug/health-hot"

EV_LABEL = {"rct": "RCT", "meta": "Meta", "observational": "观察",
            "expert": "专家", "blogger": "博主", "anecdote": "个例"}
EV_DESC = {
    "rct": "随机对照试验——证据强度高，但仍要看样本与重复性。",
    "meta": "系统综述 / 荟萃分析——综合多项研究，证据强度高。",
    "observational": "观察性研究——能显示相关，不能证明因果。",
    "expert": "专家观点 / 科普——有参考价值，待更强证据确认。",
    "blogger": "个人观点 / 方案——非临床证据，仅供参考。",
    "anecdote": "个例 / 经验——证据级别最低，谨慎对待。",
}
REQUIRED = ["title", "source_url", "slug", "category", "evidence", "summary"]


def load_items():
    items = []
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                it = json.load(fh)
        except Exception as ex:
            print(f"  ✗ JSON 解析失败 {os.path.basename(f)}: {ex}")
            continue
        it["_file"] = os.path.basename(f)
        items.append(it)
    return items


def validate(items):
    """发布闸门：返回 (合格条目, 被拦条目+原因)。不靠人记得，靠这里。"""
    good, blocked, seen_slug, seen_url = [], [], {}, {}
    for it in items:
        errs = []
        for k in REQUIRED:
            if not it.get(k):
                errs.append(f"缺字段 {k}")
        d = it.get("date", "")
        if d and d > TODAY:
            errs.append(f"未来日期 {d}（今天 {TODAY}）")
        if it.get("status") and it["status"] not in ("reviewed", "published"):
            errs.append(f"未审核 status={it['status']}")
        s, u = it.get("slug", ""), it.get("source_url", "")
        if s and s in seen_slug:
            errs.append(f"slug 重复（与 {seen_slug[s]}）")
        if u and u in seen_url:
            errs.append(f"来源链接重复（与 {seen_url[u]}）")
        if errs:
            blocked.append((it.get("_file", "?"), errs))
        else:
            seen_slug[s] = it["_file"]
            seen_url[u] = it["_file"]
            it.setdefault("featured", False)
            it.setdefault("rank", 0)
            good.append(it)
    good.sort(key=lambda x: (x.get("date", ""), x.get("rank", 0)), reverse=True)
    return good, blocked


def e(s):
    return html.escape(str(s if s is not None else ""))


def ev_badge(it):
    ev = it.get("evidence", "")
    return f'<span class="ev ev-{e(ev)}">{EV_LABEL.get(ev, e(ev))}</span>' if ev else ""


def meta_row(it):
    return (f'<div class="meta"><span class="cat">{e(it.get("category",""))}</span>'
            f'{ev_badge(it)}<span class="src">{e(it.get("source",""))}</span>'
            f'<span class="date">复核 {e(it.get("reviewed_at") or it.get("date",""))}</span>'
            f'{("<span class=badge>✦ 精选</span>") if it.get("featured") else ""}</div>')


def card(it):
    """信息流卡：标题进**详情页**（不再直接跳外链），展示一句话结论。"""
    slug = e(it.get("slug", ""))
    cat = e(it.get("category", ""))
    blob = e(" ".join(str(it.get(k, "")) for k in
             ("title", "conclusion", "summary", "category", "population", "caveats")))
    concl = e(it.get("conclusion") or it.get("summary", ""))
    return (f'<article class="card" data-cat="{cat}" data-search="{blob}">\n'
            f'  {meta_row(it)}\n'
            f'  <h2 class="title"><a href="claims/{slug}.html">{e(it.get("title",""))}</a></h2>\n'
            f'  <p class="concl">{concl}</p>\n'
            f'</article>')


def shell(title, active, inner, base="", extra_js="", desc="", canon=""):
    nav_items = [("精选", "index.html"), ("全部", "all.html"), ("关于", "about.html")]
    nav = "".join(
        f'<a class="navlink{" on" if lbl == active else ""}" href="{base}{href}">{lbl}</a>'
        for lbl, href in nav_items)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · {e(SITE_TITLE)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{SITE_URL}{canon}">
<meta property="og:type" content="article">
<meta property="og:title" content="{e(title)} · {e(SITE_TITLE)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{SITE_URL}{canon}">
<link rel="stylesheet" href="{base}styles.css">
</head>
<body>
<header class="top">
  <div class="bar">
    <a class="brand" href="{base}index.html"><span class="leaf">✚</span>{e(SITE_TITLE)}<span class="tag">· 健康说法核验库</span></a>
    <form class="search" action="{base}all.html" method="get" role="search">
      <input type="search" name="q" placeholder="查一个说法：肌酸、种子油、间歇禁食…" aria-label="搜索">
    </form>
    <nav class="nav">{nav}</nav>
  </div>
</header>
<main class="main">
{inner}
</main>
<footer class="foot"><div class="bar">
  <span>本站为科普整理，<strong>非医疗建议</strong>；每条结论标注证据等级，点击可回原文核对。</span>
  <span class="muted">{e(SITE_TITLE)} · 持续收集与查证</span>
</div></footer>
{extra_js}
</body>
</html>'''


def detail_page(it, related):
    slug = it.get("slug", "")
    url = e(it.get("source_url", ""))
    ev = it.get("evidence", "")
    fields = []
    fields.append(f'<dt>证据强度</dt><dd>{ev_badge(it)} {e(EV_DESC.get(ev,""))}</dd>')
    if it.get("population"):
        fields.append(f'<dt>适用于谁</dt><dd>{e(it["population"])}</dd>')
    if it.get("caveats"):
        fields.append(f'<dt>需要注意</dt><dd>{e(it["caveats"])}</dd>')
    if it.get("summary"):
        fields.append(f'<dt>详情</dt><dd>{e(it["summary"])}</dd>')
    rel = ""
    if related:
        links = "".join(f'<li><a href="{e(r.get("slug",""))}.html">{e(r.get("title",""))}</a>'
                        f'<span class="rcat">{e(r.get("category",""))}</span></li>' for r in related)
        rel = f'<section class="related"><h3>相关核验</h3><ul>{links}</ul></section>'
    src_date = it.get("source_published_at") or it.get("date", "")
    src_lbl = e(src_date) + ("（期刊预排，未到见刊日）" if src_date and src_date > TODAY else "")
    inner = (f'<nav class="crumb"><a href="../all.html">← 全部核验</a></nav>\n'
             f'<article class="claim">\n'
             f'  {meta_row(it)}\n'
             f'  <h1>{e(it.get("title",""))}</h1>\n'
             f'  <p class="claim-concl"><span class="lbl">一句话结论</span>{e(it.get("conclusion") or it.get("summary",""))}</p>\n'
             f'  <dl class="fields">{"".join(fields)}</dl>\n'
             f'  <a class="src-btn" href="{url}" target="_blank" rel="noopener">查看原始来源 ↗</a>\n'
             f'  <p class="prov">来源：{e(it.get("source",""))}'
             f'{(" · 原文日期 " + src_lbl) if src_date else ""}'
             f' · 本站复核 {e(it.get("reviewed_at") or TODAY)}</p>\n'
             f'</article>\n{rel}')
    return shell(it.get("title", ""), "", inner, base="../",
                 desc=(it.get("conclusion") or it.get("summary", "")),
                 canon="claims/" + it.get("slug", "") + ".html")


def render_index(items):
    feats = sorted([it for it in items if it.get("featured")],
                   key=lambda x: x.get("rank", 0), reverse=True)
    cards = "\n".join(card(it) for it in feats) or '<p class="empty">还没有核验条目。</p>'
    hero = (f'<section class="hero"><h1>{e(HERO_Q)}</h1>'
            f'<p class="lead">{e(HERO_SUB)}</p>'
            f'<form class="hero-search" action="all.html" method="get">'
            f'<input type="search" name="q" placeholder="查一个说法：肌酸、种子油、跳绳、间歇禁食…">'
            f'<button type="submit">查证据</button></form></section>')
    head = (f'<div class="sec-head"><h2>重点核验</h2>'
            f'<a class="more" href="all.html">看全部 →</a></div>')
    return shell("精选", "精选", hero + head + '<section class="cards">' + cards + '</section>',
                 desc=HERO_SUB, canon="index.html")


def render_all(items):
    cats, by = [], {}
    for it in items:
        c = it.get("category", "其他")
        if c not in by:
            by[c] = []; cats.append(c)
        by[c].append(it)
    cats.sort(key=lambda c: -len(by[c]))
    pills = '<button class="pill on" data-f="*">全部</button>' + "".join(
        f'<button class="pill" data-f="{e(c)}">{e(c)}（{len(by[c])}）</button>' for c in cats)
    sections = ""
    for c in cats:
        cards = "\n".join(card(it) for it in by[c])
        sections += (f'<section class="catsec" data-cat="{e(c)}">'
                     f'<h3 class="cat-h">{e(c)}<span class="cnt">{len(by[c])}</span></h3>'
                     f'<div class="cards">{cards}</div></section>')
    head = (f'<div class="sec-head"><h2>全部核验</h2>'
            f'<span class="muted">共 {len(items)} 条 · 按主题分组</span></div>'
            f'<div class="filters">{pills}</div>'
            f'<p class="result-note" id="note"></p>')
    js = '''<script>
function q(){const m=location.search.match(/[?&]q=([^&]*)/);return m?decodeURIComponent(m[1].replace(/\\+/g,' ')).trim():'';}
const cards=[...document.querySelectorAll('.card')],note=document.getElementById('note');
let curF='*',curQ=q();const si=document.querySelector('.search input');if(si&&curQ)si.value=curQ;
function apply(){let n=0;cards.forEach(c=>{
  const okF=curF==='*'||c.dataset.cat===curF;
  const okQ=!curQ||c.dataset.search.toLowerCase().includes(curQ.toLowerCase());
  const show=okF&&okQ;c.style.display=show?'':'none';if(show)n++;});
  document.querySelectorAll('.catsec').forEach(s=>{
    const vis=[...s.querySelectorAll('.card')].some(c=>c.style.display!=='none');
    s.style.display=vis?'':'none';});
  note.textContent=curQ?('「'+curQ+'」匹配 '+n+' 条'):'';}
document.querySelectorAll('.pill').forEach(p=>p.addEventListener('click',()=>{
  document.querySelectorAll('.pill').forEach(x=>x.classList.remove('on'));p.classList.add('on');curF=p.dataset.f;apply();}));
apply();
</script>'''
    return shell("全部", "全部", head + sections, extra_js=js,
                 desc="全部健康说法核验，按主题分组，每条标注证据强度、适用人群与原始出处。", canon="all.html")


def render_about():
    inner = f'''<section class="hero slim"><h1>关于本站</h1>
<p class="lead">「{e(SITE_TITLE)}」是一个**健康说法核验库**：把流行的健康说法，一条条查到原始证据、标出强度、写清适用人群和注意事项。资讯流只是入口，核心是帮你分清「听来的」和「有据的」。</p></section>
<section class="values">
<div class="val"><h3>怎么审核</h3><p>从权威信源（健康播客 / 研究者 / PubMed）抓取 → 提炼要点 → 按 7 条规则人工/AI 复核 → 标 <code>reviewed</code> 才发布。构建前有自动闸门：未来日期、缺来源、未审核的条目不会上线。</p></div>
<div class="val"><h3>证据分级</h3><p>每条标清 RCT / 荟萃 / 观察 / 专家 / 博主，不混为一谈。点进详情页能看到这条结论"凭什么"。</p></div>
<div class="val"><h3>何时复核</h3><p>每条带「复核日期」，按约半年的节奏回头审；健康结论会过时，过时的会标出或更新。</p></div>
<div class="val"><h3>不开处方</h3><p>涉及剂量、治疗的只讲原则、不写具体克数，不暗示治疗任何疾病。具体执行请咨询持证医生或注册营养师。</p></div>
<div class="val"><h3>标注不确定</h3><p>小样本、早期、阴性、有争议的结论都会明确标注，不替它下定论。</p></div>
<div class="val"><h3>如何纠错</h3><p>发现错误或更新？欢迎到 <a href="{REPO}/issues" target="_blank" rel="noopener">GitHub 仓库提 issue</a> 指正——本站代码与数据全部公开、可追溯。</p></div>
</section>
<p class="hint">凭什么信？不靠"我读了很多书"——靠每一条都能点回原文，你自己能核对。</p>'''
    return shell("关于", "关于", inner,
                 desc="查过再信的方法论：怎么审核、证据如何分级、何时复核、如何纠错。", canon="about.html")


CSS = '''
:root{
  --bg:#f6f9f7; --panel:#ffffff; --ink:#16302a; --muted:#5f726c; --line:#e3ece8;
  --accent:#0f8a72; --accent-soft:#e6f4f0; --accent-ink:#0a5d4d;
  --rct:#1f9d5c; --meta:#0e9488; --obs:#7c8a86; --exp:#3f73c4; --blog:#9aa39f;
  --warn:#b06a2c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  line-height:1.7;font-size:16px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.bar{max-width:920px;margin:0 auto;padding:0 22px}
.top{background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:20}
.top .bar{display:flex;align-items:center;gap:16px;height:62px}
.brand{display:flex;align-items:center;gap:7px;font-weight:800;font-size:19px;color:var(--ink);white-space:nowrap}
.brand:hover{text-decoration:none}.brand .tag{font-weight:500;font-size:13px;color:var(--muted)}
.leaf{display:inline-grid;place-items:center;width:25px;height:25px;border-radius:8px;background:var(--accent);color:#fff;font-size:14px}
.search{flex:1;max-width:380px}
.search input{width:100%;border:1px solid var(--line);background:#fbfdfc;border-radius:999px;padding:9px 15px;font-size:14px;color:var(--ink)}
.search input:focus{outline:none;border-color:var(--accent);background:#fff}
.nav{display:flex;gap:4px;margin-left:auto}
.navlink{color:var(--muted);font-size:15px;padding:7px 12px;border-radius:8px}
.navlink:hover{background:var(--accent-soft);color:var(--accent-ink);text-decoration:none}
.navlink.on{color:var(--accent);font-weight:700}
.main{max-width:920px;margin:0 auto;padding:8px 22px 56px}
.hero{padding:44px 0 24px;text-align:center}.hero.slim{padding:34px 0 10px}
.hero h1{margin:0 0 12px;font-size:30px;letter-spacing:.5px}
.lead{margin:0 auto 22px;color:var(--muted);font-size:16px;max-width:620px}
.hero-search{display:flex;gap:8px;max-width:560px;margin:0 auto}
.hero-search input{flex:1;border:1px solid var(--line);border-radius:12px;padding:13px 16px;font-size:15px;background:#fff}
.hero-search input:focus{outline:none;border-color:var(--accent)}
.hero-search button{background:var(--accent);color:#fff;border:none;border-radius:12px;padding:0 22px;font-size:15px;font-weight:700;cursor:pointer}
.hero-search button:hover{background:var(--accent-ink)}
.sec-head{display:flex;align-items:baseline;justify-content:space-between;margin:14px 0;border-bottom:2px solid var(--line);padding-bottom:8px}
.sec-head h2{margin:0;font-size:21px}.more{font-size:14px}.muted{color:var(--muted);font-size:14px}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 6px}
.pill{border:1px solid var(--line);background:#fff;color:var(--muted);border-radius:999px;padding:6px 14px;font-size:14px;cursor:pointer}
.pill:hover{color:var(--accent-ink);border-color:var(--accent)}
.pill.on{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:700}
.result-note{color:var(--muted);font-size:14px;margin:4px 0 0;min-height:1em}
.catsec{margin-top:18px}
.cat-h{font-size:16px;margin:0 0 10px;color:var(--accent-ink);display:flex;align-items:center;gap:8px}
.cat-h .cnt{font-size:12px;color:var(--muted);background:var(--accent-soft);border-radius:999px;padding:1px 9px}
.cards{display:flex;flex-direction:column;gap:13px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:0 1px 2px rgba(20,60,50,.03);transition:box-shadow .15s,transform .15s,border-color .15s}
.card:hover{box-shadow:0 8px 26px rgba(20,60,50,.08);transform:translateY(-1px);border-color:#cfe3db}
.meta{display:flex;flex-wrap:wrap;align-items:center;gap:9px;font-size:12.5px;color:var(--muted);margin-bottom:7px}
.cat{background:var(--accent-soft);color:var(--accent-ink);border-radius:7px;padding:2px 9px;font-weight:700}
.ev{border-radius:7px;padding:2px 8px;color:#fff;font-size:11.5px;font-weight:600}
.ev-rct{background:var(--rct)}.ev-meta{background:var(--meta)}.ev-observational{background:var(--obs)}
.ev-expert{background:var(--exp)}.ev-blogger,.ev-anecdote{background:var(--blog)}
.badge{margin-left:auto;background:#fff5e9;color:var(--warn);border:1px solid #f0d9bf;border-radius:7px;padding:2px 9px;font-size:11.5px;font-weight:800}
.title{margin:0 0 7px;font-size:18px;line-height:1.45}
.title a{color:var(--ink)}.title a:hover{color:var(--accent)}
.concl{margin:0;font-size:14.5px;color:#3a4742}
/* 详情页 */
.crumb{margin:14px 0 6px;font-size:14px}
.claim{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px 24px;margin-bottom:18px}
.claim h1{margin:6px 0 14px;font-size:25px;line-height:1.4}
.claim-concl{background:var(--accent-soft);border-radius:12px;padding:14px 16px;font-size:17px;color:var(--accent-ink);margin:0 0 18px}
.claim-concl .lbl{display:block;font-size:12px;font-weight:800;color:var(--accent);margin-bottom:4px;letter-spacing:.5px}
.fields{margin:0 0 18px}.fields dt{font-weight:800;color:var(--accent-ink);font-size:14px;margin-top:14px}
.fields dd{margin:4px 0 0;color:#33403b}
.src-btn{display:inline-block;background:var(--accent);color:#fff;border-radius:10px;padding:11px 20px;font-weight:700;font-size:15px}
.src-btn:hover{background:var(--accent-ink);text-decoration:none}
.prov{margin:14px 0 0;color:var(--muted);font-size:13px}
.related{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 20px}
.related h3{margin:0 0 10px;font-size:16px}.related ul{margin:0;padding:0;list-style:none}
.related li{padding:8px 0;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:10px}
.related li:first-child{border-top:none}.related .rcat{color:var(--muted);font-size:12px;flex:none}
.values{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px;margin:18px 0}
.val{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.val h3{margin:0 0 6px;color:var(--accent-ink);font-size:16px}.val p{margin:0;color:var(--muted);font-size:14px}
.val code{background:var(--accent-soft);color:var(--accent-ink);border-radius:5px;padding:0 5px;font-size:13px}
.hint{color:var(--muted);text-align:center;margin:18px 0}
.foot{border-top:1px solid var(--line);margin-top:30px;background:var(--panel)}
.foot .bar{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;padding:18px 22px;color:var(--muted);font-size:13px}
.empty{color:var(--muted);padding:30px 0}
@media(max-width:680px){
  .top .bar{flex-wrap:wrap;height:auto;padding:10px 16px;gap:10px}
  .search{order:3;max-width:none;flex-basis:100%}.brand .tag{display:none}
  .hero h1{font-size:24px}.hero{padding:30px 0 18px}
}
'''


def main():
    items = load_items()
    good, blocked = validate(items)
    # 写出
    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(CLAIMS, exist_ok=True)
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    with open(os.path.join(OUT, "styles.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(good))
    with open(os.path.join(OUT, "all.html"), "w", encoding="utf-8") as f:
        f.write(render_all(good))
    with open(os.path.join(OUT, "about.html"), "w", encoding="utf-8") as f:
        f.write(render_about())
    for it in good:
        related = [r for r in good if r.get("category") == it.get("category")
                   and r.get("slug") != it.get("slug")][:4]
        with open(os.path.join(CLAIMS, it["slug"] + ".html"), "w", encoding="utf-8") as f:
            f.write(detail_page(it, related))
    # 报告
    feat = sum(1 for it in good if it.get("featured"))
    print(f"✓ 发布 {len(good)} 条（精选 {feat}）+ {len(good)} 个详情页 → docs/")
    if blocked:
        print(f"\n⚠️  发布闸门拦下 {len(blocked)} 条（未上线）：")
        for fn, errs in blocked:
            print(f"   ✗ {fn}: {'; '.join(errs)}")
    else:
        print("✓ 发布闸门：全部通过，无未来日期/缺来源/未审核条目")


if __name__ == "__main__":
    main()

```


## 11. `collect.py`（收集引擎，含 PubMed）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集引擎 v3：从 data/sources.json 抓 RSS / YouTube / PubMed，去重，产出"候选条目"。

v3 新增 PubMed 源（type: pubmed）：
  esearch 按主题找最新论文 PMID → efetch 抓免费摘要 → 候选。
  PubMed / E-utilities 完全免费，低频无需 API key。

候选写到 /tmp/health_candidates.json —— 由 Claude 按健康库 7 铁律摘要成
data/items/*.json，再跑 build.py 上站。

纯标准库。用法：
    python3 collect.py                 # 抓全部信源
    python3 collect.py PubMed Attia    # 只抓名字匹配的
"""
import json, os, sys, glob, re, html, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "data", "sources.json")
ITEMS = os.path.join(ROOT, "data", "items")
OUT = "/tmp/health_candidates.json"
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}
PER_SOURCE = 5
DESC_CHARS = 2500

ATOM = '{http://www.w3.org/2005/Atom}'
MEDIA = '{http://search.yahoo.com/mrss/}'
CONTENT = '{http://purl.org/rss/1.0/modules/content/}encoded'
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MON = {'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
       'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=25).read()


def t(el):
    return (el.text or '').strip() if el is not None else ''


def clean_text(s):
    s = s or ''
    s = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', s)
    s = re.sub(r'(?s)<[^>]+>', ' ', s)
    s = html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def norm_date(s):
    s = (s or '').strip()
    if not s:
        return ''
    m = re.match(r'(\d{4}-\d{2}-\d{2})', s)
    if m:
        return m.group(1)
    try:
        return parsedate_to_datetime(s).strftime('%Y-%m-%d')
    except Exception:
        return s[:10]


def mon(m):
    m = (m or '').strip()
    if m[:3].lower() in MON:
        return MON[m[:3].lower()]
    return m.zfill(2) if m.isdigit() else '01'


def parse_feed(raw):
    out = []
    root = ET.fromstring(raw)
    entries = root.findall(f'.//{ATOM}entry')
    if entries:
        for e in entries:
            link_el = e.find(f'{ATOM}link')
            mg = e.find(f'{MEDIA}group')
            desc = t(mg.find(f'{MEDIA}description')) if mg is not None else ''
            out.append({'title': t(e.find(f'{ATOM}title')),
                        'url': link_el.get('href', '') if link_el is not None else '',
                        'published': norm_date(t(e.find(f'{ATOM}published')) or t(e.find(f'{ATOM}updated'))),
                        'desc': clean_text(desc)})
    else:
        for it in root.findall('.//item'):
            body = t(it.find(CONTENT)) or t(it.find('description'))
            out.append({'title': t(it.find('title')), 'url': t(it.find('link')),
                        'published': norm_date(t(it.find('pubDate'))), 'desc': clean_text(body)})
    return out


def fetch_pubmed(query, n=PER_SOURCE):
    """PubMed：按主题找最新论文，抓免费摘要。返回 [{title,url,published,desc,journal}]"""
    es = (f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&sort=date&retmax={n}"
          f"&tool=health-hot&term=" + urllib.parse.quote(query))
    ids = json.loads(fetch(es).decode()).get('esearchresult', {}).get('idlist', [])
    if not ids:
        return []
    time.sleep(0.4)
    ef = (f"{EUTILS}/efetch.fcgi?db=pubmed&retmode=xml&rettype=abstract"
          f"&tool=health-hot&id=" + ",".join(ids))
    root = ET.fromstring(fetch(ef))
    out = []
    for art in root.findall('.//PubmedArticle'):
        pmid = art.findtext('.//MedlineCitation/PMID') or ''
        a = art.find('.//Article')
        if a is None:
            continue
        tnode = a.find('ArticleTitle')
        title = ''.join(tnode.itertext()).strip() if tnode is not None else ''
        parts = []
        for ab in a.findall('.//Abstract/AbstractText'):
            lab = ab.get('Label')
            txt = ''.join(ab.itertext()).strip()
            if txt:
                parts.append((f"{lab}：" if lab else "") + txt)
        abstract = clean_text(' '.join(parts))
        journal = a.findtext('.//Journal/Title') or ''
        pd = a.find('.//Journal/JournalIssue/PubDate')
        published = ''
        if pd is not None:
            y = pd.findtext('Year')
            if y:
                published = f"{y}-{mon(pd.findtext('Month'))}-01"
            elif pd.findtext('MedlineDate'):
                published = pd.findtext('MedlineDate')[:4] + "-01-01"
        out.append({'title': title, 'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    'published': published, 'desc': abstract, 'journal': journal})
    return out


def seen_urls():
    s = set()
    for f in glob.glob(os.path.join(ITEMS, '*.json')):
        try:
            s.add(json.load(open(f, encoding='utf-8')).get('source_url', ''))
        except Exception:
            pass
    return s


def main():
    filt = [x.lower() for x in sys.argv[1:]]
    sources = json.load(open(SRC, encoding='utf-8'))['sources']
    if filt:
        sources = [s for s in sources if any(f in s['name'].lower() for f in filt)]
    seen = seen_urls()
    cands = []
    for s in sources:
        try:
            if s['type'] == 'pubmed':
                entries = fetch_pubmed(s['query'])
            else:
                url = (f"https://www.youtube.com/feeds/videos.xml?channel_id={s['channel_id']}"
                       if s['type'] == 'youtube' else s['url'])
                entries = parse_feed(fetch(url))
        except Exception as ex:
            print(f"[!] {s['name']}: 失败 — {ex}")
            continue
        new = 0
        for e in entries[:PER_SOURCE]:
            if not e['url'] or e['url'] in seen:
                continue
            src = (e['journal'] + " · PubMed") if e.get('journal') else s['name']
            cands.append({'source': src, 'category': s.get('category', ''),
                          'evidence': s.get('evidence', 'expert'),
                          'title': e['title'], 'source_url': e['url'],
                          'published': e['published'], 'desc': e['desc'][:DESC_CHARS]})
            seen.add(e['url'])
            new += 1
        print(f"[✓] {s['name']}: 共 {len(entries)} 条，新增候选 {new} 条")
    json.dump(cands, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"\n共 {len(cands)} 条候选 → {OUT}")
    for c in cands:
        print(f"  · [{c['source'][:28]} | {c['published']}] {c['title'][:42]}  （{len(c['desc'])}字）")


if __name__ == '__main__':
    main()

```


## 12. `data/sources.json`

```json
{
  "_说明": "健康信源清单。type: youtube(channel_id) / rss(url) / pubmed(query)。category/evidence 是默认标签，每条由摘要时再定。PubMed 用 E-utilities，免费无需 key；query 用 [pt] 选论文类型 + humans[mh] 过滤人类研究（避免混进兽医/材料学）。",
  "sources": [
    {"name": "Peter Attia MD", "type": "youtube", "channel_id": "UC8kGsMa0LygSX9nkBcBH1Sg", "category": "长寿", "evidence": "expert"},
    {"name": "Huberman Lab", "type": "youtube", "channel_id": "UC2D2CMWXMOVWx7giW1n3LIg", "category": "睡眠", "evidence": "expert"},
    {"name": "FoundMyFitness", "type": "youtube", "channel_id": "UC5fdyC4LxyyYv8Am6nDrkmg", "category": "营养", "evidence": "expert"},
    {"name": "Bryan Johnson", "type": "youtube", "channel_id": "UCnRVL1-HJnXWB_Xi2dAoTcg", "category": "长寿", "evidence": "expert"},
    {"name": "Huberman Lab Podcast", "type": "rss", "url": "https://feeds.megaphone.fm/hubermanlab", "category": "睡眠", "evidence": "expert"},
    {"name": "FoundMyFitness Podcast", "type": "rss", "url": "https://podcast.foundmyfitness.com/rss.xml", "category": "营养", "evidence": "expert"},
    {"name": "Bryan Johnson (Medium)", "type": "rss", "url": "https://bryan-johnson.medium.com/feed", "category": "长寿", "evidence": "expert"},

    {"name": "PubMed·间歇禁食RCT", "type": "pubmed", "query": "intermittent fasting AND randomized controlled trial[pt] AND humans[mh]", "category": "营养", "evidence": "rct"},
    {"name": "PubMed·肌酸综述", "type": "pubmed", "query": "creatine supplementation AND review[pt] AND humans[mh]", "category": "补剂", "evidence": "meta"},
    {"name": "PubMed·Omega-3 RCT", "type": "pubmed", "query": "omega-3 fatty acids AND randomized controlled trial[pt] AND humans[mh]", "category": "补剂", "evidence": "rct"},
    {"name": "PubMed·心肺功能与死亡率", "type": "pubmed", "query": "cardiorespiratory fitness AND mortality AND humans[mh]", "category": "运动", "evidence": "observational"},
    {"name": "PubMed·长寿综述", "type": "pubmed", "query": "(longevity OR healthy aging) AND review[pt] AND humans[mh]", "category": "长寿", "evidence": "meta"}
  ],
  "_未来扩展": [
    "中文权威（丁香医生/卓正/果壳/张文宏）——需自托管 RSSHub",
    "ScienceDaily 健康（科学新闻稿，需重度筛选）: https://www.sciencedaily.com/rss/health_medicine.xml"
  ]
}

```


## 13. 全部核验内容（22 条，结构化字段）


### 绝经后女性补肌酸：小幅长肌力，且安全  `creatine-postmenopausal-muscle`
- 分类 `补剂` · 证据 `meta` · 精选 True(rank 80) · status `reviewed`
- 一句话结论：肌酸配合抗阻训练，对绝经后女性瘦体重和腿力有小但确实的提升，且安全。
- 适用于谁：绝经后女性（约 600 名受试者）。
- 需要注意：增益为「小但确实」，需剂量足够并配合抗阻训练，否则无效；骨密度无明显变化。具体剂量见原文，按需问医生。
- 来源：J Int Soc Sports Nutr · 7 项 RCT 荟萃 · https://pubmed.ncbi.nlm.nih.gov/42141930/
- date=2026-05-31 / source_published_at=2026-12-01 / reviewed_at=2026-05-31
- 摘要：7 项 RCT（约 600 名绝经后女性）荟萃：肌酸**在剂量足够、且配合抗阻训练**时，瘦体重和腿部力量有小但确实的提升；剂量不足又不训练则无效。骨密度无明显变化；肾功能等安全指标与安慰剂一致、无害迹象。（具体剂量见原文，按需问医生。）


### 跳跃类运动增骨密度，可能比举铁更管用  `jump-rope-bone-density`
- 分类 `骨骼` · 证据 `meta` · 精选 True(rank 92) · status `reviewed`
- 一句话结论：跳跃类高冲击运动增骨密度，Meta 分析显示可能优于抗阻训练。
- 适用于谁：summary 主要提到绝经前女性；其他人群见原文核对。
- 需要注意：部分研究用的是"原地纵跳"，严格的"跳绳专项"证据还不算多；是否适合自己请就医核对。
- 来源：Miao 2025（Meta 分析）+ Tucker 2015（RCT） · https://pubmed.ncbi.nlm.nih.gov/40611942/
- date=2026-05-29 / source_published_at=2026-05-29 / reviewed_at=2026-05-31
- 摘要：论"练骨头"，跳跃/蹦跳类高冲击运动的增骨密度效果，Meta 分析显示可能比抗阻训练还好。绝经前女性每天只跳一二十下，几个月后髋部骨密度就明显提升。担心骨质疏松的，跳绳可能比你以为的更对路。（注：部分研究用的是"原地纵跳"，严格的"跳绳专项"证据还不算多。）


### 运动可能并不能"独立"预防肾结石  `exercise-kidney-stones`
- 分类 `代谢` · 证据 `observational` · 精选 True(rank 88) · status `reviewed`
- 一句话结论：扣除体重饮食后，运动与肾结石无独立关联。
- 适用于谁：未特别限定，见原文
- 需要注意：观察性研究，不能证明因果；运动或仅通过控体重间接相关，靠运动直接预防结石暂无直接证据。
- 来源：Ferraro & Curhan 2015（大型队列） · https://pubmed.ncbi.nlm.nih.gov/25229560/
- date=2026-05-29 / source_published_at=2026-05-29 / reviewed_at=2026-05-31
- 摘要：一项合并二十多万人的研究，在扣掉体重、饮食后发现运动与结石"没有"独立关系——运动可能只是通过帮你控制体重间接沾边。真正防结石的硬道理朴素得很：多喝水、控体重、别久坐。靠跳绳预防结石形成，目前一篇直接证据都没有。


### 越练越难飙到高心率，是心脏变强不是退步  `training-bradycardia`
- 分类 `心肺` · 证据 `expert` · 精选 True(rank 85) · status `reviewed`
- 一句话结论：静息心率变慢、同等活动心率更低，是心肺变强而非退步。
- 适用于谁：未特别限定，见原文
- 需要注意：本条目基于机制综述（expert 级证据）。若出现莫名心慌、胸闷、头晕，属另一回事，应及时就医。
- 来源：Coote & White 2015（机制综述） · https://pubmed.ncbi.nlm.nih.gov/25871550/
- date=2026-05-29 / source_published_at=2026-05-29 / reviewed_at=2026-05-31
- 摘要：练久了爬同样的楼、心率却上不去，很多人以为退步——其实是"训练适应"：心脏每跳打出去的血更多，同样的活动不需要那么快的心跳。静息心率变慢、干同样活儿心率更低，恰恰是心肺变好的信号。（提醒：莫名心慌、胸闷、头晕是另一回事，该看医生。）


### 总觉得身体僵？几个在家能做的活动度自测  `mobility-self-tests`
- 分类 `关节` · 证据 `expert` · 精选 True(rank 78) · status `reviewed`
- 一句话结论：把活动度当成可长期维持、不必随龄必然退化的能力。
- 适用于谁：未特别限定，见原文
- 需要注意：坐下-起立测试与死亡率的关联来自观察性研究，并非因果；自测请量力而行，不适感或有伤病应停止。
- 来源：FoundMyFitness · Rhonda Patrick × Kelly Starrett · https://www.youtube.com/watch?v=_i6vnLnwNC4
- date=2026-05-29 / source_published_at=2026-05-29 / reviewed_at=2026-05-31
- 摘要：Kelly Starrett 给了几个在家能做的活动度自测：坐下-起立测试（sit-and-rise，有观察性研究与死亡率相关，但不是因果）、沙发拉伸测髋伸展、能不能舒服地坐地上。要点不是「达标」，而是把活动度当成可长期维持、不必随龄必然退化的能力。专家观点 + 实操，自测量力而行。


### 只跳绳、不改饮食，八周几乎不掉脂  `jump-rope-diet-fat-loss`
- 分类 `运动` · 证据 `rct` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：光跳绳不改饮食八周几乎不掉脂，配合少吃才真瘦。
- 适用于谁：未特别限定，见原文
- 需要注意：结论基于单项八周三臂 RCT，样本与具体方案见原文核对；减脂以控制饮食为主，跳绳无特殊燃脂魔法。
- 来源：Tang 2021（三臂 RCT） · https://pubmed.ncbi.nlm.nih.gov/34579097/
- date=2026-05-29 / source_published_at=2026-05-29 / reviewed_at=2026-05-31
- 摘要：把人分成"只控饮食 / 只跳绳 / 又控又跳"三组，八周后——光跳绳不改饮食那组，体脂、血脂、胰岛素几乎没动；只有配合少吃才真瘦。你瘦不瘦主要看吃多少，跳绳没有"特殊燃脂魔法"。


### 单摇跳绳对膝、髋的冲击，其实低于跑步  `jump-rope-knee-impact`
- 分类 `关节` · 证据 `observational` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：单摇、落地轻、姿势对时，跳绳对膝髋冲击可低于跑步
- 适用于谁：未特别限定，见原文
- 需要注意：结论限于单摇、落地轻、姿势正确的前提；花式双摇、硬地猛跳不适用。证据为观察性研究（observational），并非随机对照，需谨慎；有关节不适请就医核对。
- 来源：Mullerpatan 2021 · https://pubmed.ncbi.nlm.nih.gov/33992227/
- date=2026-05-29 / source_published_at=2026-05-29 / reviewed_at=2026-05-31
- 摘要：跟"跳绳毁膝盖"的直觉相反：有研究实测，单脚轻弹式跳绳对膝、髋的冲击比跑步还低一些。前提是单摇、落地轻、姿势对；花式双摇、硬地猛跳就另说了。


### 悲伤的科学：它和抑郁不是一回事  `grief-neuroscience`
- 分类 `心理` · 证据 `expert` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：悲伤是大脑重塑关系神经回路的过程，与抑郁不是一回事。
- 适用于谁：未特别限定，见原文
- 需要注意：属专家科普，原文未给出研究细节/样本，工具（书写情绪、规律光照等）效果见原文核对；悲伤与抑郁需区分，必要时就医。
- 来源：Huberman Lab · Andrew Huberman · https://www.hubermanlab.com/episode/essentials-the-science-and-process-of-healing-from-grief
- date=2026-05-28 / source_published_at=2026-05-28 / reviewed_at=2026-05-31
- 摘要：Huberman 讲悲伤的神经科学：①大脑按「空间-时间-亲近度」给关系建图，失去某人需要重塑这套神经回路；②悲伤 ≠ 抑郁；③睡眠和皮质醇节律影响你能否适应性地度过；催产素解释了为何「思念」如此强烈。也提到书写情绪、规律光照等工具。专家科普。


### 被忽略的肌群与无伤训练  `overlooked-muscles-injury-free-training`
- 分类 `运动` · 证据 `expert` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：想练到七八十岁，别只练大肌群，肩袖、颈、足等被忽略的肌肉同样关键。
- 适用于谁：未特别限定，见原文；面向希望长期无痛训练的人群。
- 需要注意：内容为物理治疗师的个人经验与实操方法论（evidence 标注为 expert），非随机对照研究结论；腰痛等问题成因多样，出现持续疼痛或伤病请就医评估，勿仅凭经验自我处理。
- 来源：Huberman Lab · Jeff Cavaliere（物理治疗师） · https://www.hubermanlab.com/episode/build-muscle-great-posture-and-resilience-to-injury-jeff-cavaliere
- date=2026-05-25 / source_published_at=2026-05-25 / reviewed_at=2026-05-31
- 摘要：物理治疗师 Jeff Cavaliere 谈长期无痛训练的关键：①腰痛常和臀肌无力有关，可用走路类动作先激活、再强化臀肌；②用「老人测试」（从地上单脚起身）查功能性力量；③别只练大肌群——肩袖、颈、足这些「被忽略的」肌肉和结缔组织，决定你能不能一直练到七八十岁。偏实操方法论，专家经验。


### 降社交焦虑：和陌生人的小互动被低估了  `social-anxiety-small-talk`
- 分类 `心理` · 证据 `expert` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：对搭话的悲观预期多半是错的，小互动能改善身心健康。
- 适用于谁：未特别限定，见原文
- 需要注意：证据为专家观点（非随机对照试验），具体研究细节、样本与适用边界见原文核对。
- 来源：Huberman Lab · Nick Epley 教授 · https://www.hubermanlab.com/episode/how-to-overcome-social-anxiety-nick-epley
- date=2026-05-18 / source_published_at=2026-05-18 / reviewed_at=2026-05-31
- 摘要：社会连接研究者 Epley：①我们总高估「主动搭话会尴尬 / 被嫌弃」，数据显示这些悲观预期大多是错的；②哪怕和陌生人的小互动，也能实打实改善身心健康；③降社交焦虑的可行工具是「小步测试 + 修正预期」。专家观点 + 实操。


### 运动悖论：上班的体力活，可能不像休闲运动那样护心  `physical-activity-paradox`
- 分类 `运动` · 证据 `observational` · 精选 True(rank 84) · status `reviewed`
- 一句话结论：上班的体力劳动不等于护心运动，休闲运动才可靠降低心血管与死亡风险。
- 适用于谁：未特别限定，见原文
- 需要注意：证据仍偏弱、属观察性研究，工作体力活动的关联不一致，机制尚不确定，结论需谨慎，见原文核对。
- 来源：Int J Behav Nutr Phys Act · 综述 · https://pubmed.ncbi.nlm.nih.gov/42104355/
- date=2026-05-01 / source_published_at=2026-05-01 / reviewed_at=2026-05-31
- 摘要：「体力活动健康悖论」：休闲时的运动（跑步、健身）可靠地降低死亡与心血管风险；但**工作中的体力劳动**（搬运、长时间站走）关联却不一致、有时反而有害。可能机制：长时间无恢复的心血管负荷、动脉硬化、慢性炎症。证据仍偏弱，但提示「上班很累」≠「运动够了」。


### 任何年纪开始运动都不晚（对心血管）  `exercise-any-age-cardiovascular`
- 分类 `运动` · 证据 `observational` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：任何年纪开始规律运动，都能改善心血管健康。
- 适用于谁：各年龄段，尤其上了年纪、起步较晚者；具体人群见原文。
- 需要注意：证据为观察性综述（非随机对照），存在因果与混杂局限；具体运动强度、方式与剂量见原文核对。
- 来源：Clinics in Geriatric Medicine · 综述 · https://pubmed.ncbi.nlm.nih.gov/42161438/
- date=2026-05-01 / source_published_at=2026-05-01 / reviewed_at=2026-05-31
- 摘要：心肺功能随年龄下降会大幅抬高心血管病、衰弱、失能风险，久坐加速这一切。综述结论：规律运动能减缓与年龄相关的心肺功能下降、改善血管与代谢、降低发病与死亡——**即便上了年纪、身体适应变慢，仍有实打实的改善空间**。运动是心血管健康的基石。


### 关节活动度，可以不随年龄必然下降  `joint-mobility-aging`
- 分类 `关节` · 证据 `expert` · 精选 True(rank 86) · status `reviewed`
- 一句话结论：活动度不必随年龄必然下降，但长期不练几乎注定退化。
- 适用于谁：未特别限定，见原文
- 需要注意：本条为单一专家（Kelly Starrett）观点，重在方法论框架，非临床研究结论；具体方法见原文核对。
- 来源：FoundMyFitness 播客 #111 · Kelly Starrett · https://foundmyfitness.libsyn.com/111-the-optimal-mobility-protocol-for-a-durable-body-dr-kelly-starrett
- date=2026-04-24 / source_published_at=2026-04-24 / reviewed_at=2026-05-31
- 摘要：Kelly Starrett 的观点：活动度（ROM）是少数「不必随年龄必然下降」的生理维度，但长期不练几乎注定退化。本期讲怎么用日常动作模式维持身体耐用度。专家观点，重在方法论框架。


### 限时进食能降心梗患者的炎症？一个小型 RCT  `intermittent-fasting-mi`
- 分类 `营养` · 证据 `rct` · 精选 True(rank 82) · status `reviewed`
- 一句话结论：限时进食或降心梗患者炎症指标，属早期信号，别当定论。
- 适用于谁：有心梗病史／已有冠心病的患者（样本仅 19 人）
- 需要注意：样本很小、仅 2 周、看的是炎症指标而非「少发心梗」等硬结局，属早期信号，需就医个体化评估。
- 来源：J Am Heart Assoc · 随机交叉试验 · https://pubmed.ncbi.nlm.nih.gov/41859904/
- date=2026-04-01 / source_published_at=2026-04-01 / reviewed_at=2026-05-31
- 摘要：19 名有心梗病史的患者，做 2 周限时进食（每天 8–14 点之间吃）后，中性粒细胞、低度系统性炎症指标下降，单核细胞转向抗炎。提示限时进食或能帮已有冠心病的人降风险——但**样本很小、只 2 周、看的是炎症指标而非「少发心梗」这种硬结局**，属早期信号，别当定论。


### 幸福不是追来的：几件可训练的事  `trainable-happiness-brooks`
- 分类 `心理` · 证据 `expert` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：幸福需享受+满足+意义三者，感恩、反向愿望清单、运动可主动调节。
- 适用于谁：未特别限定；summary 特别提到高成就者易陷「奋斗者的诅咒」，见原文
- 需要注意：本条为专家观点与方法论（evidence: expert），非临床研究结论；「运动作用可比拟抗抑郁」为讲者本人说法，情绪困扰请就医，详见原文核对。
- 来源：FoundMyFitness 播客 #110 · Arthur Brooks · https://foundmyfitness.libsyn.com/110-how-to-build-lasting-happiness-dr-arthur-brooks
- date=2026-03-24 / source_published_at=2026-03-24 / reviewed_at=2026-05-31
- 摘要：社会科学家 Arthur Brooks 几个反直觉点：①幸福需要「享受 + 满足 + 意义」三者，光追快乐反而空；②高成就者常陷「奋斗者的诅咒」，满足感越来越短；③练感恩、列「反向愿望清单」、规律运动（他说运动对情绪的作用可比拟抗抑郁）都能调节。专家观点、方法论为主。


### NAD 与衰老：哪些干预真有人体数据  `nad-aging-interventions`
- 分类 `长寿` · 证据 `expert` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：NAD 补剂要分清「机制说得通」与「真有人体证据」，别照搬。
- 适用于谁：未特别限定，见原文
- 需要注意：需区分机制合理与人体证据，市面补剂良莠不齐，具体剂量与产品请回看原始研究核对。
- 来源：FoundMyFitness 播客 #109 · Charles Brenner · https://foundmyfitness.libsyn.com/109-how-to-boost-nad-levels-to-fight-inflammation-improve-recovery-and-slow-aging-dr-charles-brenner
- date=2026-02-09 / source_published_at=2026-02-09 / reviewed_at=2026-05-31
- 摘要：不少「衰老症状」也符合慢性炎症 + NAD 代谢受损。Brenner（NAD 领域研究者）讲机制和人体数据，并对市面上一堆 NAD 补剂去伪存真。听点在于分清「机制说得通」和「真有人体证据」——具体补剂别照搬，回看原始研究。


### 种子油真有那么坏吗？一次把证据捋清  `seed-oils`
- 分类 `营养` · 证据 `expert` · 精选 True(rank 80) · status `reviewed`
- 一句话结论：种子油未被证明独有害，总热量、纤维、活动量才是关键。
- 适用于谁：未特别限定，见原文
- 需要注意：饱和脂肪与多不饱和脂肪的权衡缺人体试验定论，仍属争议；专家建议别凭直觉、去读原始研究。
- 来源：Peter Attia × Layne Norton 博士 · The Drive #380 · https://www.youtube.com/watch?v=7_cbaDXAWYM
- date=2026-01-21 / source_published_at=2026-01-21 / reviewed_at=2026-05-31
- 摘要：围绕「种子油是否独有害」，两人把几个流行说法逐个查：①「己烷残留」——提取用的己烷在加工中被蒸汽蒸掉，要达到危害得一次吃上万公斤油，不现实；②真正的权衡是「饱和脂肪（猪油）减少氧化但升 LDL」对「多不饱和（种子油）反之」，缺人体试验定论；③比纠结用哪种油重要得多的，是总热量、纤维、活动量——「盯着炸薯条的油，错过了真正的疾病驱动」。专家梳理、结论是他们反复说的：别凭直觉，去读原始研究。


### 补肌酸会搞坏血脂吗？荟萃说：不会  `creatine-lipids`
- 分类 `补剂` · 证据 `meta` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：8 项 RCT 荟萃显示肌酸对血脂无临床意义影响。
- 适用于谁：未特别限定，见原文
- 需要注意：证据确定性偏低，仍需更大样本确认；具体剂量/人群见原文核对。
- 来源：Frontiers in Nutrition · 8 项 RCT 荟萃 · https://pubmed.ncbi.nlm.nih.gov/42180567/
- date=2026-01-01 / source_published_at=2026-01-01 / reviewed_at=2026-05-31
- 摘要：针对「补肌酸是否影响血脂」的担心，8 项随机对照试验的荟萃：肌酸对总胆固醇、LDL、HDL、甘油三酯**都没有临床意义上的影响**。也就是说，常见的「肌酸伤血脂」担忧，目前证据不支持。（不过证据确定性偏低，仍需更大样本确认。）


### 哪种运动对长寿最有用？  `exercise-intensity-longevity`
- 分类 `运动` · 证据 `expert` · 精选 True(rank 90) · status `reviewed`
- 一句话结论：剧烈运动对延寿或更高效，但属专家梳理而非定论。
- 适用于谁：未特别限定，见原文
- 需要注意：为专家梳理而非单一 RCT 定论，「1 分钟抵 10 分钟」为节目中说法，建议先听论证再回看原始研究核对。
- 来源：FoundMyFitness 播客 #108（Rhonda Patrick） · https://foundmyfitness.libsyn.com/108-the-best-type-of-exercise-for-longevity
- date=2025-12-07 / source_published_at=2025-12-07 / reviewed_at=2026-05-31
- 摘要：本期聊不同强度运动对寿命的影响，提到「1 分钟剧烈运动可能抵约 10 分钟中等强度」的说法。属专家梳理（非单一 RCT 定论），适合先听其论证、再回看背后的原始研究——我们站内也有相关研究条目可对照。


### 失眠：不靠药能怎么改善  `insomnia-cbt-i`
- 分类 `睡眠` · 证据 `expert` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：CBT-I 与刺激控制是有科学支持的非药物失眠干预手段。
- 适用于谁：慢性失眠及未治疗睡眠呼吸暂停人群；其余未特别限定，见原文。
- 需要注意：属专家梳理而非随机对照试验结论；严重或长期睡眠问题仍需就医评估，具体方案见原文核对。
- 来源：FoundMyFitness 播客 #107 · Michael Grandner · https://foundmyfitness.libsyn.com/107-how-to-cure-insomnia-without-pills-fall-asleep-dr-michael-grandner
- date=2025-10-02 / source_published_at=2025-10-02 / reviewed_at=2026-05-31
- 摘要：慢性失眠和未治疗的睡眠呼吸暂停会明显伤认知与恢复力。Grandner 讲了几条有科学支持的非药物干预，重点是 CBT-I（失眠认知行为疗法）和刺激控制。属专家梳理；严重或长期睡眠问题仍需就医评估。


### 你的「衰老速度」其实能测  `aging-pace-test`
- 分类 `长寿` · 证据 `observational` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：有测试能估衰老速度，速度略高于1关联未来7年更高死亡与慢病风险。
- 适用于谁：未特别限定，见原文
- 需要注意：证据为观察性研究（DunedinPACE 等纵向研究），仅显示相关而非因果；作者「12 个月逆转 31 年」属个人自测、营销色彩重，应当概念看、别当目标。
- 来源：Bryan Johnson · Medium · https://medium.com/future-literacy/how-fast-are-you-aging-e845830d8a3c
- date=2022-11-08 / source_published_at=2022-11-08 / reviewed_at=2026-05-31
- 摘要：有一类测试（如 DunedinPACE，基于多年纵向研究）能估你「每过 1 年、身体老了多少」。研究提示：衰老速度略高于 1，就和未来 7 年更高的死亡与慢病风险相关。作者用它追踪自己——但他「12 个月逆转 31 年」属个人自测、营销色彩重，**当概念看、别当目标**。


### 「每天八杯水」——你怎么知道这是对的？  `eight-glasses-water-how-do-you-know`
- 分类 `营养` · 证据 `blogger` · 精选 False(rank 0) · status `reviewed`
- 一句话结论：分清「真的知道」和「只是听说」，是抵御伪健康信息的第一步。
- 适用于谁：未特别限定，见原文（作者也指出饮水量因人而异）
- 需要注意：这是观点 / 方法分享，非健康建议，证据级别为博主观点；「八杯水」只是被质疑的常识说法，作者并未给出推荐饮水量，具体饮水量因人而异，见原文核对。
- 来源：Bryan Johnson · Medium · https://medium.com/future-literacy/how-much-water-should-i-drink-552be7d300e5
- date=2022-10-07 / source_published_at=2022-10-07 / reviewed_at=2026-05-31
- 摘要：一个思维实验：朋友问「每天该喝几杯水」，多数人脱口「八杯」——但追问「你怎么知道」，会发现只是在重复听来的常识，没真见过证据。作者的点不在水，在于：分清「我真的知道」和「我只是听说」，是抵御伪健康信息的第一步。（这是观点 / 方法分享，非健康建议；饮水量因人而异。）
