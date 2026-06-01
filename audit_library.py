#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit the published library without changing or publishing content."""
import argparse
import concurrent.futures
import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

import build


ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = "/tmp/health_library_audit.json"
DEFAULT_REPORT = "/tmp/health_library_audit_report.md"
DEFAULT_STALE_DAYS = 180
UA = {"User-Agent": "health-hot-library-audit/1.0 (+https://github.com/liuyuxin01210725-debug/health-hot)"}
RESTRICTED_CODES = {401, 403, 412, 429, 445}
BROKEN_CODES = {404, 410}


def _date(value):
    try:
        return datetime.date.fromisoformat(value)
    except Exception:
        return None


def _host(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def _official(url):
    return _host(url) in build._GUIDELINE_HOSTS


def _item_urls(item):
    urls = [item.get("source_url", "")]
    urls.extend(item.get("evidence_source_urls") or [])
    if item.get("discovery_source_url"):
        urls.append(item["discovery_source_url"])
    return sorted({url for url in urls if isinstance(url, str) and url})


def check_url(url, timeout=12):
    """Read a small prefix. Restricted and transient responses are warnings, not proof of a dead source."""
    request = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(256)
            return {"url": url, "status": "ok", "http_status": response.status, "detail": ""}
    except urllib.error.HTTPError as ex:
        if ex.code in RESTRICTED_CODES:
            status = "restricted"
        elif ex.code in BROKEN_CODES:
            status = "broken"
        else:
            status = "error"
        return {"url": url, "status": status, "http_status": ex.code, "detail": str(ex.reason)}
    except Exception as ex:
        return {"url": url, "status": "error", "http_status": None, "detail": str(ex)}


def check_urls(urls, max_workers=6):
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        return sorted(pool.map(check_url, urls), key=lambda row: row["url"])


def audit_items(items, today=None, stale_days=DEFAULT_STALE_DAYS, link_results=None):
    today = today or datetime.date.today()
    good, blocked = build.validate(items)
    pending = [item for item in good if build.verification_status(item) == "curated_pending_evidence"]
    stale = []
    for item in good:
        reviewed = _date(item.get("reviewed_at"))
        if reviewed and (today - reviewed).days > stale_days:
            stale.append({
                "slug": item["slug"],
                "title": item["title"],
                "reviewed_at": item["reviewed_at"],
                "days_since_review": (today - reviewed).days,
            })
    urls = sorted({url for item in good for url in _item_urls(item)})
    hosts = Counter(_host(url) for url in urls if _host(url))
    official_items = [item for item in good if any(_official(url) for url in _item_urls(item))]
    links = link_results or []
    link_counts = Counter(row["status"] for row in links)
    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "stale_after_days": stale_days,
        "counts": {
            "items": len(good),
            "verified": len(good) - len(pending),
            "pending_evidence": len(pending),
            "official_source_items": len(official_items),
            "unique_urls": len(urls),
            "review_due": len(stale),
            "blocked": len(blocked),
            "links_checked": len(links),
            "links_ok": link_counts["ok"],
            "links_restricted": link_counts["restricted"],
            "links_broken": link_counts["broken"],
            "links_error": link_counts["error"],
        },
        "pending_evidence": [{"slug": item["slug"], "title": item["title"]} for item in pending],
        "review_due": sorted(stale, key=lambda row: row["days_since_review"], reverse=True),
        "blocked": [{"file": name, "errors": errors} for name, errors in blocked],
        "source_hosts": [{"host": host, "urls": count} for host, count in hosts.most_common()],
        "urls": urls,
        "links": links,
    }


def _append_rows(lines, rows, formatter, empty="无。", limit=20):
    if not rows:
        lines.append(empty)
        return
    for row in rows[:limit]:
        lines.append(formatter(row))
    if len(rows) > limit:
        lines.append(f"- 其余 {len(rows) - limit} 项见 Artifact 内的 `health_library_audit.json`。")


def markdown_report(audit):
    counts = audit["counts"]
    lines = [
        "",
        "## E. 已发布馆藏健康审计",
        "",
        f"- 正式条目：**{counts['items']} 条** · 已核验：**{counts['verified']} 条** · 专家梳理待补证据：**{counts['pending_evidence']} 条**",
        f"- 含官方机构来源：**{counts['official_source_items']} 条** · 唯一来源链接：**{counts['unique_urls']} 个**",
        f"- 超过 {audit['stale_after_days']} 天未复核：**{counts['review_due']} 条** · 发布闸门异常：**{counts['blocked']} 条**",
    ]
    if counts["links_checked"]:
        lines.append(
            f"- 链接巡检：**{counts['links_checked']} 个** · 可达 {counts['links_ok']} · "
            f"受限 {counts['links_restricted']} · 疑似失效 {counts['links_broken']} · 临时错误 {counts['links_error']}"
        )
    lines.extend([
        "",
        "> 这是已发布内容的维护提醒。链接受限或临时错误不等于原文失效；疑似失效、长期未复核和证据待补条目需要人工确认，不会自动改写或自动发布。",
        "",
        "### E1. 复核到期提醒",
        "",
    ])
    _append_rows(
        lines,
        audit["review_due"],
        lambda row: f"- **{row['title']}** · `{row['reviewed_at']}` · 已 {row['days_since_review']} 天 · `{row['slug']}`",
    )
    lines.extend(["", "### E2. 疑似失效或暂时不可达链接", ""])
    problem_links = [row for row in audit["links"] if row["status"] in {"broken", "error"}]
    _append_rows(
        lines,
        problem_links,
        lambda row: f"- `{row['status']}` · `{row.get('http_status') or '-'}` · {row['url']} · {row.get('detail') or '-'}",
    )
    lines.extend(["", "### E3. 专家梳理 · 证据待补", ""])
    _append_rows(
        lines,
        audit["pending_evidence"],
        lambda row: f"- **{row['title']}** · `{row['slug']}`",
    )
    lines.extend(["", "### E4. 来源域名摘要", ""])
    _append_rows(
        lines,
        audit["source_hosts"],
        lambda row: f"- `{row['host']}` · {row['urls']} 个唯一链接",
        limit=30,
    )
    if audit["blocked"]:
        lines.extend(["", "### E5. 发布闸门异常", ""])
        _append_rows(
            lines,
            audit["blocked"],
            lambda row: f"- `{row['file']}` · {'；'.join(row['errors'])}",
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-links", action="store_true", help="Check published source URL reachability.")
    parser.add_argument("--max-workers", type=int, default=6)
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args()
    if args.max_workers < 1 or args.max_workers > 12:
        parser.error("--max-workers must be between 1 and 12")
    if args.stale_days < 1:
        parser.error("--stale-days must be positive")
    items, load_errors = build.load_items()
    urls = sorted({url for item in items for url in _item_urls(item)})
    links = check_urls(urls, args.max_workers) if args.check_links else []
    audit = audit_items(items, stale_days=args.stale_days, link_results=links)
    if load_errors:
        audit["counts"]["blocked"] += load_errors
        audit["load_errors"] = load_errors
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(audit, fh, ensure_ascii=False, indent=2)
    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write(markdown_report(audit))
    counts = audit["counts"]
    print(
        f"✓ 馆藏审计：{counts['items']} 条 · 已核验 {counts['verified']} · 待补证据 {counts['pending_evidence']} · "
        f"复核到期 {counts['review_due']} · 发布闸门异常 {counts['blocked']}"
    )
    if args.check_links:
        print(
            f"✓ 链接巡检：{counts['links_checked']} 个 · 可达 {counts['links_ok']} · "
            f"受限 {counts['links_restricted']} · 疑似失效 {counts['links_broken']} · 临时错误 {counts['links_error']}"
        )
    if counts["blocked"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
