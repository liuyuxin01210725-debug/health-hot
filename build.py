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
