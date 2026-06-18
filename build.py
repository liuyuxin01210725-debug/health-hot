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
import json, glob, os, re, html, shutil, datetime, sys, urllib.parse, hashlib

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data", "items")
OUT = os.path.join(ROOT, "docs")
CLAIMS = os.path.join(OUT, "claims")
# 强审硬锁的两个账本（部署闸门第二段会读，详见 strong_review_gate）：
AUDIT_PATH = os.path.join(ROOT, "data", "review_audit.json")            # /health-review 强审记录
GRANDFATHER_PATH = os.path.join(ROOT, "data", "strong_review_grandfather.json")  # 历史条目固化清单
TODAY = datetime.date.today().isoformat()

SITE_TITLE = "查过再信"
SITE_URL = os.environ.get("HEALTH_HOT_SITE_URL", "https://health-hot.vercel.app/").rstrip("/") + "/"
# Cloudflare Web Analytics（可选）：设了 HEALTH_HOT_CF_ANALYTICS_TOKEN 才在每页注入 beacon；
# 没设则一字不出——不写死 token、不影响本地构建产物。
# Cloudflare Web Analytics 只看页面访问/来源/热门 URL，不记 query string、无自定义事件。
CF_ANALYTICS_TOKEN = os.environ.get("HEALTH_HOT_CF_ANALYTICS_TOKEN", "").strip()
HERO_Q = "听到一个健康说法？先查一下证据。"
DEFAULT_SUBMIT_ENDPOINT = "https://health-hot-submit.pages.dev/submit"
SUBMIT_ENDPOINT = os.environ.get("HEALTH_HOT_SUBMIT_ENDPOINT", DEFAULT_SUBMIT_ENDPOINT).strip()
# 站内搜索打点端点（精选"热点度"的需求信号）：前端在搜索停手后 fire-and-forget 发 {term,hit}。
DEFAULT_EVENT_ENDPOINT = "https://health-hot-submit.pages.dev/event"
EVENT_ENDPOINT = os.environ.get("HEALTH_HOT_EVENT_ENDPOINT", DEFAULT_EVENT_ENDPOINT).strip()

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
                    "en.chinacdc.cn",
                    # 独立交叉源（非美官方循证机构，与 collect.py OFFICIAL_HOSTS 对齐）
                    "nhs.uk", "www.nhs.uk",
                    "ec.europa.eu", "food.ec.europa.eu",
                    "efsa.europa.eu", "www.efsa.europa.eu")


def _is_research_url(u):
    """是否为可回溯的研究锚点：主机在白名单，且路径指向具体文章。"""
    if not _is_http_url(u):
        return False
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or "").lower()
    path = p.path.strip("/")
    if host in _STUDY_HOSTS or host.endswith(".cochranelibrary.com"):
        return len(path) >= 2 and any(c.isdigit() for c in path)  # PMID/DOI/Cochrane 须指向具体条目
    return False


def _is_official_url(u):
    """是否为可回溯的官方依据：白名单机构域名下的具体页面，裸域名不算。"""
    if not _is_http_url(u):
        return False
    p = urllib.parse.urlsplit(u)
    host = (p.hostname or "").lower()
    path = p.path.strip("/")
    if host in _GUIDELINE_HOSTS:
        return len(path) >= 2  # 官方指南 / factsheet 须指向具体页面，裸域名不算
    return False


def _is_evidence_url(u):
    """是否为可作为核验依据的链接：研究锚点或白名单官方页面。"""
    return _is_research_url(u) or _is_official_url(u)


def _evidence_pool(it):
    """收集条目的核验依据候选，兼容旧数据中把主链接直接作为依据的写法。"""
    pool = [it.get("source_url", "")] + [x for x in (it.get("evidence_source_urls") or []) if isinstance(x, str)]
    return [u for u in pool if isinstance(u, str)]


def verification_status(it):
    """兼容旧消费者的二元状态。新消费者应优先使用 verification_basis。"""
    if not any(_is_evidence_url(u) for u in _evidence_pool(it)):
        return "curated_pending_evidence"          # 无核验依据 → 一律 curated，显式字段不能强升
    if it.get("verification_status") == "curated_pending_evidence":
        return "curated_pending_evidence"          # 有依据但人工选择降级（如对结论有疑），尊重
    return "verified"


VS_LABEL = {"verified": "已核验", "curated_pending_evidence": "专家梳理 · 证据链待补"}
VB_LABEL = {"study_supported": "研究支持", "official_basis": "官方依据", "frontier_pending": "前沿待核"}


def verification_basis(it):
    """面向用户的三类依据状态：研究支持 / 官方依据 / 前沿待核。

    研究锚点优先于官方页面；人工降级始终优先，避免有链接就自动抬高可信度。
    """
    if verification_status(it) == "curated_pending_evidence":
        return "frontier_pending"
    pool = _evidence_pool(it)
    if any(_is_research_url(u) for u in pool):
        return "study_supported"
    if any(_is_official_url(u) for u in pool):
        return "official_basis"
    return "frontier_pending"


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
        # content_sha = 原始文件字节的 sha256，与 scripts/prepush_check.py 的 sha() 算法一致。
        # 强审硬锁与 grandfather 固化都按它判断「正文是否变过」——改一个字节哈希就变。
        with open(f, "rb") as fb:
            it["_content_sha"] = hashlib.sha256(fb.read()).hexdigest()
        items.append(it)
    return items, errors


def load_strong_review_state():
    """读强审硬锁的两个账本，返回 (audit, grandfather)。

    - review_audit.json：{slug: {verdict, content_sha, ...}}，/health-review 强审记录。
    - strong_review_grandfather.json：{slug: content_sha}，固化引入硬锁之前已上线的历史条目，
      使硬锁上线当天不冻结全站；条目正文一改 → sha 变 → 脱离 grandfather → 必须重过强审。

    任一文件缺失/损坏都按「空」处理（fail closed）：依赖它放行的条目会被强审闸门拦下，
    而不是被静默放行——宁可冻结也不让未审内容混上线。"""
    def _load(path, label):
        if not os.path.exists(path):
            return {}
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except Exception as ex:
            print(f"  ⚠ {label} 无法解析（按空处理，相关条目将被强审闸门拦下）：{ex}")
            return {}
    return _load(AUDIT_PATH, "review_audit.json"), _load(GRANDFATHER_PATH, "strong_review_grandfather.json")


def strong_review_status(it, audit, grandfather):
    """单条强审覆盖判定：返回 None=放行，否则返回拦截原因。

    优先级——【audit 记录一旦存在即权威】，grandfather 只对「无 audit 记录」的条目兜底：
      1. 有 audit 记录：
         · verdict != PASS            → 拦（FIX/BLOCK 必须压过 grandfather，否则否决形同虚设）
         · PASS 但 content_sha 不匹配   → 拦（强审后正文已改）
         · PASS 且 content_sha 匹配     → 放行
      2. 无 audit 记录：
         · grandfather sha 匹配         → 放行（历史存量兜底）
         · grandfather 有 slug 但 sha 不符 → 拦（固化后正文已改）
         · 两边都没有                   → 拦（新增未审）"""
    slug = it.get("slug", "")
    cur = it.get("_content_sha", "")
    rec = audit.get(slug) if isinstance(audit, dict) else None
    if rec:  # audit 权威：先于 grandfather 判定，FIX/BLOCK 不可被固化清单洗白
        if rec.get("verdict") != "PASS":
            return f"强审判定={rec.get('verdict')!r}（非 PASS），需过 /health-review"
        if rec.get("content_sha") != cur:
            return "强审后正文已变更（哈希不符），需重过 /health-review"
        return None
    if cur and grandfather.get(slug) == cur:
        return None
    if slug in grandfather:
        return "固化后正文已变更（哈希不符），需重过 /health-review"
    return "未过强审（新增条目，无 PASS 记录、不在固化清单），需过 /health-review"


def strong_review_gate(items, audit, grandfather):
    """部署闸门第二段——强审硬锁。对【已过数据闸门】的条目逐条判定，
    返回 [(file, [原因]), ...]，由 main() 并入 blocked，走同一个 fail-safe（不替换 docs/、退码 1）。

    与 scripts/prepush_check.py 的区别：那个是本机/CI 的「增量」锁（只看改动条目，且不认 grandfather）；
    这个是 Vercel 构建时的「全库」锁——线上站真正的强审硬锁就在这里。"""
    failures = []
    for it in items:
        why = strong_review_status(it, audit, grandfather)
        if why:
            failures.append((it.get("_file", "?"), [why]))
    return failures


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
        elif isinstance(evl, list) and any(not _is_evidence_url(x) for x in evl):
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


# ── 精选 / 重点核验：算分自动选取（替代手动 featured bool，避免冻住）──────────────
# 重点核验分 = 0.45·证据强度 + 0.20·编辑重要性(rank) + 0.20·新鲜度 + 0.15·热点度。
# 硬门槛：只从"已核验层"(study_supported / official_basis)选，前沿待核(frontier_pending)不进门面。
# 热点度来自 data/search_hotness.json(站内搜索计数，/event 收集)；无该文件时记 0、其余三项照常驱动，
# 所以即便还没搜索数据，精选也已"算分自动刷新"、不再冻在最初那批。
FEATURED_N = 24
FEATURED_PER_CAT_CAP = 6


def _score_ref_date(items):
    """精选打分的时间锚点：全库 max(reviewed_at|date)，与 generated_at 同源(见 main)。
    用它替代 date.today() 做新鲜度衰减基准 → 精选选取(及写进 claims.json 的 featured 位)
    成为 committed 数据的纯函数、跨天 byte 可复现；否则同样内容换了一天就会换入/换出条目，
    令 CI 的 docs/claims.json byte 校验假红(codex 审出)。"""
    best = max(((it.get("reviewed_at") or it.get("date") or "")[:10] for it in items), default="")
    try:
        return datetime.date.fromisoformat(best)
    except ValueError:
        return datetime.date.fromisoformat(TODAY)


def _freshness(it, ref_date):
    """新鲜度 0~1：按本站复核日(reviewed_at，缺则 date)相对 ref_date 做时间衰减(~60 天量级)。
    ref_date 是构建锚点(全库 max 复核日，见 _score_ref_date)而非 today()，使精选跨天确定。"""
    ds = (it.get("reviewed_at") or it.get("date") or "")[:10]
    try:
        days = (ref_date - datetime.date.fromisoformat(ds)).days
    except ValueError:
        return 0.0
    return 1.0 / (1.0 + max(days, 0) / 60.0)


def _safe_int(v):
    """容错取整：data/search_hotness.json 来自外部 /event 端点、未过 validate()，
    h/m 若被写成非数字不该崩掉整个构建(codex 审出)——非法值记 0。"""
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def _hotness_norm(items):
    """站内搜索词计数(data/search_hotness.json，/event 收集)→ 每条目热点度 0~1(按 slug)。
    匹配：规范化搜索词是条目(标题/结论/摘要/别名)子串则计入该词总次数，再按全站最大值归一。
    无搜索数据(端点刚上线，常见)→ 返回空 → 热点度全 0。matcher 待真实数据到位后校准。"""
    p = os.path.join(ROOT, "data", "search_hotness.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            terms = (json.load(fh) or {}).get("terms", [])
    except (ValueError, OSError):
        return {}
    norm = lambda s: re.sub(r"[，。！？,.!?、\s]+", "", str(s or "").lower())
    raw = {}
    for it in items:
        text = norm(search_blob(it))
        total = sum(_safe_int(t.get("h", 0)) + _safe_int(t.get("m", 0)) for t in terms
                    if len(norm(t.get("term", ""))) >= 2 and norm(t.get("term", "")) in text)
        if total:
            raw[it.get("slug", "")] = total
    mx = max(raw.values()) if raw else 0
    return {k: v / mx for k, v in raw.items()} if mx else {}


def featured_score(it, hot_norm, ref_date):
    ev = EVIDENCE_SCORE.get(it.get("evidence", ""), 0) / 7.0
    rank = min(max(int(it.get("rank", 0) or 0), 0), 100) / 100.0
    return 0.45 * ev + 0.20 * rank + 0.20 * _freshness(it, ref_date) + 0.15 * hot_norm.get(it.get("slug", ""), 0.0)


def select_featured(items, n=FEATURED_N, per_cat_cap=FEATURED_PER_CAT_CAP):
    """重点核验分 top-N + 类目均衡。只取已核验层；前沿待核不进精选。
    打分时间锚点固定为全库 max 复核日(见 _score_ref_date)，使选取跨天确定、不随 today() 漂。"""
    hot = _hotness_norm(items)
    ref = _score_ref_date(items)
    scored = sorted((it for it in items if verification_basis(it) != "frontier_pending"),
                    key=lambda it: featured_score(it, hot, ref), reverse=True)
    out, per_cat = [], {}
    for it in scored:
        c = it.get("category", "其他")
        if per_cat.get(c, 0) >= per_cat_cap:
            continue
        out.append(it)
        per_cat[c] = per_cat.get(c, 0) + 1
        if len(out) >= n:
            break
    if len(out) < n:  # 类目上限没填满 → 放宽补齐
        have = {id(x) for x in out}
        for it in scored:
            if id(it) not in have:
                out.append(it)
                if len(out) >= n:
                    break
    return out


def _mark_featured(items):
    """按算分在内存里标 featured（不改数据文件）；首页精选块、列表 ✦精选 星标、claims.json 统一用它。"""
    chosen = {it.get("slug") for it in select_featured(items)}
    for it in items:
        it["featured"] = it.get("slug") in chosen


def trust_badge(basis):
    """维度 A：普通用户可理解的三类依据。待核是诚实的不确定，不渲染成错误。"""
    if basis == "study_supported":
        return '<span class="trust verified"><span class="seal">✓</span>研究支持</span>'
    if basis == "official_basis":
        return '<span class="trust official"><span class="seal">◎</span>官方依据</span>'
    return '<span class="trust pending"><span class="seal"></span>前沿待核</span>'


def strength_meter(evidence, show_label=True):
    """维度 B：七级证据强度。视觉使用中性石墨，服从于依据状态徽章。"""
    n = EVIDENCE_SCORE.get(evidence, 0)
    bars = "".join('<i class="on"></i>' if i <= n else '<i></i>' for i in range(1, 8))
    label = (f'<span class="lab">证据 <b>{e(EV_LABEL.get(evidence, evidence))}</b></span>'
             if show_label else "")
    return f'<span class="strength"><span class="bars">{bars}</span>{label}</span>'


def evidence_hint(it):
    """证据提示：用两个现有维度（依据状态 + 证据强度）合成一句「该怎么信这条」。
    纯派生、不新增数据字段——区别于 caveats（条目专属注意）与 EV_DESC（只讲强度）：
    它把「有没有可追溯依据」和「证据多强」合成一句可直接转述的信任解读，主要服务
    被 AI 调用的第二形态——下游助手拿到 feed 就有现成的、不夸大的解读层。"""
    basis = verification_basis(it)
    ev = it.get("evidence", "")
    if basis == "study_supported":
        head = "有可追溯的原始研究支撑"
    elif basis == "official_basis":
        head = "有官方 / 机构页面支撑，但本站未追溯到原始研究"
    else:
        head = "暂无可追溯的研究或官方依据，属前沿待核"
    if ev in ("rct", "meta"):
        tail = "证据强度较高，可作较可靠参考；仍要看样本量与是否被重复"
    elif ev == "guideline":
        tail = "属实践推荐级别，注意适用地区与更新时间"
    elif ev == "observational":
        tail = "只能显示相关、不能证明因果，勿据此改变重大决定"
    elif ev in ("expert", "blogger"):
        tail = "属观点性证据，待更强研究确认，仅供参考"
    else:
        tail = "证据级别最低，谨慎对待"
    return head + "；" + tail + "。"


# 同义词/别名组:换个常见叫法也能命中(旅程5——"氨糖↔氨基葡萄糖"互不相通的问题)
ALIAS_GROUPS = [
    ["氨糖", "氨基葡萄糖", "葡萄糖胺"],
    ["乳清", "乳清蛋白", "蛋白粉", "whey"],
    ["练后", "运动后", "训练后", "锻炼后"],
    ["维生素c", "维c", "vc"],
    ["欧米伽3", "omega3", "omega-3", "ω-3", "鱼油"],
    ["增肌粉", "蛋白粉", "乳清"],
    ["肌酸", "creatine"],
]


def _alias_extra(text):
    """若条目文本里出现某别名组的任一成员,把整组别名拼进检索串——这样用户用任意叫法都能命中。"""
    low = str(text).lower()
    extra = []
    for grp in ALIAS_GROUPS:
        if any(a in low for a in grp):
            extra.extend(grp)
    return " ".join(dict.fromkeys(extra))  # 去重保序


def _core_text(it):
    """短检索串的原料:标题+结论(+别名)。二字 shingle 只在这上面匹配,避免正文泛字误命中。"""
    base = " ".join(str(it.get(k, "")) for k in ("title", "conclusion")).replace("**", "")
    return base + " " + _alias_extra(base + " " + str(it.get("summary", "")))


def search_blob(it):
    """整句精确匹配用的全文串(标题/结论/摘要/分类/人群/注意 + 别名)。"""
    full = " ".join(str(it.get(k, "")) for k in
                    ("title", "conclusion", "summary", "category", "population", "caveats")).replace("**", "")
    return e(full + " " + _alias_extra(full))


def fuzzy_blob(it):
    """弱语义 shingle 匹配用的短串(仅标题+结论+别名)——收窄范围,去掉正文里'区别/能吃/东西'等泛字误命中。"""
    return e(_core_text(it))


def legend_strip():
    chunks = []
    for ev in ("rct", "meta", "observational", "expert"):
        chunks.append(f'<span class="ls-item">{strength_meter(ev, False)}<span>{e(EV_LABEL[ev])}</span></span>')
        if ev != "expert":
            chunks.append('<span class="ls-sep"></span>')
    items = "".join(chunks)
    return (f'<div class="legend-strip"><span class="ls-title">证据强度（强→弱）</span>{items}'
            f'<span class="ls-item" style="margin-left:auto;color:var(--faint)">个例 →</span></div>')


def _basis_origin(it):
    """卡片底部「核验依据」要显示的真实出处——从证据/官方链接的主机名归纳，
    而不是直接用 source 字段（source 可能写'XX播客'，会让 study_supported 卡显示
    '核验依据：XX播客'，自相矛盾、误导信任，judge 审出）。"""
    labels, seen = [], set()
    for u in _evidence_pool(it):
        if not _is_evidence_url(u):
            continue
        host = (urllib.parse.urlsplit(u).hostname or "").lower()
        if "pubmed" in host: name = "PubMed"
        elif "doi.org" in host: name = "DOI"
        elif "cochrane" in host: name = "Cochrane"
        elif "who.int" in host: name = "WHO"
        elif "nih.gov" in host or "ods.od" in host or "nccih" in host: name = "NIH"
        elif "uspreventive" in host: name = "USPSTF"
        elif "cdc.gov" in host: name = "CDC"
        elif "nhc.gov.cn" in host: name = "卫健委"
        elif "chinacdc" in host: name = "中国CDC"
        elif "nhs.uk" in host: name = "NHS"
        elif "europa.eu" in host: name = "EFSA/EU"
        else: name = host
        if name not in seen:
            seen.add(name); labels.append(name)
    return " / ".join(labels[:3])


def card(it):
    """首页核验卡：依据状态为主信号，证据强度为副信号。"""
    slug, cat = e(it.get("slug", "")), e(it.get("category", ""))
    basis = verification_basis(it)
    if basis == "frontier_pending":
        lead, origin = "你可能在这听到", it.get("source", "")
    else:
        lead = "核验依据"
        origin = _basis_origin(it) or it.get("source", "")  # 真研究出处；兜底才用 source
    feat = " feat" if it.get("featured") else ""
    star = '<span class="star">✦ 精选</span>' if it.get("featured") else ""
    return (f'<a class="card{feat}" href="claims/{slug}.html">\n'
            f'  <div class="card-top"><span class="cat">{cat}</span>{star}</div>\n'
            f'  <div class="signal">{trust_badge(basis)}{strength_meter(it.get("evidence", ""))}</div>\n'
            f'  <h3>{e(it.get("title", ""))}</h3>\n'
            f'  <p class="verdict">{fmt(it.get("conclusion") or it.get("summary", ""))}</p>\n'
            f'  <div class="card-foot"><span class="src"><span class="lead">{e(lead)}</span><br>'
            f'{e(origin)}</span><span class="go">→</span></div>\n'
            f'</a>')


_BASIS_ROW_CLASS = {"study_supported": "b-study", "official_basis": "b-official",
                    "frontier_pending": "b-front pend"}


def hrow(it):
    """首页「重点核验」横向行（改动2 落地版）：左=信任徽章+证据强度(主信号)、
    中=标题+结论+证据提示、右=分类+复核日期(次要弱化)。按重要性排、不按时间。
    沿用线上三层信任系统(研究支持/官方依据/前沿待核)，不回退成二元。"""
    basis = verification_basis(it)
    rowcls = _BASIS_ROW_CLASS.get(basis, "b-front pend")
    slug = e(it.get("slug", ""))
    reviewed = e((it.get("reviewed_at") or it.get("date", ""))[5:])
    return (f'<a class="hrow {rowcls}" href="claims/{slug}.html">'
            f'<div class="hrow-sig">{trust_badge(basis)}{strength_meter(it.get("evidence",""))}</div>'
            f'<div class="hrow-main"><h3>{e(it.get("title",""))}</h3>'
            f'<p>{fmt(it.get("conclusion") or it.get("summary",""))}</p>'
            f'<div class="hrow-hint">{e(evidence_hint(it))}</div></div>'
            f'<div class="hrow-meta"><span class="hrow-cat">{e(it.get("category",""))}</span>'
            f'<span class="hrow-date">本站复核 {reviewed}</span></div></a>')


def list_row(it):
    """全部页可扫读列表行：静态渲染，JS 只负责筛选和搜索。"""
    cat = e(it.get("category", ""))
    reviewed = e((it.get("reviewed_at") or it.get("date", ""))[5:])
    return (f'<a class="list-row" href="claims/{e(it.get("slug", ""))}.html" '
            f'data-cat="{cat}" data-basis="{e(verification_basis(it))}" '
            f'data-ev="{e(it.get("evidence", ""))}" data-search="{search_blob(it)}" '
            f'data-fuzzy="{fuzzy_blob(it)}">\n'
            f'  <span class="lr-cat">{cat}</span>\n'
            f'  <span class="lr-sig">{trust_badge(verification_basis(it))}'
            f'{strength_meter(it.get("evidence", ""), False)}</span>\n'
            f'  <span class="lr-claim"><span class="lc-t">{e(it.get("title", ""))}</span>'
            f'<span class="lc-v">{fmt(it.get("conclusion") or it.get("summary", ""))}</span></span>\n'
            f'  <span class="lr-date">{reviewed}</span>\n'
            f'</a>')


def changelog_correction_count():
    """统计公开"纠错"次数(重新复核 + 结论更正·证据降级 的条目),不含纯"新增核验"。
    用作首页信任徽章:敢公开认错=最强的"不恰饭"信号(旅程3/4)。"""
    try:
        with open(os.path.join(ROOT, "data", "changelog.json"), encoding="utf-8") as fh:
            entries = json.load(fh)
    except Exception:
        return 0
    return sum(len(e.get("items", [])) for e in entries
               if any(k in e.get("type", "") for k in ("更正", "降级", "复核")))


def recent_reviews_module(items, n=6):
    """最近复核模块（P2）：刻意保持为「模块」而非主骨架——证明这库在持续维护，
    但不让日期取代「依据状态」成为主信号。关键诚实点：日期标「本站复核日」，
    不冒充研究发表日；原文日期单列，让「2015 的研究、2026 复核」一目了然。"""
    rv = sorted([it for it in items if it.get("reviewed_at")],
                key=lambda x: x.get("reviewed_at", ""), reverse=True)[:n]
    if not rv:
        return ""
    rows = ""
    for it in rv:
        sp = it.get("source_published_at", "")
        orig = f'<span class="rv-orig">原文 {e(sp)}</span>' if sp else '<span class="rv-orig dim">原文日期未标注</span>'
        rows += (f'<a class="rv-item" href="claims/{e(it.get("slug",""))}.html">'
                 f'<div class="rv-dates"><span class="rv-checked">本站复核 {e(it.get("reviewed_at",""))}</span>{orig}</div>'
                 f'<div class="rv-body"><span class="rv-title">{e(it.get("title",""))}</span>'
                 f'{trust_badge(verification_basis(it))}</div></a>')
    nfix = changelog_correction_count()
    fix_link = (f'<a class="more fix-more" href="log.html">我们公开更正过 {nfix} 处结论 →</a>'
                if nfix else '<a class="more" href="log.html">更新与纠错记录 →</a>')
    return (f'<section class="sec recent-sec" style="padding-top:0"><div class="wrap">'
            f'<div class="sec-head"><h2>最近复核</h2>{fix_link}</div>'
            f'<p class="rv-note">下面的日期是<b>本站复核日</b>，不是研究发表日——两个都标出来，'
            f'让你看清「这条底层研究多新、我们什么时候核对过」。这个库会出错，也会<b>公开认错</b>。</p>'
            f'<div class="rv-flow">{rows}</div></div></section>')


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
      <div class="f-col"><h5>AI 接入</h5><a href="{base}ai.html">一键接入</a><a href="{base}ai.html">claims.json</a><a href="{base}ai.html">安装 Skill</a></div>
    </div>
  </div>
  <div class="foot-bottom">本站为科普整理，<b>非医疗建议</b>；每条说法标注证据等级与来源状态，点击可回来源核对。 · {e(SITE_TITLE)} · 持续收集与查证</div>
</div></footer>'''


def cf_analytics_tag(token=None):
    """Cloudflare Web Analytics beacon（可选，全站统一注入点）。
    token 缺省读 CF_ANALYTICS_TOKEN；为空返回 ""——调用方据此实现「没 token 一字不出」。
    token 走 JSON 编码进单引号属性，并转义 ' 与 </，防属性逃逸 / <script> 截断。"""
    token = (token if token is not None else CF_ANALYTICS_TOKEN) or ""
    token = token.strip()
    if not token:
        return ""
    cfg = json.dumps({"token": token}, ensure_ascii=False).replace("'", "&#39;").replace("</", "<\\/")
    return f"<script defer src=\"https://static.cloudflareinsights.com/beacon.min.js\" data-cf-beacon='{cfg}'></script>"


def shell(title, active, inner, base="", extra_js="", desc="", canon="", narrow_footer=False, detail=False):
    nav_items = [("精选", "index.html"), ("全部", "all.html"), ("更新", "log.html"), ("关于", "about.html")]
    nav = "".join(
        f'<a class="{"on" if lbl == active else ""}" href="{base}{href}">{lbl}</a>'
        for lbl, href in nav_items)
    # </body> 前统一追加可选 analytics；无 token 时 cf_analytics_tag()=="" ⇒ tail==extra_js，产物逐字节不变。
    tail = "\n".join(p for p in (extra_js, cf_analytics_tag()) if p)
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
  <div class="nav-links">{nav}<a href="{base}ai.html" class="ai{' on' if active == 'AI 接入' else ''}">🤖 AI 接入</a></div>
</div></nav>
<main>
{inner}
</main>
{footer(base, narrow_footer, detail)}
{tail}
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
        if _is_evidence_url(u) and u not in seen:  # JSON-LD citation 只列核验依据（与 feed/详情页同尺）
            seen.add(u); cites.append(u)
    if cites:
        data["citation"] = cites
    j = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{j}</script>'


def detail_page(it, related):
    ev = it.get("evidence", "")
    basis = verification_basis(it)
    pending = basis == "frontier_pending"
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
    evs = [u for u in (it.get("evidence_source_urls") or []) if isinstance(u, str) and _is_evidence_url(u)]
    nonstudy = [u for u in (it.get("evidence_source_urls") or []) if isinstance(u, str) and not _is_evidence_url(u)]
    fallback_disc = it.get("source_url", "") if not _is_evidence_url(it.get("source_url", "")) else ""
    disc = it.get("discovery_source_url", "") or (nonstudy[0] if nonstudy else "") or fallback_disc
    dual = ""
    if disc:
        proof = (f'<a href="{e(_safe_href(evs[0]))}" target="_blank" rel="noopener">'
                 f'{e(_link_label(evs[0]))}</a>') if evs else "核验依据待补"
        proof_note = (("研究证据 · 回答问题" if basis == "study_supported" else "官方依据 · 回答问题")
                      if evs else "尚未补齐，不当定论")
        proof_class = "" if evs else " 待补"
        proof_style = "" if evs else ' style="color:var(--pd-ink)"'
        dual = (f'<div class="dlink"><div class="dlink-head">把「听来的」和「有据的」分开</div>'
                f'<div class="dlink-track"><div class="dnode heard">'
                f'<div class="dn-k">🎧 你可能在这听到</div>'
                f'<div class="dn-v"><a href="{e(_safe_href(disc))}" target="_blank" rel="noopener">'
                f'{e(it.get("source", "") or _link_label(disc))}</a><small>discovery · 提出问题</small></div></div>'
                f'<div class="dlink-mid"><span class="dots">····</span><span class="arrow">→</span></div>'
                f'<div class="dnode proof{proof_class}"><div class="dn-k">🔬 核验依据</div>'
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
             f'<div class="d-signal"><div class="row"><span class="k">依据状态</span>{trust_badge(basis)}</div>'
             f'<div class="row"><span class="k">证据强度</span>{strength_meter(ev)}</div></div>'
             f'{dual}{"".join(fields)}{evidence_links}'
             f'<div class="src-line">来源：{e(it.get("source", ""))}<br>'
             f'{date_meta}'
             f'本站复核 {e(it.get("reviewed_at") or TODAY)}</div>{rel}'
             f'<div class="d-share"><span class="ds-t">觉得有用？把这条转给还在交智商税的训练搭子 👇</span>'
             f'<button class="ds-btn" type="button" id="sharebtn">复制这条链接</button>'
             f'<span class="ds-ok" id="shareok" hidden>已复制 ✓</span></div>'
             f'<div class="disclaim">本站为科普整理，<b>非医疗建议</b>；每条说法标注证据等级与来源状态，'
             f'点击可回来源核对。具体到个人，请咨询医生或专业人士。</div></div>')
    share_js = '''<script>
(function(){var b=document.getElementById('sharebtn'),ok=document.getElementById('shareok');if(!b)return;
var u=location.href.split('#')[0],t=(document.title||'').split(' · ')[0],txt=t+' — 查过再信 '+u;
function done(){if(ok)ok.hidden=false;b.textContent='已复制 ✓';setTimeout(function(){b.textContent='复制这条链接';if(ok)ok.hidden=true;},2200);}
b.addEventListener('click',function(){
  if(navigator.share){navigator.share({title:t,text:t,url:u}).then(done).catch(function(){});return;}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(done,function(){
    var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();try{document.execCommand('copy')}catch(e){}ta.remove();done();});}
  else{var ta=document.createElement('textarea');ta.value=txt;document.body.appendChild(ta);ta.select();try{document.execCommand('copy')}catch(e){}ta.remove();done();}
});})();
</script>'''
    return shell(it.get("title", ""), "", inner + ld_json(it), base="../", extra_js=share_js,
                 desc=(it.get("conclusion") or it.get("summary", "")),
                 canon="claims/" + it.get("slug", "") + ".html", detail=True)


def render_index(items):
    # 按重要性排，不按时间：① 已核验(有依据)在前、前沿待核沉底 ② 同档证据强度降序(RCT/Meta 顶上)
    feats = sorted([it for it in items if it.get("featured")],
                   key=lambda x: (0 if verification_status(x) == "verified" else 1,
                                  -EVIDENCE_SCORE.get(x.get("evidence", ""), 0)))
    rows = "\n".join(hrow(it) for it in feats) or '<p class="empty">还没有核验条目。</p>'
    hero = (f'<header class="hero"><div class="wrap"><span class="eyebrow">EVIDENCE-CHECKED · 循证核验</span>'
            f'<h1>听到一个健康说法？<br>先查一下证据。</h1>'
            f'<p class="lede">每条说法都标注<b>证据强度</b>、<b>适用人群</b>和<b>来源状态</b>'
            f'——把「听来的」和「有据的」分开，尤其是<b>健身、补剂</b>这些最容易交智商税的说法。</p>'
            f'<p class="trustline">不卖任何产品 · 不接补剂广告 · 只把证据摆给你看</p>'
            f'<form class="searchbox" action="all.html" method="get">'
            f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>'
            f'<input type="text" name="q" placeholder="比如：肌酸伤血脂吗、练后冰浴、胶原蛋白有用吗…">'
            f'<button type="submit">查证据</button></form>{legend_strip()}</div></header>')
    featured = (f'<section class="sec"><div class="wrap"><div class="sec-head"><h2>重点核验</h2>'
                f'<a class="more" href="all.html">看全部 {len(items)} 条 →</a></div>'
                f'<div class="hlist">{rows}</div></div></section>')
    agent = (f'<section class="sec" id="ai" style="padding-top:0"><div class="wrap"><div class="ai-band">'
             f'<div class="ab-l"><div class="robot">🤖 第二形态 · 被 AI 调用</div><h3>让 AI 助手直接查本站</h3>'
             f'<p>本站提供公开机读接口。你的 AI 助手可以区分「研究支持」「官方依据」与「前沿待核」，'
             f'回答健康问题时带上证据强度和对应来源链接。</p>'
             f'<a class="ab-cta" href="ai.html">一键接入 · 复制提示词粘给你的 AI →</a></div><div class="ab-r">'
             f'<div class="codeblk"><div class="ck">公开数据接口 · 任何人可匿名抓取</div>'
             f'<code>{e(SITE_URL)}claims.json</code></div>'
             f'<div class="codeblk"><div class="ck">安装 Skill（Claude Code）</div>'
             f'<code>mkdir -p ~/.claude/skills/health-hot &amp;&amp; curl -fsSL {e(SITE_URL)}skill/SKILL.md '
             f'-o ~/.claude/skills/health-hot/SKILL.md</code></div>'
             f'<div class="codeblk"><div class="ck">安装 Skill（Codex）</div>'
             f'<code>mkdir -p ~/.codex/skills/health-hot &amp;&amp; curl -fsSL {e(SITE_URL)}skill/SKILL.md '
             f'-o ~/.codex/skills/health-hot/SKILL.md</code></div></div></div></div></section>')
    recent = recent_reviews_module(items)
    return shell("精选", "精选", hero + featured + recent + agent,
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
    # 第二行：按依据状态 / 证据强度筛（judge 第3条 — 判断可信度的核心动作）
    n_study = sum(1 for it in items if verification_basis(it) == "study_supported")
    n_off = sum(1 for it in items if verification_basis(it) == "official_basis")
    n_front = sum(1 for it in items if verification_basis(it) == "frontier_pending")
    n_strong = sum(1 for it in items if it.get("evidence") in ("rct", "meta"))
    bchips = (f'<button class="bchip on" data-b="all">不限依据</button>'
              f'<button class="bchip" data-b="study_supported">研究支持<span class="ct">{n_study}</span></button>'
              f'<button class="bchip" data-b="official_basis">官方依据<span class="ct">{n_off}</span></button>'
              f'<button class="bchip" data-b="frontier_pending">前沿待核<span class="ct">{n_front}</span></button>'
              f'<button class="bchip" data-b="strong">仅 Meta/RCT<span class="ct">{n_strong}</span></button>')
    rows = "\n".join(list_row(it) for it in items)
    if SUBMIT_ENDPOINT:
        empty_desc = "想让我们查这条？点一下提交，它会进入待核清单；我们会去查原始研究，做成一条可追溯的核验。"
        primary_label = "提交这条说法待核"
        secondary_label = "复制给作者"
        empty_note = "只有点击提交才会发送；请只提交听到的健康说法，不要提交个人病史、症状或紧急医疗问题。"
        fallback_note = ""
    else:
        empty_desc = "想让我们查这条？当前还未配置一键提交接收端；可以先复制/分享给作者，不会假装提交成功。"
        primary_label = "复制这条说法，发给作者待核"
        secondary_label = ""
        empty_note = "当前不会自动提交或保存搜索；请不要在搜索框输入个人病史、症状或紧急医疗问题。"
        fallback_note = '<p class="copy-tip" id="fallbacktip">当前还未配置一键提交接收端；点击按钮会复制/分享给作者。</p>'
    secondary_button = f'<button class="empty-cta ghost" id="copyclaim" type="button">{secondary_label}</button>' if secondary_label else ''
    inner = (f'<header class="hero all-hero"><div class="wrap"><span class="eyebrow">ALL CLAIMS · 全部核验</span>'
             f'<h1>全部核验</h1><p class="lede">一行一条，依据状态与证据强度在扫读时就能分辨。</p>'
             f'<form class="searchbox all-search" onsubmit="event.preventDefault();applyFilters()">'
             f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             f'stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>'
             f'<input type="text" id="q" placeholder="搜索说法、结论或关键词…" oninput="applyFilters()">'
             f'</form></div></header><section class="sec all-sec"><div class="wrap"><div class="controls">'
             f'<div class="filterbar" id="filterbar">{pills}</div>'
             f'<div class="filterbar basisbar" id="basisbar">{bchips}</div>'
             f'<span class="count" id="count"></span></div>'
             f'<p class="fuzzytip" id="fuzzytip" hidden></p>'
             f'<div class="listwrap"><div class="list-head"><span>主题</span><span>依据 / 强度</span>'
             f'<span>说法 · 结论</span><span>复核</span></div><div id="list">{rows}</div>'
             f'<div class="empty" id="empty" hidden>'
             f'<div id="ask-state"><p class="empty-t">本库还没有核验过 <b id="emptyq"></b></p>'
             f'<p class="empty-d">{e(empty_desc)}</p>'
             f'<button class="empty-cta" id="submitclaim" type="button">{e(primary_label)}</button>'
             f'{secondary_button}'
             f'<p class="empty-note">{e(empty_note)}</p>'
             f'<input id="website" class="hp-field" type="text" autocomplete="off" tabindex="-1" aria-hidden="true">'
             f'<p class="copy-tip" id="submittip" hidden></p>'
             f'<p class="copy-tip" id="copytip" hidden></p>{fallback_note}</div>'
             f'</div>'
             f'</div></div></section>')
    submit_endpoint_js = json.dumps(SUBMIT_ENDPOINT, ensure_ascii=False)
    event_endpoint_js = json.dumps(EVENT_ENDPOINT, ensure_ascii=False)
    js = '''<script>
const SUBMIT_ENDPOINT=__SUBMIT_ENDPOINT__;
const EVENT_ENDPOINT=__EVENT_ENDPOINT__;
// 站内搜索打点:停手~1s后才发一条 {term,hit},同词只发一次,绝不每键发。sendBeacon/text-plain 免CORS预检、fire-and-forget。
let evtTimer=null,lastSentQ='';
function sendSearchEvent(term,hit){if(!EVENT_ENDPOINT)return;
  const body=JSON.stringify({term:term,hit:hit});
  try{if(navigator.sendBeacon){navigator.sendBeacon(EVENT_ENDPOINT,new Blob([body],{type:'text/plain;charset=UTF-8'}));return;}}catch(e){}
  try{fetch(EVENT_ENDPOINT,{method:'POST',headers:{'Content-Type':'text/plain'},body:body,keepalive:true}).catch(()=>{});}catch(e){}}
function scheduleSearchEvent(term,hit){if(!EVENT_ENDPOINT||term.length<2||term===lastSentQ)return;
  clearTimeout(evtTimer);
  evtTimer=setTimeout(()=>{if(term===((input.value||'').trim())){lastSentQ=term;sendSearchEvent(term,hit);}},1000);}
let activeCat='all', activeBasis='all'; const rows=[...document.querySelectorAll('.list-row')];
const input=document.getElementById('q'), count=document.getElementById('count'), empty=document.getElementById('empty');
const allSec=document.querySelector('.all-sec'), fuzzytip=document.getElementById('fuzzytip');
const qp=new URLSearchParams(location.search).get('q'); if(qp) input.value=qp;
// 问句/语气词：用户多半自然语言提问（"XX伤肾吗""有没有用"），先去掉这些再拆核心词
const STOP=['是不是','是否','会不会','有没有','能不能','可不可以','可以吗','好不好','对不对','该不该','要不要','怎么样','怎么','如何','为什么','究竟','到底','真的吗','真的','是真是假','有用吗','有用','有效吗','有效','靠谱吗','靠谱','安全吗','管用吗','管用','到底','区别','东西','吗','呢','吧','啊','呀','嘛','哦','的','了'];
function matchBasis(r){if(activeBasis==='all')return true;
  if(activeBasis==='strong')return r.dataset.ev==='rct'||r.dataset.ev==='meta';
  return r.dataset.basis===activeBasis;}
function passFilter(r){return (activeCat==='all'||r.dataset.cat===activeCat)&&matchBasis(r);}
function cleanQ(raw){let q=raw.toLowerCase();STOP.forEach(w=>{q=q.split(w).join(' ');});return q;}
// 拆核心词:整词(英文/数字/CJK,较具体)走全文;二字 shingle(兜底)只走短blob,避免正文泛字误命中
function coreTerms(clean){const parts=clean.split(/[^0-9a-z一-鿿]+/).filter(Boolean);
  const words=new Set(), shingles=new Set();
  parts.forEach(p=>{if(p.length>=2)words.add(p);
    if(/[一-鿿]/.test(p)&&p.length>=3){for(let i=0;i<p.length-1;i++)shingles.add(p.substr(i,2));}});
  return {words:[...words], shingles:[...shingles]};}
const emptyq=document.getElementById('emptyq');
let lastQ='这个说法';
function applyFilters(){
  const raw=(input.value||'').trim(), ql=raw.toLowerCase();
  const cl=cleanQ(raw).replace(/\\s+/g,''), tms=coreTerms(cleanQ(raw));
  let exact=[], fuzzy=[];
  rows.forEach(r=>{ r.style.display='none'; if(!passFilter(r))return;
    if(!raw){exact.push(r);return;}
    const blob=r.dataset.search.toLowerCase();              // 全文:标题/结论/摘要/人群/注意+别名
    const sblob=(r.dataset.fuzzy||blob).toLowerCase();      // 短blob:仅标题+结论+别名
    if(blob.includes(ql)||(cl.length>=2&&blob.includes(cl))){exact.push(r);return;}   // 精确:整句 或 去问句词后核心串(全文)
    // 弱语义:整词在全文命中,或二字shingle在短blob命中(shingle不碰正文,去泛字噪音)
    if(tms.words.some(w=>blob.includes(w))||tms.shingles.some(s=>sblob.includes(s)))fuzzy.push(r);
  });
  let shown, isFuzzy=false;
  if(!raw||exact.length){shown=exact;} else {shown=fuzzy;isFuzzy=fuzzy.length>0;}
  shown.forEach(r=>r.style.display='');
  const n=shown.length, filtersActive=activeCat!=='all'||activeBasis!=='all';
  count.textContent=(isFuzzy?'可能相关 ':'')+n+' 条 · 共 '+rows.length+' 条';
  if(isFuzzy&&raw){fuzzytip.textContent='没有与「'+raw+'」完全匹配的；以下为可能相关，点进去看是不是你想查的：';fuzzytip.hidden=false;}
  else{fuzzytip.hidden=true;}
  empty.hidden=n!==0;
  allSec.classList.toggle('no-results', n===0 && !!raw && !filtersActive);   // 纯查询 0 结果：筛选器/表头收起、提交 CTA 顶到搜索框下
  if(n===0){lastQ=raw||'这个说法';emptyq.textContent='「'+lastQ+'」';
    document.getElementById('copytip').hidden=true;document.getElementById('submittip').hidden=true;}
  scheduleSearchEvent(raw, n>0);}
document.getElementById('filterbar').addEventListener('click',e=>{const b=e.target.closest('.fchip');if(!b)return;
  activeCat=b.dataset.c;document.querySelectorAll('.fchip').forEach(x=>x.classList.toggle('on',x===b));applyFilters();});
document.getElementById('basisbar').addEventListener('click',e=>{const b=e.target.closest('.bchip');if(!b)return;
  activeBasis=b.dataset.b;document.querySelectorAll('.bchip').forEach(x=>x.classList.toggle('on',x===b));applyFilters();});
function setTip(id,msg){const tip=document.getElementById(id);tip.textContent=msg;tip.hidden=false;return tip;}
function claimText(){return '我想查这个健康说法是真是假：'+lastQ+'（来自 查过再信 '+location.origin+location.pathname.replace(/all\\.html$/,'')+'）';}
function copyClaim(){
  const txt=claimText(),tip=document.getElementById('copytip');
  const ok=()=>{tip.textContent='已复制 ✓ 发给作者后会进入待核清单。';tip.hidden=false;document.getElementById('submittip').hidden=true;};
  if(navigator.share){navigator.share({title:'查过再信待核说法',text:txt}).then(ok).catch(()=>{});return;}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(ok).catch(()=>{
    const t=document.createElement('textarea');t.value=txt;document.body.appendChild(t);t.select();
    try{document.execCommand('copy')}catch(e){}t.remove();ok();});}
  else{const t=document.createElement('textarea');t.value=txt;document.body.appendChild(t);t.select();
    try{document.execCommand('copy')}catch(e){}t.remove();ok();}
}
const copyButton=document.getElementById('copyclaim');
if(copyButton)copyButton.addEventListener('click',copyClaim);
document.getElementById('submitclaim').addEventListener('click',async()=>{
  if(!SUBMIT_ENDPOINT){copyClaim();return;}
  const claim=(lastQ||'').trim(),btn=document.getElementById('submitclaim');
  if(!claim||claim==='这个说法'){setTip('submittip','请先输入想核验的健康说法。');return;}
  btn.disabled=true;btn.textContent='提交中…';document.getElementById('copytip').hidden=true;
  try{
    const res=await fetch(SUBMIT_ENDPOINT,{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({claim:claim,page:location.href,source:'empty-search',website:document.getElementById('website').value||''})});
    const data=await res.json().catch(()=>({}));
    if(!res.ok)throw new Error(data.error||'提交失败');
    setTip('submittip',data.status==='duplicate'?'已收到过这条，会合并处理。':'已提交 ✓ 已进入待核清单。');
  }catch(e){
    setTip('submittip','提交失败：已为你保留复制入口，可以先发给作者。');
  }finally{
    btn.disabled=false;btn.textContent=SUBMIT_ENDPOINT?'提交这条说法待核':'复制这条说法，发给作者待核';
  }
});
if(!SUBMIT_ENDPOINT){
  document.getElementById('submitclaim').textContent='复制这条说法，发给作者待核';
}
applyFilters();
</script>'''
    js = js.replace("__SUBMIT_ENDPOINT__", submit_endpoint_js).replace("__EVENT_ENDPOINT__", event_endpoint_js)
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
<div class="method-item"><div class="mi-n">01</div><div><h3>三类依据：先看「凭什么相信」</h3>
<p>每条说法先归入三类之一。<b>研究支持</b>：可点回 PubMed / DOI / Cochrane 等研究锚点。<b>官方依据</b>：可点回 WHO、NIH、卫健委、中国疾控等白名单机构的具体页面。<b>前沿待核</b>：来自专家、播客或趋势线索，但核验依据还没补齐。三类不互相冒充：官方建议不是原始研究，前沿观点也不是结论。</p></div></div>
<div class="method-item"><div class="mi-n">02</div><div><h3>证据分级：再标「依据有多硬」</h3>
<p>在依据状态之外，再按证据强度分七级。两个维度组合出可信度光谱：一条可以是「研究支持 + Meta」，也可以是「官方依据 + 指南」或「前沿待核 + 专家」。</p>
<div class="src-table about-grade">{grades}</div></div></div>
<div class="method-item"><div class="mi-n">03</div><div><h3>双链接：你在哪听到 ≠ 凭什么相信</h3>
<p><b>发现来源（discovery）</b>是「你可能在某播客听到这个说法」，<b>核验依据（evidence）</b>是「研究或官方原文在哪里」。<b>播客负责提出问题，研究与官方页面负责提供可回溯依据</b>。</p></div></div>
<div class="method-item"><div class="mi-n">04</div><div><h3>信源体系：三种角色，各司其职</h3><div class="src-table">
<div class="src-role"><span class="role-tag anchor">锚点 ANCHOR</span><div class="role-d"><strong>决定结论、做核验依据</strong><span>WHO / USPSTF / NIH 官方事实页与指南，PubMed 的 Cochrane 系统综述 / 指南 / 系统综述查询</span></div></div>
<div class="src-role"><span class="role-tag discovery">发现 DISCOVERY</span><div class="role-d"><strong>只负责发现「大家在讨论什么」，不下结论</strong><span>可信专家的播客 / YouTube / 博客进入候选池，但不能自动作为核验依据</span></div></div>
<div class="src-role"><span class="role-tag radar">雷达 RADAR</span><div class="role-d"><strong>追踪新论文与趋势</strong><span>PubMed 窄主题查询；趋势不能直接冒充结论</span></div></div>
</div></div></div>
<div class="method-item"><div class="mi-n">05</div><div><h3>复核与纠错</h3>
<p>每条都带<b>复核日期</b>，随研究更新而重新审视。发布前有自动闸门：缺来源、未来日期、伪链接、未审核的条目一律进不了线上。发现错误？欢迎通过 <a href="{REPO}/issues" target="_blank" rel="noopener"><b>GitHub issue</b></a> 指出。</p></div></div>
<div class="method-item"><div class="mi-n">06</div><div><h3>内容红线</h3>
<p>这是健康产品，有刚性约束：<b>不是医疗建议</b>，不开处方、不给具体剂量、不暗示治疗任何疾病；不确定的、证据弱的，明确标注，绝不替它下定论。</p></div></div>
<div class="method-item"><div class="mi-n">07</div><div><h3>谁做的、靠什么活（利益披露）</h3>
<p>这个库由<b>个人维护</b>，<b>没有任何商业收入</b>：<b>不卖任何产品、不接补剂或品牌广告、不做带货、不收会员费</b>，页面上也不会出现联盟链接。做它的唯一目的，是把自己查过的健康/健身/补剂说法公开出来，让别人少交点智商税。正因为不靠卖东西赚钱，这个库才敢在结论里直说「这个没用」「这个被夸大了」——<b>没有任何产品需要我替它说好话</b>。</p></div></div>
</div></section>'''
    return shell("关于", "关于", inner,
                 desc="查过再信的方法论：怎么审核、证据如何分级、何时复核、如何纠错。",
                 canon="about.html", narrow_footer=True)


CHANGELOG_TYPE_CLASS = {"新增核验": "cl-add", "重新复核": "cl-review",
                        "结论更正 · 证据降级": "cl-fix"}


def render_changelog():
    """公开更新日志：刻意展示纠错（更正/降级），对核验库公开纠错=最强信任建设。"""
    path = os.path.join(ROOT, "data", "changelog.json")
    try:
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh)
    except Exception:
        entries = []
    blocks = ""
    for ent in entries:
        cls = CHANGELOG_TYPE_CLASS.get(ent.get("type", ""), "cl-add")
        lis = "".join(f"<li>{fmt(x)}</li>" for x in ent.get("items", []))
        blocks += (f'<div class="cl-entry"><div class="cl-meta"><span class="cl-date">{e(ent.get("date",""))}</span>'
                   f'<span class="cl-type {cls}">{e(ent.get("type",""))}</span></div>'
                   f'<ul class="cl-list">{lis}</ul></div>')
    inner = f'''<header class="about-h"><div class="wrap narrow"><span class="eyebrow">CHANGELOG · 更新日志</span>
<h1>更新与纠错记录</h1>
<p class="lede">这个库会出错，也会改正。新增了什么、重新复核了什么、把哪条结论更正或降级了——都公开记在这里。<b>会改正不可怕，藏着才可怕</b>，这正是「查过再信」的承诺。</p>
</div></header><section class="method"><div class="wrap narrow"><div class="changelog">{blocks or '<p>暂无记录。</p>'}</div></div></section>'''
    return shell("更新日志", "更新日志", inner,
                 desc="查过再信的公开更新与纠错记录：新增核验、重新复核、结论更正与证据降级。",
                 canon="log.html", narrow_footer=True)


AI_PROMPT = """你是循证健康助手。当我问你某个健康说法靠不靠谱时，请先抓取这个公开数据接口（任何人可匿名访问）：
{url}claims.json

里面每条说法都带这些字段，请这样用：
- verification_basis：研究支持 / 官方依据 / 前沿待核——务必区分，别把官方科普页说成原始研究。
- evidence_label：证据强度（RCT / Meta / 指南 / 观察 / 专家 / 博主 / 个例）。
- evidence_hint：一句现成的「该怎么信这条」，可以直接引用，但不要在它之上夸大。
- conclusion / caveats：结论与注意事项。
- detail_url / evidence_source_urls：详情页与原始研究 / 官方链接，回答时附上让我能回溯。

回答规则：
1. 库里有相关说法 → 引用它的 evidence_hint 和 conclusion，附 detail_url 和来源链接。
2. 库里没有 → 明确说「本库未收录这条」，不要编造，可建议我去站内提交待核。
3. 永远带上免责：这是科普整理、非医疗建议；不提供具体剂量或个体化诊疗。"""


def render_ai(items):
    """AI 接入页（第二形态）：把『被 AI 调用』从首页锚点升级成独立页。
    最核心是『一键接入』——一段可复制的提示词，粘进任意 ChatGPT / Claude 就能用本站 feed。"""
    prompt = AI_PROMPT.format(url=SITE_URL)
    # 选一个真实的 study_supported + 强证据条目，展示 evidence_hint 实际长什么样
    sample = next((it for it in items
                   if verification_basis(it) == "study_supported"
                   and it.get("evidence") in ("rct", "meta")), None) or (items[0] if items else None)
    sample_block = ""
    if sample:
        sample_block = (
            f'<div class="ai-sample"><div class="ck">feed 里一条的样子（节选）</div>'
            f'<div class="ais-row"><span class="ais-k">title</span><span class="ais-v">{e(sample.get("title",""))}</span></div>'
            f'<div class="ais-row"><span class="ais-k">verification_basis</span>'
            f'<span class="ais-v">{e(verification_basis(sample))} · {e(VB_LABEL[verification_basis(sample)])}</span></div>'
            f'<div class="ais-row"><span class="ais-k">evidence_label</span>'
            f'<span class="ais-v">{e(EV_LABEL.get(sample.get("evidence",""), ""))}</span></div>'
            f'<div class="ais-row hl"><span class="ais-k">evidence_hint</span>'
            f'<span class="ais-v">{e(evidence_hint(sample))}</span></div></div>')
    inner = f'''<header class="about-h"><div class="wrap narrow"><span class="eyebrow">FOR AI · 被 AI 调用</span>
<h1>让你的 AI 助手<br>直接查这个核验库</h1>
<p class="lede">这个库的第二个用途，是被机器调用。它提供公开机读接口，你的 ChatGPT / Claude 可以区分「研究支持」「官方依据」与「前沿待核」，回答健康问题时带上证据强度和可回溯的来源——而不是张口就来。</p>
</div></header><section class="method"><div class="wrap narrow">
<div class="method-item"><div class="mi-n">01</div><div><h3>一键接入：把这段话贴给你的 AI</h3>
<p>不用写代码。复制下面这段提示词，粘进 ChatGPT 或 Claude 的对话框，它就会在回答健康问题前先查本站数据、按证据强度作答。</p>
<div class="ai-prompt-wrap"><textarea id="aiprompt" class="ai-prompt" readonly rows="14">{e(prompt)}</textarea>
<button class="empty-cta" id="copyprompt" type="button">复制这段提示词</button>
<span class="copy-tip" id="copydone" hidden>已复制 ✓ 去粘给你的 AI 助手</span></div></div></div>
<div class="method-item"><div class="mi-n">02</div><div><h3>公开数据接口（claims.json）</h3>
<p>整库的机读版本，任何人可匿名抓取。带站点级医疗免责、字段说明（usage_note）与计数。适合接进自己的工具或 Agent。</p>
<div class="codeblk"><div class="ck">GET · 无需鉴权</div><code>{e(SITE_URL)}claims.json</code></div></div></div>
<div class="method-item"><div class="mi-n">03</div><div><h3>装成 Skill（Claude Code / Codex）</h3>
<p>如果你用 Claude Code 或 Codex，可以把本站装成一个 Skill，让它在本地就能调用这套核验逻辑。</p>
<div class="codeblk"><div class="ck">Claude Code</div>
<code>mkdir -p ~/.claude/skills/health-hot &amp;&amp; curl -fsSL {e(SITE_URL)}skill/SKILL.md -o ~/.claude/skills/health-hot/SKILL.md</code></div>
<div class="codeblk"><div class="ck">Codex</div>
<code>mkdir -p ~/.codex/skills/health-hot &amp;&amp; curl -fsSL {e(SITE_URL)}skill/SKILL.md -o ~/.codex/skills/health-hot/SKILL.md</code></div></div></div>
<div class="method-item"><div class="mi-n">04</div><div><h3>怎么读这个 feed：证据提示（evidence_hint）</h3>
<p>每条都带一个 <b>evidence_hint</b> 字段——它用「依据状态 + 证据强度」两个维度合成一句<b>可直接转述的解读</b>：先说有没有可追溯依据，再说证据有多硬。AI 拿到它就有现成、不夸大的「该怎么信这条」，不用自己揣测。</p>
{sample_block}
<p class="ai-note">注意：evidence_hint 是诚实的解读层，不是营销话术。它会直说「只能显示相关、不能证明因果」或「暂无可追溯依据，属前沿待核」——请连同这些限制一起呈现，别只摘对你结论有利的半句。</p></div></div>
</div></section>'''
    js = '''<script>
(function(){
  var btn=document.getElementById('copyprompt'),ta=document.getElementById('aiprompt'),done=document.getElementById('copydone');
  if(!btn||!ta)return;
  btn.addEventListener('click',function(){
    var txt=ta.value;
    function ok(){if(done){done.hidden=false;}btn.textContent='已复制 ✓';setTimeout(function(){btn.textContent='复制这段提示词';},2200);}
    if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(txt).then(ok,function(){ta.select();document.execCommand('copy');ok();});}
    else{ta.select();document.execCommand('copy');ok();}
  });
})();
</script>'''
    return shell("AI 接入", "AI 接入", inner,
                 desc="让你的 AI 助手直接调用查过再信核验库：一键提示词、公开 claims.json 接口、可装成 Skill。",
                 canon="ai.html", extra_js=js, narrow_footer=True)


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
        vb = verification_basis(it)
        # 证据链 = 研究锚点或白名单官方页面；发现链 = 播客/YT「在哪听到」，单列。
        evidence_urls = [u for u in srcs if _is_evidence_url(u)]
        out.append({
            "slug": slug,
            "title": it.get("title", ""),
            "detail_url": SITE_URL + "claims/" + slug + ".html",
            "category": it.get("category", ""),
            "verification_status": vs,                     # verified | curated_pending_evidence
            "verification_label": VS_LABEL[vs],
            "verification_basis": vb,                      # study_supported | official_basis | frontier_pending
            "verification_basis_label": VB_LABEL[vb],
            "evidence": it.get("evidence", ""),
            "evidence_label": EV_LABEL.get(it.get("evidence", ""), it.get("evidence", "")),
            "evidence_hint": evidence_hint(it),            # 派生解读层：依据状态+证据强度合成的「该怎么信」，供下游 AI 直接转述
            "conclusion": (it.get("conclusion") or it.get("summary") or "").replace("**", ""),
            "population": (it.get("population") or "").replace("**", ""),
            "caveats": (it.get("caveats") or "").replace("**", ""),
            "summary": (it.get("summary") or "").replace("**", ""),
            "source": it.get("source", ""),
            "evidence_source_urls": evidence_urls,         # 核验依据链接：研究或官方页面（可能为空）
            "discovery_source_url": it.get("discovery_source_url", "")
                                    or (srcs[0] if srcs and not evidence_urls else ""),  # 没研究时把源当「发现链」
            "source_urls": srcs,                           # 兼容旧字段：全部来源
            "featured": bool(it.get("featured", False)),
            "date": it.get("date", ""),
            "source_published_at": it.get("source_published_at", ""),
            "reviewed_at": it.get("reviewed_at", ""),
        })
    n_verified = sum(1 for c in out if c["verification_status"] == "verified")
    basis_counts = {k: sum(1 for c in out if c["verification_basis"] == k) for k in VB_LABEL}
    # generated_at 用「最新复核日」而非构建当天 → 同样内容反复构建产出 byte 级一致，
    # 让 docs/claims.json 可被 CI 的 git diff --exit-code 当成「必须等于闸门产物」来校验，
    # 堵住 GitHub Pages 直接 serve 已提交 docs/ 的旁路。无条目时退回 TODAY。
    generated_at = max((it.get("reviewed_at") or it.get("date") or TODAY) for it in items) if items else TODAY
    return {
        "schema_version": "1.4",  # 1.4: 新增 evidence_hint 派生解读层；1.3 起有三类 verification_basis（兼容旧消费者）
        "site": SITE_TITLE,
        "site_url": SITE_URL,
        "description": "中文循证健康说法核验库——每条结论标注证据强度、适用人群与原始出处。",
        "disclaimer": "本数据为科普整理，非医疗建议；不提供具体剂量与个体化诊疗。"
                      "请点击 detail_url / evidence_source_urls 回原文核对。",
        "usage_note": "新消费者请优先使用 verification_basis：study_supported=『研究支持』，"
                      "official_basis=『官方依据』，frontier_pending=『前沿待核』。"
                      "verification_status 仅为兼容旧消费者保留，不应用它把官方页面称为原始研究。"
                      "evidence_source_urls 为核验依据链接（研究或白名单官方页面），"
                      "discovery_source_url 是『在哪听到』（非证据）。"
                      "evidence_hint 是用依据状态+证据强度合成的可直接转述的解读，"
                      "回答用户时可原样引用，但请勿在此基础上夸大或加上本站未给出的剂量/诊疗建议。",
        "generated_at": generated_at,
        "count": len(out),
        "verified_count": n_verified,
        "study_supported_count": basis_counts["study_supported"],
        "official_basis_count": basis_counts["official_basis"],
        "frontier_pending_count": basis_counts["frontier_pending"],
        "claims": out,
    }




def main():
    items, load_errors = load_items()
    good, blocked = validate(items)
    # 发布闸门第二段——强审硬锁（Vercel 构建跑的就是 build.py，所以这是线上站真正的强审锁）。
    # 新增/改动条目不过 /health-review 就进 blocked → 与坏数据走同一 fail-safe：docs/ 不替换、退码 1。
    # 存量条目由 grandfather 固化清单按 content_sha 兜底放行（已强审的走 review_audit 权威路径）。
    audit, grandfather = load_strong_review_state()
    sr_failures = strong_review_gate(good, audit, grandfather)
    if sr_failures:
        sr_files = {fn for fn, _ in sr_failures}
        good = [it for it in good if it.get("_file") not in sr_files]
        blocked.extend(sr_failures)
    # 重点核验(精选)=算分自动选取(证据+rank+新鲜度+热点度)+类目均衡，替代手动 featured，避免冻住
    _mark_featured(good)
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
    with open(os.path.join(tmp, "log.html"), "w", encoding="utf-8") as f:
        f.write(render_changelog())
    with open(os.path.join(tmp, "ai.html"), "w", encoding="utf-8") as f:
        f.write(render_ai(good))
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
