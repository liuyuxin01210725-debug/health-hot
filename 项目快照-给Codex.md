# 查过再信 / health-hot — 项目快照（供 Codex 审查）

> 这是一个个人健康资讯聚合站的完整快照：架构 + 全部源码 + 全部内容 + 审查重点。
> 目的：请 Codex 从代码正确性、健壮性、内容安全、架构合理性等角度审一遍。

---

## 1. 这是什么

「查过再信」是一个**循证、按证据分级的中文健康资讯流**（仿 AI HOT 的模式，但做健康、走自己的浅色风格）。
- 从权威信源（健康播客 / YouTube / PubMed）抓取 → 按「7 铁律」摘要成卡片 → 生成静态站 → GitHub Pages 上线。
- 站长是**无编程背景**的个人，强调：纯 Python 标准库、零第三方依赖、可一句话维护。

## 2. 线上 / 仓库

- 线上：https://liuyuxin01210725-debug.github.io/health-hot/
- 仓库：GitHub `liuyuxin01210725-debug/health-hot`（公开）
- 本地：`~/Documents/AI health/`

## 3. 架构与数据流

```
data/sources.json   信源清单（youtube=channel_id / rss=url / pubmed=query）
      │
      ▼  collect.py   抓取 + 去重（RSS/Atom 解析；PubMed 走免费 E-utilities）
/tmp/health_candidates.json   候选条目（含正文/摘要）
      │
      ▼  [人工 / Claude 按 7 铁律 摘要]   ← 质量关口，非自动
data/items/*.json   每条 = 一张卡片（结构化）
      │
      ▼  build.py   渲染 → docs/{index,all,about}.html + styles.css
      │
      ▼  git push → GitHub Pages（main 分支 /docs 目录）
```

- **无后端、无数据库、无构建框架。** 静态站。
- 部署：GitHub Pages 直接 serve `/docs`（因为当前 token 无 `workflow` 权限，未用 GitHub Actions）。

## 4. 技术栈与文件结构

- **纯 Python 3 标准库**（`collect.py` / `build.py`，零 `pip` 依赖）。
- 前端：原生 HTML/CSS + 少量内联 JS（搜索 / 分类筛选）。

```
AI health/
├── build.py            静态站生成器（读 data/items → 写 docs/）
├── collect.py          收集引擎（信源 → 候选）
├── data/
│   ├── sources.json    信源配置
│   └── items/*.json    22 张内容卡（每条一个 JSON）
├── docs/               构建产物（GitHub Pages serve 这个目录）
├── README.md
└── .gitignore          忽略 public/、__pycache__、内部文档
```

## 5. 数据模型

**item（data/items/*.json）字段：**
- `title` 标题 · `source` 来源名 · `source_url` 原文链接（铁律2：必有）
- `date` (YYYY-MM-DD) · `category`（运动/营养/补剂/睡眠/长寿/骨骼/代谢/心肺/关节/心理）
- `featured` (bool, 是否进精选) · `rank` (int, 精选排序)
- `evidence` ∈ `rct|meta|observational|expert|blogger`（铁律1：证据分级）
- `summary` 推荐理由（从正文提炼的要点）

**sources.json：** `type` ∈ `youtube`(channel_id) / `rss`(url) / `pubmed`(query)。

## 6. 内容规则（7 铁律 — 内容安全约束，审查时请据此核对）

这是从健康知识库继承的硬约束，**摘要时必须遵守**：
1. **证据分级强制**：每条标 rct/meta/observational/expert/blogger。
2. **引用追溯**：每条必有可点击 source_url。
3. **不给具体剂量**：补剂/方案类只讲原则、方向，不写具体克数（剂量留给原文）。
4. **医疗免责**：站内声明非医疗建议；涉就医的加提醒。
5. **不暗示治疗任何疾病**。
6. **标注不确定**：小样本/早期/阴性/有争议的明确标。
7. **版权**：只做「摘要 + 推荐理由 + 回原文链接」，绝不搬运全文。

## 7. 设计决策

- **浅色健康风**（非 AI HOT 的深色科技流）：白底、留白、柔和青绿、搜索前置、按主题筛选——为「可信感」服务。
- **知识库优先 + 轻量更新流**：健康信息更新慢，不做「日更新闻」假象，靠主题深度撑存在感。
- **信源求权威不求量**：刻意不加 STAT 等日更新闻流；X/推特因获取难 + 噪音大暂不接。
- **PubMed 是证据地基**：免费 E-utilities，能产出真 RCT/荟萃级卡片，把证据天花板从「专家说」抬到「研究说」。

## 8. 已知问题 / 给 Codex 的审查重点 ⭐

请重点看这些：

**代码正确性 / 健壮性**
- `collect.py` 的 PubMed XML 解析边界：无 Abstract、`MedlineDate` 而非 Year/Month、非 `PubmedArticle` 节点、`itertext()` 用法是否稳妥。
- RSS 与 Atom 双格式兼容是否有漏判；`content:encoded` 命名空间处理。
- 去重逻辑（按 source_url）是否够；NCBI E-utilities 的速率礼貌（`time.sleep`）与无 key 限制。
- 网络异常 / 超时的容错（单源失败不应中断整轮——目前用 try/except 跳过，请核对覆盖面）。

**build.py / 前端**
- HTML 转义：item 内容虽作者可控，但 `e()`（html.escape）覆盖是否完整，有无 XSS 面。
- `all.html` 的搜索/筛选内联 JS 健壮性（正则取 `?q=`、大小写、空态）。
- CSS：请扫一眼 `.why` 规则附近是否有**杂散分号 / 笔误**；移动端断点。

**内容安全（按第 6 节 7 铁律核对）**
- 抽查 `data/items/*.json` 的 `summary`：是否真的**不含具体剂量**、不暗示治疗、对小样本/阴性结果有标注。
- 版权：是否都只是摘要 + 回链，未实质搬运原文。
- `evidence` 等级标注是否与实际研究类型相符。

**架构 / 可维护性**
- 「静态站 + 人工摘要」这个取舍是否合理？瓶颈与扩展性。
- git author/email 硬编码在命令里（非全局配置）——是否更好的做法。
- 每周无人值守自动化方案（需 `workflow` scope + LLM API key）——给建议。

---

（以下为全部源码与内容，供逐行审查）

## 9. `build.py`（静态站生成器）

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
健康 HOT — 卡片式健康资讯流静态生成器（浅色健康风：干净 + 留白 + 搜索前置）。

读 data/items/*.json  ->  生成 public/{index,all,about}.html + styles.css
- index.html : 精选（featured=true，按 rank 排）—— 精华版
- all.html   : 全部（分类筛选 + 关键词搜索）—— 全部版
- about.html : 关于 / 方法论（亮出 6 条铁律当信任信号）

纯标准库，无依赖。用法：python3 build.py
"""
import json, glob, os, html
from collections import defaultdict

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "items")
OUT = os.path.join(ROOT, "docs")

SITE_TITLE = "查过再信"
SITE_SUB = "把听来的和有据的分开——每条都标了来源、证据强度，附可点击原文。"
EV_LABEL = {"rct": "RCT", "meta": "Meta", "observational": "观察",
            "expert": "专家", "blogger": "博主", "anecdote": "个例"}


def load_items():
    items = []
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            it = json.load(fh)
        it.setdefault("featured", False)
        it.setdefault("rank", 0)
        items.append(it)
    items.sort(key=lambda x: (x.get("date", ""), x.get("rank", 0)), reverse=True)
    return items


def e(s):
    return html.escape(str(s if s is not None else ""))


def card(it):
    feat = it.get("featured")
    badge = f'<span class="badge">✦ 精选</span>' if feat else ""
    ev = it.get("evidence")
    evtag = f'<span class="ev ev-{e(ev)}">{EV_LABEL.get(ev, e(ev))}</span>' if ev else ""
    cat = e(it.get("category", ""))
    url = e(it.get("source_url", ""))
    title = e(it.get("title", ""))
    title_html = (f'<a href="{url}" target="_blank" rel="noopener">{title}<span class="ext"> ↗</span></a>'
                  if url else title)
    search_blob = e((it.get("title", "") + " " + it.get("summary", "") + " " + it.get("category", "")))
    return (f'<article class="card" data-cat="{cat}" data-search="{search_blob}">\n'
            f'  <div class="meta"><span class="cat">{cat}</span>{evtag}'
            f'<span class="src">{e(it.get("source",""))}</span>'
            f'<span class="date">{e(it.get("date",""))}</span>{badge}</div>\n'
            f'  <h2 class="title">{title_html}</h2>\n'
            f'  <p class="why"><span class="why-tag">推荐理由</span>{e(it.get("summary",""))}</p>\n'
            f'</article>')


def shell(title, active, inner, extra_js=""):
    nav_items = [("精选", "index.html"), ("全部", "all.html"), ("关于", "about.html")]
    nav = "".join(
        f'<a class="navlink{" on" if lbl == active else ""}" href="{href}">{lbl}</a>'
        for lbl, href in nav_items)
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · {e(SITE_TITLE)}</title>
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header class="top">
  <div class="bar">
    <a class="brand" href="index.html"><span class="leaf">✚</span>{e(SITE_TITLE)}</a>
    <form class="search" action="all.html" method="get" role="search">
      <input type="search" name="q" placeholder="搜健康话题：土豆、肌酸、间歇禁食…" aria-label="搜索">
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


def render_index(items):
    feats = sorted([it for it in items if it.get("featured")],
                   key=lambda x: x.get("rank", 0), reverse=True)
    cards = "\n".join(card(it) for it in feats) or '<p class="empty">还没有精选条目。</p>'
    hero = (f'<section class="hero">'
            f'<h1>每条健康结论，<span class="hl">查过再信</span></h1>'
            f'<p class="lead">{e(SITE_SUB)}</p>'
            f'<form class="hero-search" action="all.html" method="get">'
            f'<input type="search" name="q" placeholder="想了解什么？土豆、肌酸、睡眠、间歇禁食…">'
            f'<button type="submit">查一下</button></form>'
            f'</section>')
    head = f'<div class="sec-head"><h2>本周精选</h2><a class="more" href="all.html">看全部 →</a></div>'
    return shell("精选", "精选", hero + head + '<section class="cards">' + cards + '</section>')


def render_all(items):
    cats = []
    for it in items:
        c = it.get("category", "")
        if c and c not in cats:
            cats.append(c)
    pills = '<button class="pill on" data-f="*">全部</button>' + \
            "".join(f'<button class="pill" data-f="{e(c)}">{e(c)}</button>' for c in cats)
    cards = "\n".join(card(it) for it in items)
    head = (f'<div class="sec-head"><h2>全部动态</h2>'
            f'<span class="muted">收集到的全部健康信息</span></div>'
            f'<div class="filters">{pills}</div>'
            f'<p class="result-note" id="note"></p>')
    js = '''<script>
function q(){const m=location.search.match(/[?&]q=([^&]*)/);return m?decodeURIComponent(m[1].replace(/\\+/g,' ')).trim():'';}
const cards=[...document.querySelectorAll('.card')];const note=document.getElementById('note');
let curF='*',curQ=q();
const si=document.querySelector('.search input');if(si&&curQ)si.value=curQ;
function apply(){let n=0;cards.forEach(c=>{
  const okF=curF==='*'||c.dataset.cat===curF;
  const okQ=!curQ||c.dataset.search.toLowerCase().includes(curQ.toLowerCase());
  const show=okF&&okQ;c.style.display=show?'':'none';if(show)n++;});
  note.textContent=curQ?`「${curQ}」匹配 ${n} 条`:'';}
document.querySelectorAll('.pill').forEach(p=>p.addEventListener('click',()=>{
  document.querySelectorAll('.pill').forEach(x=>x.classList.remove('on'));p.classList.add('on');curF=p.dataset.f;apply();}));
apply();
</script>'''
    return shell("全部", "全部", head + '<section class="cards">' + cards + '</section>', js)


def render_about():
    inner = '''<section class="hero slim"><h1>关于本站</h1>
<p class="lead">一个持续收集、查证的健康信息流。不是资讯搬运——每条都尽量查到原始研究、标出证据强度、附可点击出处。</p></section>
<section class="values">
<div class="val"><h3>证据分级</h3><p>每条标清是 RCT、Meta、观察性还是专家观点，不混为一谈。</p></div>
<div class="val"><h3>引用追溯</h3><p>每条附原始出处（PubMed / 期刊），你能点回去自己核对。</p></div>
<div class="val"><h3>不开处方</h3><p>涉及剂量、治疗的只讲原则，不给具体剂量、不暗示治某种病。</p></div>
<div class="val"><h3>医疗免责</h3><p>所有内容是科普整理，非医疗建议。执行前请咨询持证医生或注册营养师。</p></div>
<div class="val"><h3>标注不确定</h3><p>证据不足、研究打架的地方，明说"还没定论"。</p></div>
<div class="val"><h3>定期复核</h3><p>健康结论会过时，按半年节奏回头审。</p></div>
</section>
<p class="hint">凭什么信？不靠"我读了很多书"——靠每一条都能点回原文，你自己能核对。</p>'''
    return shell("关于", "关于", inner)


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
.top .bar{display:flex;align-items:center;gap:18px;height:62px}
.brand{display:flex;align-items:center;gap:7px;font-weight:800;font-size:20px;color:var(--ink)}
.brand:hover{text-decoration:none}
.leaf{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:8px;
  background:var(--accent);color:#fff;font-size:15px}
.search{flex:1;max-width:420px}
.search input{width:100%;border:1px solid var(--line);background:#fbfdfc;border-radius:999px;
  padding:9px 16px;font-size:14px;color:var(--ink)}
.search input:focus{outline:none;border-color:var(--accent);background:#fff}
.nav{display:flex;gap:6px;margin-left:auto}
.navlink{color:var(--muted);font-size:15px;padding:7px 13px;border-radius:8px}
.navlink:hover{background:var(--accent-soft);color:var(--accent-ink);text-decoration:none}
.navlink.on{color:var(--accent);font-weight:700}

.main{max-width:920px;margin:0 auto;padding:8px 22px 56px}
.hero{padding:46px 0 26px;text-align:center}
.hero.slim{padding:36px 0 12px}
.hero h1{margin:0 0 12px;font-size:34px;letter-spacing:.5px}
.hl{color:var(--accent)}
.lead{margin:0 auto 22px;color:var(--muted);font-size:16px;max-width:600px}
.hero-search{display:flex;gap:8px;max-width:540px;margin:0 auto}
.hero-search input{flex:1;border:1px solid var(--line);border-radius:12px;padding:13px 16px;font-size:15px;background:#fff}
.hero-search input:focus{outline:none;border-color:var(--accent)}
.hero-search button{background:var(--accent);color:#fff;border:none;border-radius:12px;
  padding:0 22px;font-size:15px;font-weight:700;cursor:pointer}
.hero-search button:hover{background:var(--accent-ink)}

.sec-head{display:flex;align-items:baseline;justify-content:space-between;margin:14px 0 14px;
  border-bottom:2px solid var(--line);padding-bottom:8px}
.sec-head h2{margin:0;font-size:21px}
.more{font-size:14px}.muted{color:var(--muted);font-size:14px}

.filters{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0 10px}
.pill{border:1px solid var(--line);background:#fff;color:var(--muted);border-radius:999px;
  padding:6px 15px;font-size:14px;cursor:pointer}
.pill:hover{color:var(--accent-ink);border-color:var(--accent)}
.pill.on{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:700}
.result-note{color:var(--muted);font-size:14px;margin:4px 0 0;min-height:1em}

.cards{display:flex;flex-direction:column;gap:14px;margin-top:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:18px 20px;
  box-shadow:0 1px 2px rgba(20,60,50,.03);transition:box-shadow .15s,transform .15s,border-color .15s}
.card:hover{box-shadow:0 8px 26px rgba(20,60,50,.08);transform:translateY(-1px);border-color:#cfe3db}
.meta{display:flex;flex-wrap:wrap;align-items:center;gap:9px;font-size:12.5px;color:var(--muted);margin-bottom:8px}
.cat{background:var(--accent-soft);color:var(--accent-ink);border-radius:7px;padding:2px 9px;font-weight:700}
.ev{border-radius:7px;padding:2px 8px;color:#fff;font-size:11.5px;font-weight:600}
.ev-rct{background:var(--rct)}.ev-meta{background:var(--meta)}.ev-observational{background:var(--obs)}
.ev-expert{background:var(--exp)}.ev-blogger,.ev-anecdote{background:var(--blog)}
.badge{margin-left:auto;background:#fff5e9;color:var(--warn);border:1px solid #f0d9bf;
  border-radius:7px;padding:2px 9px;font-size:11.5px;font-weight:800}
.title{margin:0 0 10px;font-size:19px;line-height:1.45}
.title a{color:var(--ink)}.title a:hover{color:var(--accent)}.ext{color:var(--muted);font-size:13px}
.why{margin:0;background:var(--accent-soft);border-radius:10px;padding:11px 14px;font-size:14.5px;color:#234};
.why-tag{display:inline-block;color:var(--accent-ink);font-weight:800;font-size:12px;margin-right:8px}

.values{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:18px 0}
.val{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.val h3{margin:0 0 6px;color:var(--accent-ink);font-size:16px}
.val p{margin:0;color:var(--muted);font-size:14px}
.hint{color:var(--muted);text-align:center;margin:18px 0}

.foot{border-top:1px solid var(--line);margin-top:30px;background:var(--panel)}
.foot .bar{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;padding:18px 22px;color:var(--muted);font-size:13px}
.empty{color:var(--muted);padding:30px 0}

@media(max-width:680px){
  .top .bar{flex-wrap:wrap;height:auto;padding:10px 16px;gap:10px}
  .search{order:3;max-width:none;flex-basis:100%}
  .hero h1{font-size:27px}.hero{padding:30px 0 18px}
}
'''


def main():
    os.makedirs(OUT, exist_ok=True)
    items = load_items()
    with open(os.path.join(OUT, "styles.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(items))
    with open(os.path.join(OUT, "all.html"), "w", encoding="utf-8") as f:
        f.write(render_all(items))
    with open(os.path.join(OUT, "about.html"), "w", encoding="utf-8") as f:
        f.write(render_about())
    feat = sum(1 for it in items if it.get("featured"))
    print(f"✓ 构建完成（浅色健康风）：{len(items)} 条（精选 {feat}）→ index/all/about.html")


if __name__ == "__main__":
    main()

```


## 10. `collect.py`（收集引擎）

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


## 11. `data/sources.json`

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


## 12. 全部内容卡（22 张，按日期排）


### 绝经后女性补肌酸：小幅长肌力，且安全
- 分类 `补剂` · 证据 `meta` · 精选 True（rank 80）· 2026-12-01
- 来源：J Int Soc Sports Nutr · 7 项 RCT 荟萃
- 链接：https://pubmed.ncbi.nlm.nih.gov/42141930/
- 摘要：7 项 RCT（约 600 名绝经后女性）荟萃：肌酸**在剂量足够、且配合抗阻训练**时，瘦体重和腿部力量有小但确实的提升；剂量不足又不训练则无效。骨密度无明显变化；肾功能等安全指标与安慰剂一致、无害迹象。（具体剂量见原文，按需问医生。）


### 跳跃类运动增骨密度，可能比举铁更管用
- 分类 `骨骼` · 证据 `meta` · 精选 True（rank 92）· 2026-05-29
- 来源：Miao 2025（Meta 分析）+ Tucker 2015（RCT）
- 链接：https://pubmed.ncbi.nlm.nih.gov/40611942/
- 摘要：论"练骨头"，跳跃/蹦跳类高冲击运动的增骨密度效果，Meta 分析显示可能比抗阻训练还好。绝经前女性每天只跳一二十下，几个月后髋部骨密度就明显提升。担心骨质疏松的，跳绳可能比你以为的更对路。（注：部分研究用的是"原地纵跳"，严格的"跳绳专项"证据还不算多。）


### 运动可能并不能"独立"预防肾结石
- 分类 `代谢` · 证据 `observational` · 精选 True（rank 88）· 2026-05-29
- 来源：Ferraro & Curhan 2015（大型队列）
- 链接：https://pubmed.ncbi.nlm.nih.gov/25229560/
- 摘要：一项合并二十多万人的研究，在扣掉体重、饮食后发现运动与结石"没有"独立关系——运动可能只是通过帮你控制体重间接沾边。真正防结石的硬道理朴素得很：多喝水、控体重、别久坐。靠跳绳预防结石形成，目前一篇直接证据都没有。


### 越练越难飙到高心率，是心脏变强不是退步
- 分类 `心肺` · 证据 `expert` · 精选 True（rank 85）· 2026-05-29
- 来源：Coote & White 2015（机制综述）
- 链接：https://pubmed.ncbi.nlm.nih.gov/25871550/
- 摘要：练久了爬同样的楼、心率却上不去，很多人以为退步——其实是"训练适应"：心脏每跳打出去的血更多，同样的活动不需要那么快的心跳。静息心率变慢、干同样活儿心率更低，恰恰是心肺变好的信号。（提醒：莫名心慌、胸闷、头晕是另一回事，该看医生。）


### 总觉得身体僵？几个在家能做的活动度自测
- 分类 `关节` · 证据 `expert` · 精选 True（rank 78）· 2026-05-29
- 来源：FoundMyFitness · Rhonda Patrick × Kelly Starrett
- 链接：https://www.youtube.com/watch?v=_i6vnLnwNC4
- 摘要：Kelly Starrett 给了几个在家能做的活动度自测：坐下-起立测试（sit-and-rise，有观察性研究与死亡率相关，但不是因果）、沙发拉伸测髋伸展、能不能舒服地坐地上。要点不是「达标」，而是把活动度当成可长期维持、不必随龄必然退化的能力。专家观点 + 实操，自测量力而行。


### 只跳绳、不改饮食，八周几乎不掉脂
- 分类 `运动` · 证据 `rct` · 精选 False（rank 0）· 2026-05-29
- 来源：Tang 2021（三臂 RCT）
- 链接：https://pubmed.ncbi.nlm.nih.gov/34579097/
- 摘要：把人分成"只控饮食 / 只跳绳 / 又控又跳"三组，八周后——光跳绳不改饮食那组，体脂、血脂、胰岛素几乎没动；只有配合少吃才真瘦。你瘦不瘦主要看吃多少，跳绳没有"特殊燃脂魔法"。


### 单摇跳绳对膝、髋的冲击，其实低于跑步
- 分类 `关节` · 证据 `observational` · 精选 False（rank 0）· 2026-05-29
- 来源：Mullerpatan 2021
- 链接：https://pubmed.ncbi.nlm.nih.gov/33992227/
- 摘要：跟"跳绳毁膝盖"的直觉相反：有研究实测，单脚轻弹式跳绳对膝、髋的冲击比跑步还低一些。前提是单摇、落地轻、姿势对；花式双摇、硬地猛跳就另说了。


### 悲伤的科学：它和抑郁不是一回事
- 分类 `心理` · 证据 `expert` · 精选 False（rank 0）· 2026-05-28
- 来源：Huberman Lab · Andrew Huberman
- 链接：https://www.hubermanlab.com/episode/essentials-the-science-and-process-of-healing-from-grief
- 摘要：Huberman 讲悲伤的神经科学：①大脑按「空间-时间-亲近度」给关系建图，失去某人需要重塑这套神经回路；②悲伤 ≠ 抑郁；③睡眠和皮质醇节律影响你能否适应性地度过；催产素解释了为何「思念」如此强烈。也提到书写情绪、规律光照等工具。专家科普。


### 被忽略的肌群与无伤训练
- 分类 `运动` · 证据 `expert` · 精选 False（rank 0）· 2026-05-25
- 来源：Huberman Lab · Jeff Cavaliere（物理治疗师）
- 链接：https://www.hubermanlab.com/episode/build-muscle-great-posture-and-resilience-to-injury-jeff-cavaliere
- 摘要：物理治疗师 Jeff Cavaliere 谈长期无痛训练的关键：①腰痛常和臀肌无力有关，可用走路类动作先激活、再强化臀肌；②用「老人测试」（从地上单脚起身）查功能性力量；③别只练大肌群——肩袖、颈、足这些「被忽略的」肌肉和结缔组织，决定你能不能一直练到七八十岁。偏实操方法论，专家经验。


### 降社交焦虑：和陌生人的小互动被低估了
- 分类 `心理` · 证据 `expert` · 精选 False（rank 0）· 2026-05-18
- 来源：Huberman Lab · Nick Epley 教授
- 链接：https://www.hubermanlab.com/episode/how-to-overcome-social-anxiety-nick-epley
- 摘要：社会连接研究者 Epley：①我们总高估「主动搭话会尴尬 / 被嫌弃」，数据显示这些悲观预期大多是错的；②哪怕和陌生人的小互动，也能实打实改善身心健康；③降社交焦虑的可行工具是「小步测试 + 修正预期」。专家观点 + 实操。


### 运动悖论：上班的体力活，可能不像休闲运动那样护心
- 分类 `运动` · 证据 `observational` · 精选 True（rank 84）· 2026-05-01
- 来源：Int J Behav Nutr Phys Act · 综述
- 链接：https://pubmed.ncbi.nlm.nih.gov/42104355/
- 摘要：「体力活动健康悖论」：休闲时的运动（跑步、健身）可靠地降低死亡与心血管风险；但**工作中的体力劳动**（搬运、长时间站走）关联却不一致、有时反而有害。可能机制：长时间无恢复的心血管负荷、动脉硬化、慢性炎症。证据仍偏弱，但提示「上班很累」≠「运动够了」。


### 任何年纪开始运动都不晚（对心血管）
- 分类 `运动` · 证据 `observational` · 精选 False（rank 0）· 2026-05-01
- 来源：Clinics in Geriatric Medicine · 综述
- 链接：https://pubmed.ncbi.nlm.nih.gov/42161438/
- 摘要：心肺功能随年龄下降会大幅抬高心血管病、衰弱、失能风险，久坐加速这一切。综述结论：规律运动能减缓与年龄相关的心肺功能下降、改善血管与代谢、降低发病与死亡——**即便上了年纪、身体适应变慢，仍有实打实的改善空间**。运动是心血管健康的基石。


### 关节活动度，可以不随年龄必然下降
- 分类 `关节` · 证据 `expert` · 精选 True（rank 86）· 2026-04-24
- 来源：FoundMyFitness 播客 #111 · Kelly Starrett
- 链接：https://foundmyfitness.libsyn.com/111-the-optimal-mobility-protocol-for-a-durable-body-dr-kelly-starrett
- 摘要：Kelly Starrett 的观点：活动度（ROM）是少数「不必随年龄必然下降」的生理维度，但长期不练几乎注定退化。本期讲怎么用日常动作模式维持身体耐用度。专家观点，重在方法论框架。


### 限时进食能降心梗患者的炎症？一个小型 RCT
- 分类 `营养` · 证据 `rct` · 精选 True（rank 82）· 2026-04-01
- 来源：J Am Heart Assoc · 随机交叉试验
- 链接：https://pubmed.ncbi.nlm.nih.gov/41859904/
- 摘要：19 名有心梗病史的患者，做 2 周限时进食（每天 8–14 点之间吃）后，中性粒细胞、低度系统性炎症指标下降，单核细胞转向抗炎。提示限时进食或能帮已有冠心病的人降风险——但**样本很小、只 2 周、看的是炎症指标而非「少发心梗」这种硬结局**，属早期信号，别当定论。


### 幸福不是追来的：几件可训练的事
- 分类 `心理` · 证据 `expert` · 精选 False（rank 0）· 2026-03-24
- 来源：FoundMyFitness 播客 #110 · Arthur Brooks
- 链接：https://foundmyfitness.libsyn.com/110-how-to-build-lasting-happiness-dr-arthur-brooks
- 摘要：社会科学家 Arthur Brooks 几个反直觉点：①幸福需要「享受 + 满足 + 意义」三者，光追快乐反而空；②高成就者常陷「奋斗者的诅咒」，满足感越来越短；③练感恩、列「反向愿望清单」、规律运动（他说运动对情绪的作用可比拟抗抑郁）都能调节。专家观点、方法论为主。


### NAD 与衰老：哪些干预真有人体数据
- 分类 `长寿` · 证据 `expert` · 精选 False（rank 0）· 2026-02-09
- 来源：FoundMyFitness 播客 #109 · Charles Brenner
- 链接：https://foundmyfitness.libsyn.com/109-how-to-boost-nad-levels-to-fight-inflammation-improve-recovery-and-slow-aging-dr-charles-brenner
- 摘要：不少「衰老症状」也符合慢性炎症 + NAD 代谢受损。Brenner（NAD 领域研究者）讲机制和人体数据，并对市面上一堆 NAD 补剂去伪存真。听点在于分清「机制说得通」和「真有人体证据」——具体补剂别照搬，回看原始研究。


### 种子油真有那么坏吗？一次把证据捋清
- 分类 `营养` · 证据 `expert` · 精选 True（rank 80）· 2026-01-21
- 来源：Peter Attia × Layne Norton 博士 · The Drive #380
- 链接：https://www.youtube.com/watch?v=7_cbaDXAWYM
- 摘要：围绕「种子油是否独有害」，两人把几个流行说法逐个查：①「己烷残留」——提取用的己烷在加工中被蒸汽蒸掉，要达到危害得一次吃上万公斤油，不现实；②真正的权衡是「饱和脂肪（猪油）减少氧化但升 LDL」对「多不饱和（种子油）反之」，缺人体试验定论；③比纠结用哪种油重要得多的，是总热量、纤维、活动量——「盯着炸薯条的油，错过了真正的疾病驱动」。专家梳理、结论是他们反复说的：别凭直觉，去读原始研究。


### 补肌酸会搞坏血脂吗？荟萃说：不会
- 分类 `补剂` · 证据 `meta` · 精选 False（rank 0）· 2026-01-01
- 来源：Frontiers in Nutrition · 8 项 RCT 荟萃
- 链接：https://pubmed.ncbi.nlm.nih.gov/42180567/
- 摘要：针对「补肌酸是否影响血脂」的担心，8 项随机对照试验的荟萃：肌酸对总胆固醇、LDL、HDL、甘油三酯**都没有临床意义上的影响**。也就是说，常见的「肌酸伤血脂」担忧，目前证据不支持。（不过证据确定性偏低，仍需更大样本确认。）


### 哪种运动对长寿最有用？
- 分类 `运动` · 证据 `expert` · 精选 True（rank 90）· 2025-12-07
- 来源：FoundMyFitness 播客 #108（Rhonda Patrick）
- 链接：https://foundmyfitness.libsyn.com/108-the-best-type-of-exercise-for-longevity
- 摘要：本期聊不同强度运动对寿命的影响，提到「1 分钟剧烈运动可能抵约 10 分钟中等强度」的说法。属专家梳理（非单一 RCT 定论），适合先听其论证、再回看背后的原始研究——我们站内也有相关研究条目可对照。


### 失眠：不靠药能怎么改善
- 分类 `睡眠` · 证据 `expert` · 精选 False（rank 0）· 2025-10-02
- 来源：FoundMyFitness 播客 #107 · Michael Grandner
- 链接：https://foundmyfitness.libsyn.com/107-how-to-cure-insomnia-without-pills-fall-asleep-dr-michael-grandner
- 摘要：慢性失眠和未治疗的睡眠呼吸暂停会明显伤认知与恢复力。Grandner 讲了几条有科学支持的非药物干预，重点是 CBT-I（失眠认知行为疗法）和刺激控制。属专家梳理；严重或长期睡眠问题仍需就医评估。


### 你的「衰老速度」其实能测
- 分类 `长寿` · 证据 `observational` · 精选 False（rank 0）· 2022-11-08
- 来源：Bryan Johnson · Medium
- 链接：https://medium.com/future-literacy/how-fast-are-you-aging-e845830d8a3c
- 摘要：有一类测试（如 DunedinPACE，基于多年纵向研究）能估你「每过 1 年、身体老了多少」。研究提示：衰老速度略高于 1，就和未来 7 年更高的死亡与慢病风险相关。作者用它追踪自己——但他「12 个月逆转 31 年」属个人自测、营销色彩重，**当概念看、别当目标**。


### 「每天八杯水」——你怎么知道这是对的？
- 分类 `营养` · 证据 `blogger` · 精选 False（rank 0）· 2022-10-07
- 来源：Bryan Johnson · Medium
- 链接：https://medium.com/future-literacy/how-much-water-should-i-drink-552be7d300e5
- 摘要：一个思维实验：朋友问「每天该喝几杯水」，多数人脱口「八杯」——但追问「你怎么知道」，会发现只是在重复听来的常识，没真见过证据。作者的点不在水，在于：分清「我真的知道」和「我只是听说」，是抵御伪健康信息的第一步。（这是观点 / 方法分享，非健康建议；饮水量因人而异。）
