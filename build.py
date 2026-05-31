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
HERO_Q = "听到一个健康说法？先查一下证据。"
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


def shell(title, active, inner, base="", extra_js=""):
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
    inner = (f'<nav class="crumb"><a href="../all.html">← 全部核验</a></nav>\n'
             f'<article class="claim">\n'
             f'  {meta_row(it)}\n'
             f'  <h1>{e(it.get("title",""))}</h1>\n'
             f'  <p class="claim-concl"><span class="lbl">一句话结论</span>{e(it.get("conclusion") or it.get("summary",""))}</p>\n'
             f'  <dl class="fields">{"".join(fields)}</dl>\n'
             f'  <a class="src-btn" href="{url}" target="_blank" rel="noopener">查看原始来源 ↗</a>\n'
             f'  <p class="prov">来源：{e(it.get("source",""))}'
             f'{(" · 原文日期 " + e(src_date)) if src_date else ""}'
             f' · 本站复核 {e(it.get("reviewed_at") or TODAY)}</p>\n'
             f'</article>\n{rel}')
    return shell(it.get("title", ""), "", inner, base="../")


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
    return shell("精选", "精选", hero + head + '<section class="cards">' + cards + '</section>')


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
    return shell("全部", "全部", head + sections, extra_js=js)


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
