#!/usr/bin/env python3
"""记录一条上线前强审结论到 data/review_audit.json。

由 /health-review 流程在每条强审结束后调用。content_sha 在记录时
按【当前磁盘上的文件内容】实时计算，确保审计记录与实际上线内容绑定。

用法：
  python3 scripts/record_review.py <slug> <PASS|FIX|BLOCK> "审查笔记/依据" [checksJSON]
  checksJSON 可选，形如 '{"pmid_real":true,"conclusion_subset":true,...}'
"""
import json, os, sys, hashlib, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS_DIR = os.path.join(ROOT, "data", "items")
AUDIT_PATH = os.path.join(ROOT, "data", "review_audit.json")
GRANDFATHER_PATH = os.path.join(ROOT, "data", "strong_review_grandfather.json")


def find_item(slug):
    for f in os.listdir(ITEMS_DIR):
        if not f.endswith(".json"):
            continue
        p = os.path.join(ITEMS_DIR, f)
        try:
            if json.load(open(p, encoding="utf-8")).get("slug") == slug:
                return p
        except Exception:
            pass
    return None


def main(argv):
    if len(argv) < 3:
        print("用法: record_review.py <slug> <PASS|FIX|BLOCK> \"笔记\" [checksJSON]")
        return 2
    slug, verdict, notes = argv[0], argv[1].upper(), argv[2]
    checks = json.loads(argv[3]) if len(argv) > 3 and argv[3].strip() else {}
    if verdict not in ("PASS", "FIX", "BLOCK"):
        print("verdict 必须是 PASS / FIX / BLOCK")
        return 2

    path = find_item(slug)
    if not path:
        print(f"找不到 slug={slug} 的条目文件")
        return 1
    with open(path, "rb") as f:
        content_sha = hashlib.sha256(f.read()).hexdigest()

    audit = {}
    if os.path.exists(AUDIT_PATH):
        with open(AUDIT_PATH, encoding="utf-8") as f:
            audit = json.load(f)
    audit[slug] = {
        "verdict": verdict,
        "content_sha": content_sha,
        "reviewed_at": datetime.date.today().isoformat(),
        "checks": checks,
        "notes": notes,
    }
    with open(AUDIT_PATH, "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)

    # 条目一旦进入强审账本（任何 verdict），就从 grandfather 固化清单移除：
    # 此后它由 review_audit 权威判定，grandfather 只保留「从未强审过的存量」，
    # 于是 len(grandfather) 就是真实的待强审欠债数，会随强审推进真正瘦身。
    if os.path.exists(GRANDFATHER_PATH):
        try:
            with open(GRANDFATHER_PATH, encoding="utf-8") as f:
                gf = json.load(f)
        except Exception:
            gf = None
        if isinstance(gf, dict) and slug in gf:
            gf.pop(slug, None)
            with open(GRANDFATHER_PATH, "w", encoding="utf-8") as f:
                json.dump(gf, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
            print(f"  · 已从 grandfather 移除 {slug}（剩余固化 {len(gf)} 条）")

    mark = {"PASS": "✓", "FIX": "✎", "BLOCK": "✗"}[verdict]
    print(f"{mark} 记录强审: {slug} → {verdict}  (sha {content_sha[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
