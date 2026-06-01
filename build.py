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
HERO_SUB = "每条说法都标注证据强度、适用人群和来源状态——把「听来的」和「有据的」分开。"
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
REQUIRED = ["title", "source_url", "slug", "category", "evidence", "summary", "source", "date", "reviewed_at",
            "conclusion", "population", "caveats"]
EVIDENCE_OK = {"rct", "meta", "guideline", "observational", "expert", "blogger", "anecdote"}
CATEGORY_OK = {"运动", "关节", "心理", "营养", "补剂", "长寿", "骨骼", "代谢", "心肺", "睡眠", "其他"}
VERIFICATION_OK = {"verified", "curated_pending_evidence"}
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
    if not isinstance(u, str) or "\\" in u or re.search(r'[\x00-\x1f\x7f-\x9f\s]', u):
        return False  # 拒所有 C0/C1 控制字符 + 空白（含 DEL\x7f、NEL\x85，codex 边界探测）
    try:
        p = urllib.parse.urlsplit(u)
        p.port  # 触发非法端口校验
    except Exception:
        return False
    return (p.scheme in ("http", "https") and bool(p.hostname) and "." in p.hostname
            and p.username is None and p.password is None)


def _safe_href(u):
    """渲染层再确认 URL（纵深防御）：非合法 http(s) 一律降级为 #。
    闸门已挡 javascript:/data:，这里是第二道，即便数据绕过闸门也不会渲出伪协议链接。"""
    return u if _is_http_url(u) else "#"


_STUDY_HOSTS = ("pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "doi.org",
                "cochranelibrary.com", "www.cochranelibrary.com")
_GUIDELINE_HOSTS = ("who.int", "www.who.int", "uspreventiveservicestaskforce.org",
                    "www.uspreventiveservicestaskforce.org", "ods.od.nih.gov",
                    "nccih.nih.gov", "www.nccih.nih.gov", "cdc.gov", "www.cdc.gov",
                    "nhc.gov.cn", "www.nhc.gov.cn", "chinacdc.cn", "www.chinacdc.cn",
                    "en.chinacdc.cn")


def _is_study_url(u):
    """是否为可核验的研究 / 指南锚点：① 主机名在白名单（按真实 hostname，不用子串——子串会被
    'https://evil.com/?x=pubmed.ncbi.nlm.nih.gov' 骗过）② 且**路径指向具体条目**（非裸域名）——
    'https://doi.org/' / 'https://ncbi.nlm.nih.gov/' 这种没有文章 ID 的不算研究（codex 二次审出）。"""
    if not _is_http_url(u):
        return False
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or "").lower()
    path = p.path.strip("/")
    if host in _STUDY_HOSTS or host.endswith(".cochranelibrary.com"):
        return len(path) >= 2 and any(c.isdigit() for c in path)  # PMID/DOI/Cochrane 须指向具体条目
    if host in _GUIDELINE_HOSTS:
        return len(path) >= 2  # 官方指南 / factsheet 须指向具体页面，裸域名不算
    return False


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
        if it.get("category") not in CATEGORY_OK:
            errs.append(f"category 非法：{it.get('category')!r}")
        if it.get("verification_status") is not None and it.get("verification_status") not in VERIFICATION_OK:
            errs.append(f"verification_status 非法：{it.get('verification_status')!r}")
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
        elif isinstance(evl, list) and any(not _is_study_url(x) for x in evl):
            errs.append("evidence_source_urls 只能放研究 / 指南锚点；播客、视频等请放 discovery_source_url")
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


EVIDENCE_SCORE = {"rct": 7, "meta": 6, "guideline": 5, "observational": 4,
                  "expert": 3, "blogger": 2, "anecdote": 1}
EVIDENCE_ABOUT = {"rct": "随机对照试验", "meta": "荟萃 / 系统综述", "guideline": "权威机构指南",
                  "observational": "观察性研究", "expert": "专家观点梳理",
                  "blogger": "科普博主", "anecdote": "个案 / 轶事"}


def trust_badge(status):
    """维度 A：二元信任分层。待补是诚实的不确定，不渲染成错误或警告。"""
    if status == "verified":
        return '<span class="trust verified"><span class="seal">✓</span>已核验</span>'
    return '<span class="trust pending"><span class="seal"></span>专家梳理 · 证据待补</span>'


def strength_meter(evidence, show_label=True):
    """维度 B：七级证据强度。视觉使用中性石墨，服从于信任徽章。"""
    n = EVIDENCE_SCORE.get(evidence, 0)
    bars = "".join('<i class="on"></i>' if i <= n else '<i></i>' for i in range(1, 8))
    label = (f'<span class="lab">证据 <b>{e(EV_LABEL.get(evidence, evidence))}</b></span>'
             if show_label else "")
    return f'<span class="strength"><span class="bars">{bars}</span>{label}</span>'


def search_blob(it):
    return e(" ".join(str(it.get(k, "")) for k in
             ("title", "conclusion", "summary", "category", "population", "caveats")).replace("**", ""))


def legend_strip():
    chunks = []
    for ev in ("rct", "meta", "observational", "expert"):
        chunks.append(f'<span class="ls-item">{strength_meter(ev, False)}<span>{e(EV_LABEL[ev])}</span></span>')
        if ev != "expert":
            chunks.append('<span class="ls-sep"></span>')
    items = "".join(chunks)
    return (f'<div class="legend-strip"><span class="ls-title">证据强度（强→弱）</span>{items}'
            f'<span class="ls-item" style="margin-left:auto;color:var(--faint)">个例 →</span></div>')


def card(it):
    """首页核验卡：信任分层为主信号，证据强度为副信号。"""
    slug, cat = e(it.get("slug", "")), e(it.get("category", ""))
    status = verification_status(it)
    source_lead = "你可能在这听到" if status == "curated_pending_evidence" else "核验依据"
    feat = " feat" if it.get("featured") else ""
    star = '<span class="star">✦ 精选</span>' if it.get("featured") else ""
    return (f'<a class="card{feat}" href="claims/{slug}.html">\n'
            f'  <div class="card-top"><span class="cat">{cat}</span>{star}</div>\n'
            f'  <div class="signal">{trust_badge(status)}{strength_meter(it.get("evidence", ""))}</div>\n'
            f'  <h3>{e(it.get("title", ""))}</h3>\n'
            f'  <p class="verdict">{fmt(it.get("conclusion") or it.get("summary", ""))}</p>\n'
            f'  <div class="card-foot"><span class="src"><span class="lead">{source_lead}</span><br>'
            f'{e(it.get("source", ""))}</span><span class="go">→</span></div>\n'
            f'</a>')


def list_row(it):
    """全部页可扫读列表行：静态渲染，JS 只负责筛选和搜索。"""
    cat = e(it.get("category", ""))
    reviewed = e((it.get("reviewed_at") or it.get("date", ""))[5:])
    return (f'<a class="list-row" href="claims/{e(it.get("slug", ""))}.html" '
            f'data-cat="{cat}" data-search="{search_blob(it)}">\n'
            f'  <span class="lr-cat">{cat}</span>\n'
            f'  <span class="lr-sig">{trust_badge(verification_status(it))}'
            f'{strength_meter(it.get("evidence", ""), False)}</span>\n'
            f'  <span class="lr-claim"><span class="lc-t">{e(it.get("title", ""))}</span>'
            f'<span class="lc-v">{fmt(it.get("conclusion") or it.get("summary", ""))}</span></span>\n'
            f'  <span class="lr-date">{reviewed}</span>\n'
            f'</a>')


def footer(base="", narrow=False, detail=False):
    wrap = "wrap narrow" if narrow else "wrap"
    extra = " detail-foot" if detail else ""
    return f'''<footer class="foot{extra}"><div class="{wrap}">
  <div class="foot-in">
    <div>
      <div class="f-logo"><span class="x">✚</span>{e(SITE_TITLE)}</div>
      <p class="f-claim">把「听来的」和「有据的」分开。每条说法可追溯、可被机器调用。</p>
    </div>
    <div class="f-links">
      <div class="f-col"><h5>浏览</h5><a href="{base}index.html">精选</a><a href="{base}all.html">全部核验</a><a href="{base}about.html">关于方法论</a></div>
      <div class="f-col"><h5>AI 接入</h5><a href="{base}index.html#ai">claims.json</a><a href="{base}index.html#ai">安装 Skill</a></div>
    </div>
  </div>
  <div class="foot-bottom">本站为科普整理，<b>非医疗建议</b>；每条说法标注证据等级与来源状态，点击可回来源核对。 · {e(SITE_TITLE)} · 持续收集与查证</div>
</div></footer>'''


def shell(title, active, inner, base="", extra_js="", desc="", canon="", narrow_footer=False, detail=False):
    nav_items = [("精选", "index.html"), ("全部", "all.html"), ("关于", "about.html")]
    nav = "".join(
        f'<a class="{"on" if lbl == active else ""}" href="{base}{href}">{lbl}</a>'
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
<link rel="stylesheet" href="{base}claims.css">
</head>
<body class="vfy">
<nav class="nav"><div class="wrap nav-in">
  <a class="logo" href="{base}index.html"><span class="x">✚</span>{e(SITE_TITLE)}<small>· 健康说法核验库</small></a>
  <div class="nav-links">{nav}<a href="{base}index.html#ai" class="ai">🤖 AI 接入</a></div>
</div></nav>
<main>
{inner}
</main>
{footer(base, narrow_footer, detail)}
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
    ev = it.get("evidence", "")
    status = verification_status(it)
    pending = status == "curated_pending_evidence"
    fields = [f'<div class="field"><div class="fk"><span class="ico">◎</span> 证据强度说明</div>'
              f'<p>{e(EV_DESC.get(ev, ""))}</p></div>']
    if it.get("population"):
        fields.append(f'<div class="field"><div class="fk"><span class="ico">👥</span> 适用于谁</div>'
                      f'<p>{fmt(it["population"])}</p></div>')
    if it.get("caveats"):
        fields.append(f'<div class="field note"><div class="fk"><span class="ico">△</span> 需要注意</div>'
                      f'<p>{fmt(it["caveats"])}</p></div>')
    if it.get("summary"):
        fields.append(f'<div class="field"><div class="fk"><span class="ico">≡</span> 详情</div>'
                      f'<p>{fmt(it["summary"])}</p></div>')
    rel = ""
    if related:
        links = "".join(f'<a class="d-rel-item" href="{e(r.get("slug",""))}.html">'
                        f'<span class="rt">{e(r.get("title",""))}</span>'
                        f'<span class="rc">{e(r.get("category",""))}</span></a>' for r in related)
        rel = f'<div class="d-related"><h5>相关核验</h5>{links}</div>'
    src_date = it.get("source_published_at", "")
    collected = it.get("date", "")
    src_lbl = e(src_date) + ("（期刊预排，未到见刊日）" if src_date and src_date > TODAY else "")
    date_meta = ("原文日期 " + src_lbl + " · " if src_date
                 else ("本站收录 " + e(collected) + " · " if collected else ""))
    evs = [u for u in (it.get("evidence_source_urls") or []) if isinstance(u, str) and _is_study_url(u)]
    nonstudy = [u for u in (it.get("evidence_source_urls") or []) if isinstance(u, str) and not _is_study_url(u)]
    fallback_disc = it.get("source_url", "") if not _is_study_url(it.get("source_url", "")) else ""
    disc = it.get("discovery_source_url", "") or (nonstudy[0] if nonstudy else "") or fallback_disc
    dual = ""
    if disc:
        proof = (f'<a href="{e(_safe_href(evs[0]))}" target="_blank" rel="noopener">'
                 f'{e(_link_label(evs[0]))}</a>') if evs else "原始研究待补"
        proof_note = "evidence · 回答问题" if evs else "尚未补齐，不当定论"
        proof_class = "" if evs else " 待补"
        proof_style = "" if evs else ' style="color:var(--pd-ink)"'
        dual = (f'<div class="dlink"><div class="dlink-head">把「听来的」和「有据的」分开</div>'
                f'<div class="dlink-track"><div class="dnode heard">'
                f'<div class="dn-k">🎧 你可能在这听到</div>'
                f'<div class="dn-v"><a href="{e(_safe_href(disc))}" target="_blank" rel="noopener">'
                f'{e(it.get("source", "") or _link_label(disc))}</a><small>discovery · 提出问题</small></div></div>'
                f'<div class="dlink-mid"><span class="dots">····</span><span class="arrow">→</span></div>'
                f'<div class="dnode proof{proof_class}"><div class="dn-k">🔬 支撑它的研究</div>'
                f'<div class="dn-v"{proof_style}>{proof}<small>{proof_note}</small></div></div></div></div>')
    evidence_links = ""
    if evs:
        buttons = "".join(
            f'<a class="ev-link" href="{e(_safe_href(u))}" target="_blank" rel="noopener">'
            f'<span class="el-ic">🔬</span><span class="el-t">核验依据 · 点回原始来源'
            f'<small>{e(_link_label(u))}</small></span><span class="el-go">↗</span></a>' for u in evs)
        evidence_links = f'<div class="ev-links">{buttons}</div>'
    star = '<span class="star">✦ 精选</span>' if it.get("featured") else ""
    inner = (f'<div class="detail-page"><a class="d-back" href="../all.html">← 全部核验</a>'
             f'<div class="d-meta-top"><span class="cat">{e(it.get("category", ""))}</span>{star}</div>'
             f'<h1 class="d-title">{e(it.get("title", ""))}</h1>'
             f'<div class="d-verdict{" pend" if pending else ""}"><div class="vk">一句话结论</div>'
             f'<p>{fmt(it.get("conclusion") or it.get("summary", ""))}</p></div>'
             f'<div class="d-signal"><div class="row"><span class="k">信任分层</span>{trust_badge(status)}</div>'
             f'<div class="row"><span class="k">证据强度</span>{strength_meter(ev)}</div></div>'
             f'{dual}{"".join(fields)}{evidence_links}'
             f'<div class="src-line">来源：{e(it.get("source", ""))}<br>'
             f'{date_meta}'
             f'本站复核 {e(it.get("reviewed_at") or TODAY)}</div>{rel}'
             f'<div class="disclaim">本站为科普整理，<b>非医疗建议</b>；每条说法标注证据等级与来源状态，'
             f'点击可回来源核对。具体到个人，请咨询医生或专业人士。</div></div>')
    return shell(it.get("title", ""), "", inner + ld_json(it), base="../",
                 desc=(it.get("conclusion") or it.get("summary", "")),
                 canon="claims/" + it.get("slug", "") + ".html", detail=True)


def render_index(items):
    feats = sorted([it for it in items if it.get("featured")],
                   key=lambda x: x.get("rank", 0), reverse=True)
    cards = "\n".join(card(it) for it in feats) or '<p class="empty">还没有核验条目。</p>'
    hero = (f'<header class="hero"><div class="wrap"><span class="eyebrow">EVIDENCE-CHECKED · 循证核验</span>'
            f'<h1>听到一个健康说法？<br>先查一下证据。</h1>'
            f'<p class="lede">每条说法都标注<b>证据强度</b>、<b>适用人群</b>和<b>来源状态</b>'
            f'——把「听来的」和「有据的」分开。</p>'
            f'<form class="searchbox" action="all.html" method="get">'
            f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>'
            f'<input type="text" name="q" placeholder="比如：肌酸伤肾吗、种子油、限时进食…">'
            f'<button type="submit">查证据</button></form>{legend_strip()}</div></header>')
    featured = (f'<section class="sec"><div class="wrap"><div class="sec-head"><h2>重点核验</h2>'
                f'<a class="more" href="all.html">看全部 {len(items)} 条 →</a></div>'
                f'<div class="grid">{cards}</div></div></section>')
    agent = (f'<section class="sec" id="ai" style="padding-top:0"><div class="wrap"><div class="ai-band">'
             f'<div class="ab-l"><div class="robot">🤖 第二形态 · 被 AI 调用</div><h3>让 AI 助手直接查本站</h3>'
             f'<p>本站提供公开机读接口。你的 AI 助手可以区分「已核验」与「专家梳理·证据待补」，'
             f'回答健康问题时带上证据强度和对应来源链接。</p></div><div class="ab-r">'
             f'<div class="codeblk"><div class="ck">公开数据接口 · 任何人可匿名抓取</div>'
             f'<code>{e(SITE_URL)}claims.json</code></div>'
             f'<div class="codeblk"><div class="ck">安装 Skill（Claude Code）</div>'
             f'<code>mkdir -p ~/.claude/skills/health-hot &amp;&amp; curl -fsSL {e(SITE_URL)}skill/SKILL.md '
             f'-o ~/.claude/skills/health-hot/SKILL.md</code></div>'
             f'<div class="codeblk"><div class="ck">安装 Skill（Codex）</div>'
             f'<code>mkdir -p ~/.codex/skills/health-hot &amp;&amp; curl -fsSL {e(SITE_URL)}skill/SKILL.md '
             f'-o ~/.codex/skills/health-hot/SKILL.md</code></div></div></div></div></section>')
    return shell("精选", "精选", hero + featured + agent,
                 desc=HERO_SUB, canon="index.html")


def render_all(items):
    cats, by = [], {}
    for it in items:
        c = it.get("category", "其他")
        if c not in by:
            by[c] = []; cats.append(c)
        by[c].append(it)
    cats.sort(key=lambda c: -len(by[c]))
    pills = f'<button class="fchip on" data-c="all">全部<span class="ct">{len(items)}</span></button>' + "".join(
        f'<button class="fchip" data-c="{e(c)}">{e(c)}<span class="ct">{len(by[c])}</span></button>' for c in cats)
    rows = "\n".join(list_row(it) for it in items)
    inner = (f'<header class="hero all-hero"><div class="wrap"><span class="eyebrow">ALL CLAIMS · 全部核验</span>'
             f'<h1>全部核验</h1><p class="lede">一行一条，信任分层与证据强度在扫读时就能分辨。</p>'
             f'<form class="searchbox all-search" onsubmit="event.preventDefault();applyFilters()">'
             f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             f'stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>'
             f'<input type="text" id="q" placeholder="搜索说法、结论或关键词…" oninput="applyFilters()">'
             f'</form></div></header><section class="sec all-sec"><div class="wrap"><div class="controls">'
             f'<div class="filterbar" id="filterbar">{pills}</div><span class="count" id="count"></span></div>'
             f'<div class="listwrap"><div class="list-head"><span>主题</span><span>信任 / 强度</span>'
             f'<span>说法 · 结论</span><span>复核</span></div><div id="list">{rows}</div>'
             f'<div class="empty" id="empty" hidden>没有找到匹配的核验，换个关键词或主题试试。</div>'
             f'</div></div></section>')
    js = '''<script>
let activeCat='all'; const rows=[...document.querySelectorAll('.list-row')];
const input=document.getElementById('q'), count=document.getElementById('count'), empty=document.getElementById('empty');
const qp=new URLSearchParams(location.search).get('q'); if(qp) input.value=qp;
function applyFilters(){const query=(input.value||'').trim().toLowerCase();let n=0;rows.forEach(r=>{
  const show=(activeCat==='all'||r.dataset.cat===activeCat)&&(!query||r.dataset.search.toLowerCase().includes(query));
  r.style.display=show?'':'none';if(show)n++;});count.textContent=n+' 条 · 共 '+rows.length+' 条';empty.hidden=n!==0;}
document.getElementById('filterbar').addEventListener('click',e=>{const b=e.target.closest('.fchip');if(!b)return;
  activeCat=b.dataset.c;document.querySelectorAll('.fchip').forEach(x=>x.classList.toggle('on',x===b));applyFilters();});
applyFilters();
</script>'''
    return shell("全部", "全部", inner, extra_js=js,
                 desc="全部健康说法核验，按主题分组，每条标注证据强度、适用人群与原始出处。", canon="all.html")


def render_about():
    grades = "".join(
        f'<div class="src-role grade-role"><span>{strength_meter(ev, False)}</span>'
        f'<div class="role-d"><strong>{e(EV_LABEL[ev])}</strong><span>{e(EVIDENCE_ABOUT[ev])}</span></div>'
        f'<span class="lr-date">{EVIDENCE_SCORE[ev]}/7</span></div>'
        for ev in ("rct", "meta", "guideline", "observational", "expert", "blogger", "anecdote"))
    inner = f'''<header class="about-h"><div class="wrap narrow"><span class="eyebrow">METHODOLOGY · 方法论</span>
<h1>我们怎么把「听来的」<br>变成「有据的」</h1>
<p class="lede">这个库不生产观点，它核验说法。每一条结论怎么来、证据强弱怎么分、什么时候复核、发现错了怎么改——都写在这里。</p>
</div></header><section class="method"><div class="wrap narrow">
<div class="method-item"><div class="mi-n">01</div><div><h3>两层信任：先分「查实了没有」</h3>
<p>每条说法先归入两种状态之一。<b>已核验</b>：有独立的 PubMed / 官方指南 / Cochrane 研究支撑，可点回原始研究。<b>专家梳理·证据待补</b>：来自播客或专家的梳理，方向有参考价值，但原始研究链接还没补齐。我们老实标注「还没查到」，<b>这不是错误，是诚实</b>。</p></div></div>
<div class="method-item"><div class="mi-n">02</div><div><h3>证据分级：再标「支撑它的研究有多硬」</h3>
<p>对有研究支撑的条目，再按证据强度分七级。两个维度组合出可信度光谱：一条可以是「已核验 + Meta」，也可以是「专家梳理待补 + 专家」。</p>
<div class="src-table about-grade">{grades}</div></div></div>
<div class="method-item"><div class="mi-n">03</div><div><h3>双链接：你在哪听到 ≠ 凭什么相信</h3>
<p><b>发现来源（discovery）</b>是「你可能在某播客听到这个说法」，<b>核验依据（evidence）</b>是「支撑它的研究在哪里」。<b>播客负责提出问题，研究负责回答问题</b>。</p></div></div>
<div class="method-item"><div class="mi-n">04</div><div><h3>信源体系：三种角色，各司其职</h3><div class="src-table">
<div class="src-role"><span class="role-tag anchor">锚点 ANCHOR</span><div class="role-d"><strong>决定结论、做核验依据</strong><span>WHO / USPSTF / NIH 官方事实页与指南，PubMed 的 Cochrane 系统综述 / 指南 / 系统综述查询</span></div></div>
<div class="src-role"><span class="role-tag discovery">发现 DISCOVERY</span><div class="role-d"><strong>只负责发现「大家在讨论什么」，不下结论</strong><span>播客 / YouTube 等创作者入口默认不采集，需要时手动启用</span></div></div>
<div class="src-role"><span class="role-tag radar">雷达 RADAR</span><div class="role-d"><strong>追踪新论文与趋势</strong><span>PubMed 窄主题查询；趋势不能直接冒充结论</span></div></div>
</div></div></div>
<div class="method-item"><div class="mi-n">05</div><div><h3>复核与纠错</h3>
<p>每条都带<b>复核日期</b>，随研究更新而重新审视。发布前有自动闸门：缺来源、未来日期、伪链接、未审核的条目一律进不了线上。发现错误？欢迎通过 <a href="{REPO}/issues" target="_blank" rel="noopener"><b>GitHub issue</b></a> 指出。</p></div></div>
<div class="method-item"><div class="mi-n">06</div><div><h3>内容红线</h3>
<p>这是健康产品，有刚性约束：<b>不是医疗建议</b>，不开处方、不给具体剂量、不暗示治疗任何疾病；不确定的、证据弱的，明确标注，绝不替它下定论。</p></div></div>
</div></section>'''
    return shell("关于", "关于", inner,
                 desc="查过再信的方法论：怎么审核、证据如何分级、何时复核、如何纠错。",
                 canon="about.html", narrow_footer=True)


def claims_feed(items):
    """机读 feed：把已发布的核验导出成 JSON，供公开 Skill / Agent 直接调用（对标 AI HOT 的 public API）。
    只导出已过发布闸门的 good 条目；带站点级医疗免责（铁律④），让任何下游消费方都能带着它一起呈现。"""
    out = []
    for it in items:
        slug = it.get("slug", "")
        # source_urls 是兼容旧消费者的「全部来源」；新消费者必须用 evidence_source_urls /
        # discovery_source_url 分辨证据链与发现链，不能把 source_urls 当成原文研究列表。
        srcs = []
        for u in [it.get("source_url", "")] + [x for x in (it.get("evidence_source_urls") or []) if isinstance(x, str)]:
            if _is_http_url(u) and u not in srcs:
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
            "source_published_at": it.get("source_published_at", ""),
            "reviewed_at": it.get("reviewed_at", ""),
        })
    n_verified = sum(1 for c in out if c["verification_status"] == "verified")
    return {
        "schema_version": "1.2",  # 1.2: 信任分层 + evidence/discovery 分离 + 原始来源日期
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




def main():
    items, load_errors = load_items()
    good, blocked = validate(items)
    # 先全部写进临时目录，成功后再原子替换 docs/——渲染中途崩溃不会删掉已上线的站
    tmp = OUT + ".tmp"
    tmp_claims = os.path.join(tmp, "claims")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp_claims, exist_ok=True)
    open(os.path.join(tmp, ".nojekyll"), "w").close()
    css_src = os.path.join(ROOT, "claims.css")
    if not os.path.isfile(css_src):
        raise FileNotFoundError("缺少 claims.css：设计样式未加入仓库")
    shutil.copy(css_src, os.path.join(tmp, "claims.css"))
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
