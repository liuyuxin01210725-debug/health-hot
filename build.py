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
import json, glob, os, re, html, shutil, datetime, sys, urllib.parse

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

EV_LABEL = {"rct": "RCT", "meta": "Meta", "guideline": "指南", "observational": "观察",
            "expert": "专家", "blogger": "博主", "anecdote": "个例"}
EV_DESC = {
    "rct": "随机对照试验——证据强度高，但仍要看样本与重复性。",
    "meta": "系统综述 / 荟萃分析——综合多项研究，证据强度高。",
    "guideline": "官方 / 学会指南——基于证据的实践推荐，注意适用地区。",
    "observational": "观察性研究——能显示相关，不能证明因果。",
    "expert": "专家观点 / 科普——有参考价值，待更强证据确认。",
    "blogger": "个人观点 / 方案——非临床证据，仅供参考。",
    "anecdote": "个例 / 经验——证据级别最低，谨慎对待。",
}
REQUIRED = ["title", "source_url", "slug", "category", "evidence", "summary", "source", "date", "reviewed_at"]
EVIDENCE_OK = {"rct", "meta", "guideline", "observational", "expert", "blogger", "anecdote"}
SLUG_RE = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*\Z')  # 防路径穿越/注入；\Z 不放过结尾换行（$ 会）


def _isodate(s):
    try:
        return datetime.date.fromisoformat(s)
    except Exception:
        return None


def _norm_url(u):
    """归一化用于去重：去 fragment、host 小写、去末尾斜杠、剥掉 utm_*/fbclid/gclid 等跟踪参数——
    避免同一来源因 ?utm=… 或结尾 / 的差异被当成两条而漏过去重。"""
    if not isinstance(u, str):
        return ""
    u = re.sub(r'#.*$', '', u.strip())
    m = re.match(r'^(https?://)([^/?]+)([^?]*)(\?.*)?$', u)
    if not m:
        return u
    scheme, path, query = m.group(1), m.group(3), (m.group(4) or "")
    host = re.sub(r':(80|443)$', '', m.group(2).lower())  # host 小写 + 去默认端口
    path = re.sub(r'/+$', '', path)  # 去末尾斜杠
    if query:
        def _track(kv):  # 按「键名」判断跟踪参数（原写法要求 utm_ 紧贴 =，漏掉 utm_source=… ）
            key = kv.split('=', 1)[0].lower()
            return key.startswith('utm_') or key in ('fbclid', 'gclid', 'ref', 'source')
        keep = [kv for kv in query[1:].split('&') if kv and not _track(kv)]
        query = ('?' + '&'.join(sorted(keep))) if keep else ''
    return scheme + host + path + query


def _is_http_url(u):
    """合法 http(s) URL：scheme 为 http/https + 有真实主机名 + 主机含「.」+ 无控制字符。
    用 urlsplit 解析真 hostname，挡掉 'https://?q=x' / 'https://#x'（看似有内容实则无主机，codex 审出）
    与含 \\n/\\x00 的伪 URL。"""
    if not isinstance(u, str) or re.search(r'[\x00-\x1f\x7f-\x9f\s]', u):
        return False  # 拒所有 C0/C1 控制字符 + 空白（含 DEL\x7f、NEL\x85，codex 边界探测）
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname) and "." in p.hostname


def _safe_href(u):
    """渲染层再确认 URL（纵深防御）：非合法 http(s) 一律降级为 #。
    闸门已挡 javascript:/data:，这里是第二道，即便数据绕过闸门也不会渲出伪协议链接。"""
    return u if _is_http_url(u) else "#"


_STUDY_HOSTS = ("pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "doi.org",
                "cochranelibrary.com", "www.cochranelibrary.com")


def _is_study_url(u):
    """是否为真研究链接：① 主机名在研究站白名单（按真实 hostname，不用子串——子串会被
    'https://evil.com/?x=pubmed.ncbi.nlm.nih.gov' 骗过）② 且**路径指向具体条目**（非裸域名）——
    'https://doi.org/' / 'https://ncbi.nlm.nih.gov/' 这种没有文章 ID 的不算研究（codex 二次审出）。"""
    if not _is_http_url(u):
        return False
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or "").lower()
    if not (host in _STUDY_HOSTS or host.endswith(".cochranelibrary.com")):
        return False
    path = p.path.strip("/")
    return len(path) >= 2 and any(c.isdigit() for c in path)  # 须有具体条目（PMID/DOI 都含数字），裸域名不算


def _has_study(it):
    """是否有独立的研究/指南级证据链接（PubMed / DOI / Cochrane）——判定信任分层。"""
    pool = [it.get("source_url", "")] + [x for x in (it.get("evidence_source_urls") or []) if isinstance(x, str)]
    return any(_is_study_url(u) for u in pool if isinstance(u, str))


def verification_status(it):
    """信任分层（P0）：把『专家梳理』和『循证已核验』在数据层分开，不靠文字补丁。
      verified                  —— 有独立 PubMed/指南/Cochrane 支撑，可称『已核验』
      curated_pending_evidence  —— 专家/播客梳理，原文证据链待补，**不可**称『已核验』
    规则：『verified』必须有真研究 URL 兜底——**不允许**手动把无研究的条目标成 verified
    （codex 审出：显式字段曾可绕过研究要求）。只允许显式**降级**为 curated。"""
    if not _has_study(it):
        return "curated_pending_evidence"          # 无真研究 → 一律 curated，显式字段不能强升
    if it.get("verification_status") == "curated_pending_evidence":
        return "curated_pending_evidence"          # 有研究但人工选择降级（如对结论有疑），尊重
    return "verified"


VS_LABEL = {"verified": "已核验", "curated_pending_evidence": "专家梳理 · 证据链待补"}


def _link_label(u):
    """链接显示名：PubMed 显 PMID，其余显域名。"""
    m = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', u or "")
    if m:
        return f"PubMed {m.group(1)}"
    m = re.match(r'https?://([^/]+)', u or "")
    return m.group(1) if m else (u or "")


def load_items():
    items, errors = [], 0
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                it = json.load(fh)
        except Exception as ex:
            print(f"  ✗ JSON 解析失败 {os.path.basename(f)}: {ex}"); errors += 1
            continue
        if not isinstance(it, dict):  # 顶层必须是对象，否则下面 it['_file']= 会崩（codex 审出）
            print(f"  ✗ 顶层非对象，跳过 {os.path.basename(f)}"); errors += 1
            continue
        it["_file"] = os.path.basename(f)
        items.append(it)
    return items, errors


def validate(items):
    """发布闸门：返回 (合格条目, 被拦条目+原因)。坏数据在这里被拦，不靠人记得。"""
    good, blocked, seen_slug, seen_url = [], [], {}, {}
    today = _isodate(TODAY)
    for it in items:
        errs = []
        if not isinstance(it, dict):
            blocked.append((str(it)[:40], ["条目不是对象"])); continue
        # 必填 + 必须是非空字符串（防类型混淆崩溃）
        for k in REQUIRED:
            v = it.get(k)
            if not isinstance(v, str) or not v.strip():
                errs.append(f"缺/非字符串字段 {k}")
        # 可选富文本字段若存在必须是字符串，否则 fmt()/.replace() 在渲染/导出时崩（codex 审出）
        for k in ("conclusion", "population", "caveats"):
            if it.get(k) is not None and not isinstance(it.get(k), str):
                errs.append(f"{k} 非字符串")
        # 类型校验
        if not isinstance(it.get("featured", False), bool):
            errs.append("featured 非布尔")
        if not isinstance(it.get("rank", 0), int) or isinstance(it.get("rank", 0), bool):
            errs.append("rank 非整数")
        if it.get("evidence") not in EVIDENCE_OK:
            errs.append(f"evidence 非法：{it.get('evidence')!r}")
        # slug 白名单（防 ../ 路径穿越 与 属性注入）
        s = it.get("slug", "")
        if not (isinstance(s, str) and SLUG_RE.match(s)):
            errs.append(f"slug 非法（仅 a-z0-9-）：{s!r}")
        # source_url 必须 http(s)（防 javascript:/data: 伪协议）
        u = it.get("source_url", "")
        if not _is_http_url(u):
            errs.append(f"source_url 非合法 http(s)（须含主机、无控制符）：{u!r}")
        # status 严格 reviewed（缺失 / published 都不放行）
        if it.get("status") != "reviewed":
            errs.append(f"status 非 reviewed：{it.get('status')!r}")
        # 日期结构化解析：date/reviewed_at 必须 ISO 且不在未来；source_published_at 可未来但须可解析
        for k in ("date", "reviewed_at"):
            dv = it.get(k)
            d = _isodate(dv) if isinstance(dv, str) else None
            if dv and d is None:
                errs.append(f"{k} 非 ISO 日期：{dv!r}")
            elif d and today and d > today:
                errs.append(f"{k} 未来日期 {dv}")
        sp = it.get("source_published_at")
        if sp is not None and (not isinstance(sp, str) or _isodate(sp) is None):
            errs.append(f"source_published_at 非 ISO 日期：{sp!r}")
        # 双链接字段类型校验
        ds = it.get("discovery_source_url")
        if ds is not None and not isinstance(ds, str):
            errs.append("discovery_source_url 非字符串")
        elif isinstance(ds, str) and ds and not _is_http_url(ds):
            errs.append("discovery_source_url 非 http(s)")
        evl = it.get("evidence_source_urls")
        if evl is not None and (not isinstance(evl, list) or any(not _is_http_url(x) for x in evl)):
            errs.append("evidence_source_urls 须为 http(s) 列表")
        # 去重（slug 精确；url 归一化）
        nu = _norm_url(u)
        if isinstance(s, str) and s in seen_slug:
            errs.append(f"slug 重复（与 {seen_slug[s]}）")
        if nu and nu in seen_url:
            errs.append(f"来源链接重复（与 {seen_url[nu]}）")
        if errs:
            blocked.append((it.get("_file", "?"), errs))
        else:
            seen_slug[s] = it["_file"]
            seen_url[nu] = it["_file"]
            it.setdefault("featured", False)
            it.setdefault("rank", 0)
            good.append(it)
    good.sort(key=lambda x: (x.get("date", ""), x.get("rank", 0)), reverse=True)
    return good, blocked


def e(s):
    return html.escape(str(s if s is not None else ""))


def fmt(s):
    """富文本字段：先 HTML 转义（防注入），再把 **粗体** 转成 <strong>。
    用于 conclusion/summary/caveats/population —— 摘要时写的 Markdown 粗体不再裸露成 ** 星号。"""
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', e(s))


def ev_badge(it):
    ev = it.get("evidence", "")
    return f'<span class="ev ev-{e(ev)}">{EV_LABEL.get(ev, e(ev))}</span>' if ev else ""


def ev_legend():
    """证据强度图例：给不懂术语的访客一眼看懂徽章含义、以及强弱次序。"""
    order = ["rct", "meta", "guideline", "observational", "expert", "blogger", "anecdote"]
    short = {"rct": "随机对照", "meta": "荟萃", "guideline": "指南", "observational": "观察性",
             "expert": "专家观点", "blogger": "博主", "anecdote": "个例"}
    chips = "".join(f'<span class="lg-item"><span class="ev ev-{k}">{EV_LABEL[k]}</span>{short[k]}</span>'
                    for k in order)
    return f'<div class="ev-legend"><span class="lg-lead">证据强度（强 → 弱）</span>{chips}</div>'


def vs_badge(it):
    """信任分层徽章：verified=已核验（绿）/ curated=专家梳理待补（琥珀），让访客一眼分清。"""
    vs = verification_status(it)
    if vs == "verified":
        return '<span class="vs vs-ok" title="有独立研究/指南支撑">✓ 已核验</span>'
    return '<span class="vs vs-pend" title="专家或播客梳理，原文证据链待补">◔ 专家梳理·证据待补</span>'


def meta_row(it):
    return (f'<div class="meta"><span class="cat">{e(it.get("category",""))}</span>'
            f'{vs_badge(it)}{ev_badge(it)}<span class="src">{e(it.get("source",""))}</span>'
            f'<span class="date">复核 {e(it.get("reviewed_at") or it.get("date",""))}</span>'
            f'{("<span class=badge>✦ 精选</span>") if it.get("featured") else ""}</div>')


def card(it):
    """信息流卡：标题进**详情页**（不再直接跳外链），展示一句话结论。"""
    slug = e(it.get("slug", ""))
    cat = e(it.get("category", ""))
    blob = e(" ".join(str(it.get(k, "")) for k in
             ("title", "conclusion", "summary", "category", "population", "caveats")).replace("**", ""))
    concl = fmt(it.get("conclusion") or it.get("summary", ""))
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
<link rel="canonical" href="{e(SITE_URL + canon)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{e(title)} · {e(SITE_TITLE)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(SITE_URL + canon)}">
<meta property="og:image" content="{e(SITE_URL)}og.png">
<meta property="og:site_name" content="{e(SITE_TITLE)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)} · {e(SITE_TITLE)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(SITE_URL)}og.png">
<link rel="icon" href="{base}favicon.svg" type="image/svg+xml">
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


def ld_json(it):
    """详情页结构化数据（schema.org MedicalWebPage）：助力搜索引擎理解+富结果。
    用 MedicalWebPage 而非 ClaimReview——后者强制真/假评分，会把"证据分级+标注不确定"的结论
    压成非黑即白，违背 7 铁律。json.dumps 安全编码，并转义 </ 防 <script> 逃逸。"""
    slug = it.get("slug", "")
    data = {
        "@context": "https://schema.org",
        "@type": "MedicalWebPage",
        "name": it.get("title", ""),
        "url": SITE_URL + "claims/" + slug + ".html",
        "description": (it.get("conclusion") or it.get("summary") or "").replace("**", ""),
        "inLanguage": "zh-CN",
        # datePublished = 本站收录日（绝不未来）；不用 source_published_at（可能是期刊预排未来日，会让 JSON-LD 出现未来日期）
        "datePublished": it.get("date", ""),
        "dateModified": it.get("reviewed_at") or it.get("date", ""),
        "author": {"@type": "Organization", "name": SITE_TITLE, "url": SITE_URL},
        "publisher": {"@type": "Organization", "name": SITE_TITLE, "url": SITE_URL},
    }
    cites, seen = [], set()
    for u in [it.get("source_url", "")] + (it.get("evidence_source_urls") or []):
        if _is_study_url(u) and u not in seen:  # JSON-LD citation 只列真研究（与 feed/详情页同尺）
            seen.add(u); cites.append(u)
    if cites:
        data["citation"] = cites
    j = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{j}</script>'


def detail_page(it, related):
    slug = it.get("slug", "")
    url = e(_safe_href(it.get("source_url", "")))
    ev = it.get("evidence", "")
    fields = []
    fields.append(f'<dt>证据强度</dt><dd>{ev_badge(it)} {e(EV_DESC.get(ev,""))}</dd>')
    if it.get("population"):
        fields.append(f'<dt>适用于谁</dt><dd>{fmt(it["population"])}</dd>')
    if it.get("caveats"):
        fields.append(f'<dt>需要注意</dt><dd>{fmt(it["caveats"])}</dd>')
    if it.get("summary"):
        fields.append(f'<dt>详情</dt><dd>{fmt(it["summary"])}</dd>')
    # 信任分层横幅：专家梳理待补证据的条目，明确告诉访客「这不是已核验结论」
    banner = ""
    if verification_status(it) == "curated_pending_evidence":
        banner = ('<div class="pend-banner"><b>◔ 专家梳理 · 证据链待补</b>　'
                  '这条来自播客 / 研究者的梳理，<b>尚未链接到独立的原始研究</b>，'
                  '不等于「已核验」结论。请结合下方来源自行判断，我们会持续补上原文证据。</div>')
    rel = ""
    if related:
        links = "".join(f'<li><a href="{e(r.get("slug",""))}.html">{e(r.get("title",""))}</a>'
                        f'<span class="rcat">{e(r.get("category",""))}</span></li>' for r in related)
        rel = f'<section class="related"><h3>相关核验</h3><ul>{links}</ul></section>'
    src_date = it.get("source_published_at") or it.get("date", "")
    src_lbl = e(src_date) + ("（期刊预排，未到见刊日）" if src_date and src_date > TODAY else "")
    # 双链接：在哪听到（discovery） vs 凭什么核验（evidence）
    # 「核验依据」只放真研究 URL（与 feed 同一把尺 _is_study_url）——误放进 evidence 的播客 URL
    # 不会被当成研究展示，而是回落到「在哪听到」（codex 审出 HTML 与 feed 不一致）。
    evs = [u for u in (it.get("evidence_source_urls") or []) if isinstance(u, str) and _is_study_url(u)]
    nonstudy = [u for u in (it.get("evidence_source_urls") or []) if isinstance(u, str) and not _is_study_url(u)]
    disc = it.get("discovery_source_url", "") or (nonstudy[0] if nonstudy else "")
    dual = '<div class="dual">'
    if disc:
        dual += (f'<div class="dl-row"><span class="dl-k">🎧 你可能在哪听到</span>'
                 f'<a href="{e(_safe_href(disc))}" target="_blank" rel="noopener">{e(_link_label(disc))} ↗</a></div>')
    if evs:
        dual += ('<div class="dl-row"><span class="dl-k">🔬 核验依据</span><span class="dl-v">'
                 + " ".join(f'<a href="{e(_safe_href(u))}" target="_blank" rel="noopener">{e(_link_label(u))} ↗</a>' for u in evs)
                 + '</span></div>')
    else:
        dual += ('<div class="dl-row"><span class="dl-k">🔬 核验依据</span>'
                 '<span class="dl-pending">见原始来源中引用的研究（待单独标注）</span></div>')
    dual += '</div>'
    inner = (f'<nav class="crumb"><a href="../all.html">← 全部核验</a></nav>\n'
             f'<article class="claim">\n'
             f'  {meta_row(it)}\n'
             f'  <h1>{e(it.get("title",""))}</h1>\n'
             f'  {banner}\n'
             f'  <p class="claim-concl"><span class="lbl">一句话结论</span>{fmt(it.get("conclusion") or it.get("summary",""))}</p>\n'
             f'  <dl class="fields">{"".join(fields)}</dl>\n'
             f'  {dual}\n'
             f'  <a class="src-btn" href="{url}" target="_blank" rel="noopener">查看原始来源 ↗</a>\n'
             f'  <p class="prov">来源：{e(it.get("source",""))}'
             f'{(" · 原文日期 " + src_lbl) if src_date else ""}'
             f' · 本站复核 {e(it.get("reviewed_at") or TODAY)}</p>\n'
             f'</article>\n{rel}')
    return shell(it.get("title", ""), "", inner + ld_json(it), base="../",
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
    agent = (f'<section class="agent-cta">'
             f'<h2>🤖 让 AI 助手直接查本站</h2>'
             f'<p>本站提供公开机读接口，你的 AI 助手（Claude 等）可以直接查询已核验的健康说法，'
             f'回答时带上证据强度和原文链接。</p>'
             f'<div class="agent-grid">'
             f'<div class="agent-box"><h3>数据接口</h3>'
             f'<p>任何人可匿名抓取的 JSON feed：</p>'
             f'<code class="agent-url">{e(SITE_URL)}claims.json</code></div>'
             f'<div class="agent-box"><h3>一键安装 Skill</h3>'
             f'<p>装进 Claude，之后直接问「肌酸伤肾吗」：</p>'
             f'<code class="agent-url">mkdir -p ~/.claude/skills/health-hot &amp;&amp; curl -s {e(SITE_URL)}skill/SKILL.md -o ~/.claude/skills/health-hot/SKILL.md</code></div>'
             f'</div></section>')
    return shell("精选", "精选", hero + head + ev_legend() + '<section class="cards">' + cards + '</section>' + agent,
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
function q(){try{const m=location.search.match(/[?&]q=([^&]*)/);return m?decodeURIComponent(m[1].replace(/\\+/g,' ')).trim():'';}catch(e){return '';}}
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
    return shell("全部", "全部", head + ev_legend() + sections, extra_js=js,
                 desc="全部健康说法核验，按主题分组，每条标注证据强度、适用人群与原始出处。", canon="all.html")


def render_about():
    inner = f'''<section class="hero slim"><h1>关于本站</h1>
<p class="lead">「{e(SITE_TITLE)}」是一个<strong>健康说法核验库</strong>：把流行的健康说法，一条条查到原始证据、标出强度、写清适用人群和注意事项。资讯流只是入口，核心是帮你分清「听来的」和「有据的」。</p></section>
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


def claims_feed(items):
    """机读 feed：把已发布的核验导出成 JSON，供公开 Skill / Agent 直接调用（对标 AI HOT 的 public API）。
    只导出已过发布闸门的 good 条目；带站点级医疗免责（铁律④），让任何下游消费方都能带着它一起呈现。"""
    out = []
    for it in items:
        slug = it.get("slug", "")
        # source_urls = 主源在前 + 证据链，去重，仅 http(s)；至少含 1 条（主源已过闸门校验）。
        # discovery_source_url（"在哪听到"）不是证据，单列、不并入 source_urls。
        srcs = []
        for u in [it.get("source_url", "")] + [x for x in (it.get("evidence_source_urls") or []) if isinstance(x, str)]:
            if isinstance(u, str) and u and re.match(r'^https?://', u) and u not in srcs:
                srcs.append(u)
        vs = verification_status(it)
        # 证据链 = 只含真研究链接（按主机名判定，不用子串——见 _is_study_url）；发现链 = 播客/YT「在哪听到」，单列。
        evidence_urls = [u for u in srcs if _is_study_url(u)]
        out.append({
            "slug": slug,
            "title": it.get("title", ""),
            "detail_url": SITE_URL + "claims/" + slug + ".html",
            "category": it.get("category", ""),
            "verification_status": vs,                     # verified | curated_pending_evidence
            "verification_label": VS_LABEL[vs],
            "evidence": it.get("evidence", ""),
            "evidence_label": EV_LABEL.get(it.get("evidence", ""), it.get("evidence", "")),
            "conclusion": (it.get("conclusion") or it.get("summary") or "").replace("**", ""),
            "population": (it.get("population") or "").replace("**", ""),
            "caveats": (it.get("caveats") or "").replace("**", ""),
            "summary": (it.get("summary") or "").replace("**", ""),
            "source": it.get("source", ""),
            "evidence_source_urls": evidence_urls,         # 真研究链接（可能为空）
            "discovery_source_url": it.get("discovery_source_url", "")
                                    or (srcs[0] if srcs and not evidence_urls else ""),  # 没研究时把源当「发现链」
            "source_urls": srcs,                           # 兼容旧字段：全部来源
            "featured": bool(it.get("featured", False)),
            "date": it.get("date", ""),
            "reviewed_at": it.get("reviewed_at", ""),
        })
    n_verified = sum(1 for c in out if c["verification_status"] == "verified")
    return {
        "schema_version": "1.1",  # 1.1: 新增 verification_status 信任分层 + evidence/discovery 分离
        "site": SITE_TITLE,
        "site_url": SITE_URL,
        "description": "中文循证健康说法核验库——每条结论标注证据强度、适用人群与原始出处。",
        "disclaimer": "本数据为科普整理，非医疗建议；不提供具体剂量与个体化诊疗。"
                      "请点击 detail_url / evidence_source_urls 回原文核对。",
        "usage_note": "verification_status=verified 的条目有独立研究/指南支撑，可称『已核验』；"
                      "=curated_pending_evidence 的是专家/播客梳理、原文证据链待补，"
                      "**不可**冒充『已核验』，须标明『专家梳理·证据待补』。evidence_source_urls 为真研究链接，"
                      "discovery_source_url 是『在哪听到』（非证据）。",
        "generated_at": TODAY,
        "count": len(out),
        "verified_count": n_verified,
        "claims": out,
    }


CSS = '''
:root{
  --bg:#f6f9f7; --panel:#ffffff; --ink:#16302a; --muted:#5f726c; --line:#e3ece8;
  --accent:#0c7560; --accent-soft:#e6f4f0; --accent-ink:#0a5d4d;
  --rct:#146b3f; --meta:#0c7d73; --obs:#54605c; --exp:#34619f; --blog:#5f6863;
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
.ev-guideline{background:#5e45a4}
.ev-expert{background:var(--exp)}.ev-blogger,.ev-anecdote{background:var(--blog)}
.badge{margin-left:auto;background:#fff5e9;color:var(--warn);border:1px solid #f0d9bf;border-radius:7px;padding:2px 9px;font-size:11.5px;font-weight:800}
.ev-legend{display:flex;flex-wrap:wrap;align-items:center;gap:7px 13px;margin:0 0 16px;padding:10px 14px;background:var(--panel);border:1px solid var(--line);border-radius:12px;font-size:12.5px;color:var(--muted)}
.ev-legend .lg-lead{font-weight:700;color:var(--accent-ink)}
.ev-legend .lg-item{display:inline-flex;align-items:center;gap:5px}
.vs{border-radius:7px;padding:2px 8px;font-size:11.5px;font-weight:700}
.vs-ok{background:var(--accent-soft);color:var(--accent-ink)}
.vs-pend{background:#fff5e9;color:#9a5a1f;border:1px solid #f0d9bf}
.pend-banner{background:#fff5e9;border:1px solid #f0d9bf;color:#7a4a18;border-radius:12px;padding:12px 16px;margin:0 0 16px;font-size:14px}
.pend-banner b{color:#9a5a1f}
.agent-cta{margin:32px 0 0;padding:22px 24px;background:var(--accent-soft);border:1px solid #cfe3db;border-radius:16px}
.agent-cta h2{margin:0 0 6px;font-size:19px;color:var(--accent-ink)}
.agent-cta>p{margin:0 0 16px;color:var(--muted);font-size:14px}
.agent-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.agent-box{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.agent-box h3{margin:0 0 4px;font-size:15px;color:var(--ink)}
.agent-box p{margin:0 0 8px;color:var(--muted);font-size:13px}
.agent-url{display:block;background:#0f201c;color:#7fe3c4;border-radius:8px;padding:10px 12px;font-size:12px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;word-break:break-all;line-height:1.5}
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
.dual{margin:0 0 16px;display:flex;flex-direction:column;gap:8px}
.dl-row{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px;font-size:14px}
.dl-k{flex:0 0 auto;font-weight:700;color:var(--accent-ink);background:var(--accent-soft);border-radius:7px;padding:2px 9px;font-size:12.5px}
.dl-v{display:flex;flex-wrap:wrap;gap:10px}
.dl-pending{color:var(--muted)}
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
    items, load_errors = load_items()
    good, blocked = validate(items)
    # 先全部写进临时目录，成功后再原子替换 docs/——渲染中途崩溃不会删掉已上线的站
    tmp = OUT + ".tmp"
    tmp_claims = os.path.join(tmp, "claims")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp_claims, exist_ok=True)
    open(os.path.join(tmp, ".nojekyll"), "w").close()
    with open(os.path.join(tmp, "styles.css"), "w", encoding="utf-8") as f:
        f.write(CSS)
    with open(os.path.join(tmp, "index.html"), "w", encoding="utf-8") as f:
        f.write(render_index(good))
    with open(os.path.join(tmp, "all.html"), "w", encoding="utf-8") as f:
        f.write(render_all(good))
    with open(os.path.join(tmp, "about.html"), "w", encoding="utf-8") as f:
        f.write(render_about())
    with open(os.path.join(tmp, "claims.json"), "w", encoding="utf-8") as f:
        json.dump(claims_feed(good), f, ensure_ascii=False, indent=2)
    # 公开 Skill 源随站点发布：skill/ → docs/skill/（放在 tmp 里走原子替换，重建不丢）
    skill_src = os.path.join(ROOT, "skill")
    if os.path.isdir(skill_src):
        shutil.copytree(skill_src, os.path.join(tmp, "skill"))
    # favicon（SVG：品牌绿底 + 白十字）+ sitemap.xml + robots.txt —— SEO 基础设施
    with open(os.path.join(tmp, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                '<rect width="32" height="32" rx="8" fill="#0c7560"/>'
                '<rect x="14" y="7" width="4" height="18" rx="1.5" fill="#fff"/>'
                '<rect x="7" y="14" width="18" height="4" rx="1.5" fill="#fff"/></svg>')
    # sitemap：详情页用各自的复核日做 lastmod（不再全部盖今天，避免每次构建都谎称「全站今天更新」，codex 审出）
    newest = max((it.get("reviewed_at") or it.get("date") or TODAY) for it in good) if good else TODAY
    pages = [("index.html", newest), ("all.html", newest), ("about.html", newest)]
    pages += [("claims/" + it["slug"] + ".html", it.get("reviewed_at") or it.get("date") or TODAY) for it in good]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>',
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p, lm in pages:
        sm.append(f"  <url><loc>{SITE_URL}{p}</loc><lastmod>{lm}</lastmod></url>")
    sm.append("</urlset>")
    with open(os.path.join(tmp, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(sm) + "\n")
    with open(os.path.join(tmp, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n")
    # og:image 社交分享卡（由 make_og.py 预生成，构建只拷贝——保持零依赖）
    og_src = os.path.join(ROOT, "assets", "og.png")
    if os.path.isfile(og_src):
        shutil.copy(og_src, os.path.join(tmp, "og.png"))
    for it in good:
        related = [r for r in good if r.get("category") == it.get("category")
                   and r.get("slug") != it.get("slug")][:4]
        # slug 已过白名单校验；再确认输出路径不逃出 claims/
        dest = os.path.join(tmp_claims, it["slug"] + ".html")
        if os.path.abspath(dest).startswith(os.path.abspath(tmp_claims) + os.sep):
            with open(dest, "w", encoding="utf-8") as f:
                f.write(detail_page(it, related))
    feat = sum(1 for it in good if it.get("featured"))
    # 发布闸门（fail-safe）：有拦截/读取失败时，**先不替换 docs/**，保留已上线旧站，只报告。
    # 此前是「先 rename 再 exit 1」=假闸门：坏数据已经覆盖了旧站才报错（codex 审出）。
    if (blocked or load_errors) and "--force" not in sys.argv:
        shutil.rmtree(tmp, ignore_errors=True)  # 丢弃临时产物，docs/ 原封不动
        print(f"⛔ 发布闸门：拦下 {len(blocked)} 条 + 读取失败 {load_errors} 个——docs/ **未改动**，旧站保留。")
        for fn, errs in blocked:
            print(f"   ✗ {fn}: {'; '.join(errs)}")
        print("   修好后重跑；确需用合格内容强制重建请加 --force。")
        sys.exit(1)
    # 接近原子的替换：旧站挪到 .old → 新站就位 → 删旧站。两次 rename 之间的窗口若失败，
    # except 把 .old 挪回 OUT，保证 docs/ 不会消失（codex 审出无 rollback）。
    old = OUT + ".old"
    shutil.rmtree(old, ignore_errors=True)
    moved = False
    if os.path.exists(OUT):
        os.rename(OUT, old); moved = True
    try:
        os.rename(tmp, OUT)
    except Exception:
        if moved and not os.path.exists(OUT):  # 第二步失败 → 回滚：把旧站挪回来
            os.rename(old, OUT)
        raise
    shutil.rmtree(old, ignore_errors=True)
    print(f"✓ 发布 {len(good)} 条（精选 {feat}）+ {len(good)} 个详情页 + claims.json（机读 feed）→ docs/")
    if blocked:  # 仅 --force 时会走到这
        print(f"\n⚠️  --force 强制发布，已忽略 {len(blocked)} 条被拦条目：")
        for fn, errs in blocked:
            print(f"   ✗ {fn}: {'; '.join(errs)}")
    else:
        print("✓ 发布闸门：全部通过，无未来日期/缺来源/未审核条目")


if __name__ == "__main__":
    main()
