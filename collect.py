#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集引擎 v1：从 data/sources.json 抓 RSS / YouTube 频道，去重，产出"候选条目"。

候选写到 /tmp/health_candidates.json —— 由 Claude 按健康库 7 铁律
（证据分级 / 引用追溯 / 不给剂量 / 医疗免责 / 不暗示治疗 / 标不确定）
摘要成 data/items/*.json，再跑 build.py 上站。

纯标准库，无第三方依赖。
用法：
    python3 collect.py                # 抓全部信源
    python3 collect.py FoundMyFitness Attia   # 只抓名字匹配的
"""
import json, os, sys, glob, re, urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "data", "sources.json")
ITEMS = os.path.join(ROOT, "data", "items")
OUT = "/tmp/health_candidates.json"
UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'}
PER_SOURCE = 5  # 每个源最多取最新几条

ATOM = '{http://www.w3.org/2005/Atom}'
MEDIA = '{http://search.yahoo.com/mrss/}'


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=20).read()


def t(el):
    return (el.text or '').strip() if el is not None else ''


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


def parse_feed(raw):
    """兼容 Atom（YouTube）和 RSS 2.0（播客/期刊），返回 [{title,url,published,desc}]"""
    out = []
    root = ET.fromstring(raw)
    entries = root.findall(f'.//{ATOM}entry')
    if entries:  # Atom
        for e in entries:
            link_el = e.find(f'{ATOM}link')
            mg = e.find(f'{MEDIA}group')
            out.append({
                'title': t(e.find(f'{ATOM}title')),
                'url': link_el.get('href', '') if link_el is not None else '',
                'published': norm_date(t(e.find(f'{ATOM}published')) or t(e.find(f'{ATOM}updated'))),
                'desc': t(mg.find(f'{MEDIA}description')) if mg is not None else '',
            })
    else:  # RSS 2.0
        for it in root.findall('.//item'):
            out.append({
                'title': t(it.find('title')),
                'url': t(it.find('link')),
                'published': norm_date(t(it.find('pubDate'))),
                'desc': t(it.find('description')),
            })
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
    filt = [a.lower() for a in sys.argv[1:]]
    sources = json.load(open(SRC, encoding='utf-8'))['sources']
    if filt:
        sources = [s for s in sources if any(f in s['name'].lower() for f in filt)]
    seen = seen_urls()
    cands = []
    for s in sources:
        url = (f"https://www.youtube.com/feeds/videos.xml?channel_id={s['channel_id']}"
               if s['type'] == 'youtube' else s['url'])
        try:
            entries = parse_feed(fetch(url))
        except Exception as ex:
            print(f"[!] {s['name']}: 抓取/解析失败 — {ex}")
            continue
        new = 0
        for e in entries[:PER_SOURCE]:
            if not e['url'] or e['url'] in seen:
                continue
            cands.append({
                'source': s['name'], 'category': s.get('category', ''),
                'evidence': s.get('evidence', 'expert'),
                'title': e['title'], 'source_url': e['url'],
                'published': e['published'], 'desc': e['desc'][:600],
            })
            seen.add(e['url'])
            new += 1
        print(f"[✓] {s['name']}: 共 {len(entries)} 条，新增候选 {new} 条")
    json.dump(cands, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"\n共 {len(cands)} 条候选 → {OUT}")
    for c in cands[:15]:
        print(f"  · [{c['source']} | {c['published']}] {c['title'][:48]}")


if __name__ == '__main__':
    main()
