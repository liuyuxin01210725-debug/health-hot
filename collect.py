#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集引擎 v5：从 data/sources.json 抓官方精选目录 / RSS / YouTube / PubMed，去重，产出"候选条目"。

v5 默认纳入可信专家发现层，并从节目简介 / 博客摘要提取 citation_urls_to_review：
  这些链接只是待核引用，不能自动升级成证据锚点。发现层临时失败只告警，不阻断官方 / PubMed 主流程。

v4 新增官方精选目录（type: official_catalog）：
  仅接受白名单政府 / 官方机构域名下的具体事实页或指南页，作为 anchor 候选。

v3 新增 PubMed 源（type: pubmed）：
  esearch 按主题找最新论文 PMID → efetch 抓免费摘要 → 候选。
  PubMed / E-utilities 完全免费，低频无需 API key。

候选写到 /tmp/health_candidates.json —— 由 Claude 按健康库 7 铁律摘要成
data/items/*.json，再跑 build.py 上站。

纯标准库。用法：
    python3 collect.py                 # 抓全部信源
    python3 collect.py PubMed Attia    # 只抓名字匹配的
"""
import json, os, sys, glob, re, html, time, threading, urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "data", "sources.json")
ITEMS = os.path.join(ROOT, "data", "items")
OUT = "/tmp/health_candidates.json"
META_OUT = "/tmp/health_collection_meta.json"
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}
PER_SOURCE = 5
DESC_CHARS = 2500
FETCH_ATTEMPTS = 3
TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}
OFFICIAL_HOSTS = {
    "who.int", "www.who.int",
    "uspreventiveservicestaskforce.org", "www.uspreventiveservicestaskforce.org",
    "ods.od.nih.gov",
    "nccih.nih.gov", "www.nccih.nih.gov",
    "cdc.gov", "www.cdc.gov",
    "nhc.gov.cn", "www.nhc.gov.cn",
    "chinacdc.cn", "www.chinacdc.cn", "en.chinacdc.cn",
}
REFERENCE_HOSTS = OFFICIAL_HOSTS | {
    "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov",
    "doi.org", "www.doi.org", "clinicaltrials.gov", "www.clinicaltrials.gov",
    "cochranelibrary.com", "www.cochranelibrary.com",
}

ATOM = '{http://www.w3.org/2005/Atom}'
MEDIA = '{http://search.yahoo.com/mrss/}'
CONTENT = '{http://purl.org/rss/1.0/modules/content/}encoded'
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
MON = {'jan':'01','feb':'02','mar':'03','apr':'04','may':'05','jun':'06',
       'jul':'07','aug':'08','sep':'09','oct':'10','nov':'11','dec':'12'}


_last_fetch = [0.0]  # 全局限速：NCBI 无 API key 建议 ≤3 req/s，这里统一 ≥0.35s 一次
_fetch_lock = threading.Lock()  # 加锁串行化 wait+update，否则并发调用者会一起醒来（codex 审出）


def _retry_delay(ex, attempt):
    retry_after = ex.headers.get('Retry-After') if getattr(ex, 'headers', None) else None
    try:
        retry_after = float(retry_after)
    except (TypeError, ValueError):
        retry_after = 0.0
    return min(30.0, max(retry_after, 2.0 ** (attempt + 1)))


def fetch(url, attempts=FETCH_ATTEMPTS, timeout=25, allowed_final_hosts=None):
    for attempt in range(attempts):
        try:
            return _fetch_once(url, timeout=timeout, allowed_final_hosts=allowed_final_hosts)
        except urllib.error.HTTPError as ex:
            if ex.code not in TRANSIENT_HTTP_CODES or attempt == attempts - 1:
                raise
            delay = _retry_delay(ex, attempt)
            print(f"[~] {ex.code} 临时响应，{delay:g}s 后重试 {attempt + 2}/{attempts}：{urllib.parse.urlsplit(url).netloc}")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError) as ex:
            if attempt == attempts - 1:
                raise
            delay = 2.0 ** (attempt + 1)
            print(f"[~] 临时网络错误 {ex!s}，{delay:g}s 后重试 {attempt + 2}/{attempts}：{urllib.parse.urlsplit(url).netloc}")
            time.sleep(delay)


def _fetch_once(url, timeout=25, allowed_final_hosts=None):
    with _fetch_lock:  # 串行节流：即使将来并发调用，间隔也真正 ≥0.35s
        wait = 0.35 - (time.monotonic() - _last_fetch[0])
        if wait > 0:
            time.sleep(wait)
        _last_fetch[0] = time.monotonic()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        # 跟随重定向后，确认最终 URL 仍是 http(s)——挡 file:// 等伪协议跳转（SSRF 纵深防御，codex 审出）。
        # 注：内网 IP（169.254/localhost）重定向不在此简易防护内；本地手动采集已知信源，风险极低。
        final = r.geturl()
        if not isinstance(final, str) or not re.match(r'^https?://', final, re.I):
            raise ValueError(f"最终 URL 非 http(s)，已拒绝（防 SSRF）：{final!r}")
        if allowed_final_hosts:
            host = (urllib.parse.urlsplit(final).hostname or '').lower()
            if host not in allowed_final_hosts:
                raise ValueError(f"最终 URL 不在允许域名中，已拒绝：{host!r}")
        return r.read(8 * 1024 * 1024)  # 8MB 上限，防超大 feed 撑爆内存


def safe_fromstring(raw):
    """解析不可信 XML：拒绝含内部实体定义 <!ENTITY 的文档——挡 billion-laughs 实体膨胀。
    只拒 <!ENTITY，不拒纯 DOCTYPE 声明：PubMed efetch 合法返回带外部 DTD 引用的
      <!DOCTYPE PubmedArticleSet PUBLIC ... "https://dtd.nlm.nih.gov/...">（无内部实体），
    一刀切拒 DOCTYPE 会把正常 PubMed 抓取也拒掉（已踩过这个回归）。
    XXE 方面：ElementTree/expat 默认不取外部实体（codex 实测确认），故外部 DTD 引用安全。
    全量扫描 + 去 NUL：防「长前导注释推后 <!ENTITY」与 UTF-16/32 编码绕过。纯标准库零依赖。"""
    if isinstance(raw, (bytes, bytearray)):
        low = raw.replace(b'\x00', b'').lower()
        if b'<!entity' in low:
            raise ValueError("XML 含内部实体定义 <!ENTITY，已拒绝（防实体膨胀 DoS）")
    return ET.fromstring(raw)


def t(el):
    return (el.text or '').strip() if el is not None else ''


def clean_text(s):
    s = s or ''
    if len(s) > 100_000:  # 防回溯型正则 ReDoS：feed 摘要不该有 100KB，超长先截断（codex 实测 560KB 卡 27 秒）
        s = s[:100_000]
    s = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', s)
    s = re.sub(r'(?s)<[^>]+>', ' ', s)
    s = html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def extract_urls(s, limit=20):
    """从 feed 简介提取上下文链接。只做发现，不把链接自动当作研究证据。"""
    raw = html.unescape(html.unescape(s or ''))  # 部分 RSS 把查询参数二次转义为 &amp;amp;
    found = re.findall(r'''(?i)href\s*=\s*["'](https?://[^"'<>]+)''', raw)
    found.extend(re.findall(r'''(?i)\bhttps?://[^\s<>"']+''', raw))
    out = []
    for url in found:
        url = url.rstrip('.,;:!?)]}\'"')
        try:
            p = urllib.parse.urlsplit(url)
        except Exception:
            continue
        if p.scheme not in ('http', 'https') or not p.hostname or p.username is not None or p.password is not None:
            continue
        if url not in out:
            out.append(url)
        if len(out) >= limit:
            break
    return out


def likely_reference_url(url):
    """轻量标记疑似原始引用；只能帮助排序，不能自动把链接升级成证据。"""
    try:
        p = urllib.parse.urlsplit(url)
    except Exception:
        return False
    host = (p.hostname or '').lower()
    path = p.path.lower()
    return (host in REFERENCE_HOSTS or host.endswith('.cochranelibrary.com')
            or '/doi/' in path or path.startswith('/doi/'))


def _host(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or '').lower()
    except Exception:
        return ''


def enrich_reference_urls(source, entry):
    """对可信专家 feed 跟随至多一个配置过的官方详情页，提取疑似原始依据。

    这是审核辅助，不是证据升级：页面链接仍要人工 / AI 判断是否真能支撑说法。
    """
    context_urls = entry.get('citation_urls', []) or []
    citations = [url for url in context_urls if likely_reference_url(url)]
    allowed_hosts = {host.lower() for host in (source.get('reference_page_hosts') or [])
                     if isinstance(host, str) and host.strip()}
    if not allowed_hosts:
        return '', citations[:20], ''
    detail_url = ''
    for url in [entry.get('url', '')] + context_urls:
        try:
            path = urllib.parse.urlsplit(url).path.strip('/').lower()
        except Exception:
            continue
        if _host(url) in allowed_hosts and len(path) >= 2 and not path.startswith(
                ('newsletter', 'subscribe', 'terms-of-use', 'members')
        ):
            detail_url = url
            break
    if not detail_url:
        return '', citations[:20], ''
    try:
        raw = fetch(detail_url, attempts=1, timeout=12, allowed_final_hosts=allowed_hosts)
        page_links = extract_urls(raw.decode('utf-8', 'ignore'), limit=200)
    except Exception as ex:
        return detail_url, citations[:20], str(ex)
    for url in page_links:
        if likely_reference_url(url) and url not in citations:
            citations.append(url)
    return detail_url, citations[:20], ''


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
        pass
    m = re.search(r'(\d{4})', s)  # 退而求其次：抓 4 位年份；抓不到就空（不吐 "Winter 202" 这种垃圾）
    return f"{m.group(1)}-01-01" if m else ''


def mon(m):
    m = (m or '').strip()
    if m[:3].lower() in MON:
        return MON[m[:3].lower()]
    return m.zfill(2) if m.isdigit() else '01'


def parse_feed(raw):
    out = []
    root = safe_fromstring(raw)
    entries = root.findall(f'.//{ATOM}entry')
    if entries:
        for e in entries:
            links = e.findall(f'{ATOM}link')
            href = next((l.get('href', '') for l in links if l.get('rel', 'alternate') == 'alternate'), '')
            if not href and links:
                href = links[0].get('href', '')
            mg = e.find(f'{MEDIA}group')
            desc = t(mg.find(f'{MEDIA}description')) if mg is not None else ''
            if not desc:
                desc = t(e.find(f'{ATOM}summary')) or t(e.find(f'{ATOM}content'))
            out.append({'title': t(e.find(f'{ATOM}title')),
                        'url': href,
                        'published': norm_date(t(e.find(f'{ATOM}published')) or t(e.find(f'{ATOM}updated'))),
                        'desc': clean_text(desc), 'citation_urls': extract_urls(desc)})
    else:
        for it in root.findall('.//item'):
            body = t(it.find(CONTENT)) or t(it.find('description'))
            out.append({'title': t(it.find('title')), 'url': t(it.find('link')),
                        'published': norm_date(t(it.find('pubDate'))), 'desc': clean_text(body),
                        'citation_urls': extract_urls(body)})
    return out


def fetch_pubmed(query, n=PER_SOURCE):
    """PubMed：按主题找最新论文，抓免费摘要。返回 [{title,url,published,desc,journal}]"""
    es = (f"{EUTILS}/esearch.fcgi?db=pubmed&retmode=json&sort=date&retmax={n}"
          f"&tool=health-hot&email=liuyuxin01210725-debug@users.noreply.github.com&term=" + urllib.parse.quote(query))
    ids = [i for i in json.loads(fetch(es).decode()).get('esearchresult', {}).get('idlist', [])
           if isinstance(i, str) and i.isascii() and i.isdigit()]  # ASCII 数字才收（全角数字 isdigit 也为真）
    if not ids:
        return []
    ef = (f"{EUTILS}/efetch.fcgi?db=pubmed&retmode=xml&rettype=abstract"
          f"&tool=health-hot&email=liuyuxin01210725-debug@users.noreply.github.com&id=" + ",".join(ids))
    root = safe_fromstring(fetch(ef))
    out = []
    for art in root.findall('.//PubmedArticle'):
        pmid = art.findtext('.//MedlineCitation/PMID') or ''
        if not (pmid.isascii() and pmid.isdigit()):  # 只接受 ASCII 数字 PMID，再拼进 URL
            continue
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
        if not abstract:  # 无摘要的（如部分 book/无 abstract 文章）跳过，不产空卡
            continue
        journal = a.findtext('.//Journal/Title') or ''
        pd = a.find('.//Journal/JournalIssue/PubDate')
        published = ''
        if pd is not None:
            y = pd.findtext('Year')
            if y:
                published = f"{y}-{mon(pd.findtext('Month'))}-01"
            else:
                md = pd.findtext('MedlineDate') or ''
                mm = re.search(r'\d{4}', md)
                published = (mm.group(0) + "-01-01") if mm else ''
        # 证据级按 PublicationType 结果级判定（不靠 query 的 [pt]）
        pts = [(pt.text or '').lower() for pt in a.findall('.//PublicationType')]
        if any('randomized controlled trial' in p for p in pts):
            ev = 'rct'
        elif any(('meta-analysis' in p or 'systematic review' in p) for p in pts):
            ev = 'meta'
        elif any('guideline' in p for p in pts):
            ev = 'guideline'
        elif any(('observational' in p or 'cohort' in p or 'case-control' in p
                  or 'cross-sectional' in p or 'comparative study' in p) for p in pts):
            ev = 'observational'
        else:
            ev = 'unknown'  # 无法从 PublicationType 判定的，标 unknown 待人工定级（不默认塞成 observational，codex 审出）
        doi = ''
        for el in a.findall('.//ELocationID'):
            if el.get('EIdType') == 'doi' and el.text:
                doi = el.text.strip().lower(); break
        out.append({'title': title, 'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    'published': published, 'desc': abstract, 'journal': journal,
                    'evidence': ev, 'doi': doi})
    return out


def norm_title(s):
    return re.sub(r'\W+', '', (s or '').lower())


def canonical_id(entry, group=''):
    """跨次采集去重键：优先 PMID / DOI；节目 feed 用 group+标题。
    候选转正式条目时保留 canonical_id，下一轮才能识别 YouTube/RSS 的同一期节目。"""
    url = entry.get('url', '') or ''
    m = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', url)
    if m:
        return 'pmid:' + m.group(1)
    if entry.get('doi'):
        return 'doi:' + entry['doi'].strip().lower()
    title = norm_title(entry.get('title', ''))
    return f'group:{group}:{title}' if group and title else ''


def relevance_hint(source, entry):
    """窄主题雷达的轻量相关性提示：不武断过滤，只提醒人工/AI 优先复核标题未命中的候选。"""
    terms = source.get('title_terms') or []
    if not isinstance(terms, list) or not terms:
        return 'not_configured'
    title = (entry.get('title') or '').lower()
    return 'title_match' if any(isinstance(term, str) and term.lower() in title for term in terms) else 'query_match_only'


def official_catalog_entries(source):
    """官方精选目录：只接收白名单官方域名下的具体页面。

    目录是编辑层的常青问题池，不自动把网页内容发布为结论。它进入审核收件箱后仍要人工/AI
    摘要并写入 data/items/*.json，再走 build.py 发布闸门。
    """
    if source.get('role') != 'anchor':
        raise ValueError("official_catalog 的 role 必须为 anchor")
    entries = source.get('entries')
    if not isinstance(entries, list) or not entries:
        raise ValueError("official_catalog 缺 entries 数组")
    out = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"official_catalog 第 {index} 项不是对象")
        url = entry.get('url', '')
        try:
            p = urllib.parse.urlsplit(url)
        except Exception as ex:
            raise ValueError(f"official_catalog 第 {index} 项 URL 非法：{url!r}") from ex
        host = (p.hostname or '').lower()
        if (p.scheme != 'https' or host not in OFFICIAL_HOSTS or p.username is not None
                or p.password is not None or len(p.path.strip('/')) < 2):
            raise ValueError(f"official_catalog 第 {index} 项不是白名单官方具体页面：{url!r}")
        title = entry.get('title', '')
        desc = entry.get('desc', '')
        if not isinstance(title, str) or not title.strip():
            raise ValueError(f"official_catalog 第 {index} 项缺 title")
        if not isinstance(desc, str) or not desc.strip():
            raise ValueError(f"official_catalog 第 {index} 项缺 desc")
        out.append({'title': title.strip(), 'url': url, 'published': entry.get('published', ''),
                    'desc': desc.strip(), 'category': entry.get('category', source.get('category', '')),
                    'evidence': 'guideline'})
    return out


def seen_records():
    urls, keys = set(), set()
    for f in glob.glob(os.path.join(ITEMS, '*.json')):
        try:
            item = json.load(open(f, encoding='utf-8'))
            urls.add(item.get('source_url', ''))
            if item.get('canonical_id'):
                keys.add(item['canonical_id'])
        except Exception:
            pass
    return urls, keys


def select_sources(sources, args):
    """默认跑权威层与可信专家发现层；--include-discovery 再加入实验型雷达。"""
    include_discovery = '--include-discovery' in args
    filt = [x.lower() for x in args if x != '--include-discovery']
    if filt:
        return [s for s in sources if isinstance(s, dict)
                and any(f in s.get('name', '').lower() for f in filt)]
    if include_discovery:
        return [s for s in sources if isinstance(s, dict)]
    return [s for s in sources if isinstance(s, dict) and s.get('default_enabled', True) is not False]


def failure_is_warning(source):
    """发现层波动不应阻断权威主流程；anchor 失败始终阻断，配置不能绕过。"""
    return (source.get('failure_policy') == 'warn'
            and source.get('role') in {'discovery', 'radar'})


def main():
    try:
        cfg = json.load(open(SRC, encoding='utf-8'))
        sources = cfg.get('sources', [])
        if not isinstance(sources, list):
            raise ValueError("sources 不是数组")
    except Exception as ex:
        print(f"[!] 读取 sources.json 失败：{ex}")
        sys.exit(1)  # 配置坏 → 退出码 1，让自动化能察觉失败（此前 return=退出码0，会被误判成功，codex 审出）
    sources = select_sources(sources, sys.argv[1:])
    if not sources:
        print("[!] 没有匹配的信源，请检查筛选参数或 sources.json")
        sys.exit(1)
    seen, seen_canonical = seen_records()
    seen_doi, seen_title = set(), set()
    cands, succeeded, failed, warnings, failures = [], 0, 0, 0, []
    for s in sources:
        name = s.get('name', '<未命名>') if isinstance(s, dict) else '<非对象>'
        try:
            if not isinstance(s, dict) or 'type' not in s:
                raise ValueError("source 缺 type 字段")
            if s['type'] == 'pubmed':
                entries = fetch_pubmed(s['query'])
            elif s['type'] == 'official_catalog':
                entries = official_catalog_entries(s)
            elif s['type'] in ('youtube', 'rss'):
                url = (f"https://www.youtube.com/feeds/videos.xml?channel_id={s['channel_id']}"
                       if s['type'] == 'youtube' else s['url'])
                entries = parse_feed(fetch(url, attempts=1, timeout=12) if failure_is_warning(s) else fetch(url))
            else:
                raise ValueError(f"不支持的 source type：{s['type']!r}")
        except Exception as ex:
            optional = failure_is_warning(s)
            prefix = "[~]" if optional else "[!]"
            print(f"{prefix} {name}: 失败 — {ex}" + ("（发现层告警，不阻断主流程）" if optional else ""))
            failures.append({'source': name, 'role': s.get('role', ''), 'optional': optional, 'error': str(ex)})
            if optional:
                warnings += 1
            else:
                failed += 1
            continue
        succeeded += 1
        new = 0
        group = s.get('group', '')
        limit = s.get('limit', PER_SOURCE)
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 30):
            print(f"[!] {name}: 失败 — limit 必须为 1–30 的整数")
            failed += 1
            continue
        for e in entries[:limit]:
            url = e.get('url', '')
            if not url or not re.match(r'^https?://', url) or url in seen:  # 采集层即拒非 http(s) 链接
                continue
            doi = e.get('doi', '')
            if doi and doi in seen_doi:          # 跨源同一篇论文（DOI）只收一次
                continue
            cid = canonical_id(e, group)
            if cid and cid in seen_canonical:    # 跨次采集：候选提升为正式条目后仍能去重
                continue
            tkey = (group, norm_title(e.get('title', ''))) if group else None
            if tkey and tkey in seen_title:      # 同节目 YouTube+Podcast 同一期只收一次
                continue
            src = (e['journal'] + " · PubMed") if e.get('journal') else name
            rel = relevance_hint(s, e)
            detail_url, citation_urls, enrichment_error = enrich_reference_urls(s, e)
            cands.append({'source': src, 'category': e.get('category') or s.get('category', ''),
                          'role': s.get('role', ''),
                          'evidence': e.get('evidence') or s.get('evidence', 'expert'),
                          'title': e['title'], 'source_url': url,
                          'published': e['published'], 'desc': e['desc'][:DESC_CHARS],
                          'doi': doi, 'canonical_id': cid,
                          'collection_source': name, 'collection_query': s.get('query', ''),
                          'authority_level': s.get('authority_level', ''),
                          'discovery_tier': s.get('discovery_tier', ''),
                          'context_urls_to_review': [x for x in e.get('citation_urls', []) if x != url][:20],
                          'reference_page_url': detail_url,
                          'citation_urls_to_review': [x for x in citation_urls if x != url][:20],
                          'reference_enrichment_error': enrichment_error,
                          'relevance_hint': rel})
            seen.add(url)
            if doi:
                seen_doi.add(doi)
            if tkey:
                seen_title.add(tkey)
            if cid:
                seen_canonical.add(cid)
            new += 1
        print(f"[✓] {name}（{s.get('role', '?')}）: 共 {len(entries)} 条，新增候选 {new} 条")
    if not succeeded:
        print("\n⛔ 全部选中信源采集失败：未覆盖旧候选文件。")
        sys.exit(1)
    json.dump(cands, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump({'failures': failures}, open(META_OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"\n共 {len(cands)} 条候选 → {OUT}")
    for c in cands:
        flag = " · ⚠ 标题未命中窄主题，需人工判断" if c.get('relevance_hint') == 'query_match_only' else ""
        print(f"  · [{c['source'][:28]} | {c['published']}] {c['title'][:42]}  （{len(c['desc'])}字）{flag}")
    if failed:
        print(f"\n⛔ 有 {failed} 个信源采集失败：候选已保留，但退出码为 1，请检查后再进入发布流程。")
        sys.exit(1)
    if warnings:
        print(f"\n⚠ 有 {warnings} 个发现层信源临时失败：已记录告警，官方 / PubMed 主流程继续。")


if __name__ == '__main__':
    main()
