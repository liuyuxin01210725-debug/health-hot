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
