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
    with urllib.request.urlopen(req, timeout=25) as r:
        # 跟随重定向后，确认最终 URL 仍是 http(s)——挡 file:// 等伪协议跳转（SSRF 纵深防御，codex 审出）。
        # 注：内网 IP（169.254/localhost）重定向不在此简易防护内；本地手动采集已知信源，风险极低。
        final = r.geturl()
        if not isinstance(final, str) or not re.match(r'^https?://', final, re.I):
            raise ValueError(f"最终 URL 非 http(s)，已拒绝（防 SSRF）：{final!r}")
        return r.read(8 * 1024 * 1024)  # 8MB 上限，防超大 feed 撑爆内存


def safe_fromstring(raw):
    """解析不可信 XML：拒绝含 DOCTYPE / ENTITY 的文档——挡 billion-laughs 实体膨胀与 XXE。
    必须全量扫描：只扫前 N 字节会被「长前导注释把 DOCTYPE 推到后面」绕过（codex 审出的 bypass）。
    expat 默认不取外部实体，但内部实体膨胀仍能拖垮 CPU/内存。纯标准库零依赖。"""
    if isinstance(raw, (bytes, bytearray)):
        low = raw.replace(b'\x00', b'').lower()  # 去 NUL：连 UTF-16/32 编码的 <!DOCTYPE 也能识别（codex 审出的编码绕过）
        if b'<!doctype' in low or b'<!entity' in low:
            raise ValueError("XML 含 DOCTYPE/ENTITY，已拒绝（防实体膨胀/XXE）")
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
          f"&tool=health-hot&email=liuyuxin01210725-debug@users.noreply.github.com&term=" + urllib.parse.quote(query))
    ids = [i for i in json.loads(fetch(es).decode()).get('esearchresult', {}).get('idlist', [])
           if isinstance(i, str) and i.isascii() and i.isdigit()]  # ASCII 数字才收（全角数字 isdigit 也为真）
    if not ids:
        return []
    time.sleep(0.4)
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
        else:
            ev = 'observational'
        doi = ''
        for el in a.findall('.//ELocationID'):
            if el.get('EIdType') == 'doi' and el.text:
                doi = el.text.strip().lower(); break
        out.append({'title': title, 'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    'published': published, 'desc': abstract, 'journal': journal,
                    'evidence': ev, 'doi': doi})
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
    try:
        cfg = json.load(open(SRC, encoding='utf-8'))
        sources = cfg.get('sources', [])
        if not isinstance(sources, list):
            raise ValueError("sources 不是数组")
    except Exception as ex:
        print(f"[!] 读取 sources.json 失败：{ex}")
        return
    if filt:
        sources = [s for s in sources if isinstance(s, dict) and any(f in s.get('name', '').lower() for f in filt)]
    seen = seen_urls()
    seen_doi, seen_title = set(), set()
    cands = []
    for s in sources:
        name = s.get('name', '<未命名>') if isinstance(s, dict) else '<非对象>'
        try:
            if not isinstance(s, dict) or 'type' not in s:
                raise ValueError("source 缺 type 字段")
            if s['type'] == 'pubmed':
                entries = fetch_pubmed(s['query'])
            else:
                url = (f"https://www.youtube.com/feeds/videos.xml?channel_id={s['channel_id']}"
                       if s['type'] == 'youtube' else s['url'])
                entries = parse_feed(fetch(url))
        except Exception as ex:
            print(f"[!] {name}: 失败 — {ex}")
            continue
        new = 0
        group = s.get('group', '')
        for e in entries[:PER_SOURCE]:
            url = e.get('url', '')
            if not url or not re.match(r'^https?://', url) or url in seen:  # 采集层即拒非 http(s) 链接
                continue
            doi = e.get('doi', '')
            if doi and doi in seen_doi:          # 跨源同一篇论文（DOI）只收一次
                continue
            tkey = (group, re.sub(r'\W+', '', (e.get('title', '') or '').lower())) if group else None
            if tkey and tkey in seen_title:      # 同节目 YouTube+Podcast 同一期只收一次
                continue
            src = (e['journal'] + " · PubMed") if e.get('journal') else name
            cands.append({'source': src, 'category': s.get('category', ''),
                          'role': s.get('role', ''),
                          'evidence': e.get('evidence') or s.get('evidence', 'expert'),
                          'title': e['title'], 'source_url': url,
                          'published': e['published'], 'desc': e['desc'][:DESC_CHARS]})
            seen.add(url)
            if doi:
                seen_doi.add(doi)
            if tkey:
                seen_title.add(tkey)
            new += 1
        print(f"[✓] {name}（{s.get('role', '?')}）: 共 {len(entries)} 条，新增候选 {new} 条")
    json.dump(cands, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"\n共 {len(cands)} 条候选 → {OUT}")
    for c in cands:
        print(f"  · [{c['source'][:28]} | {c['published']}] {c['title'][:42]}  （{len(c['desc'])}字）")


if __name__ == '__main__':
    main()
