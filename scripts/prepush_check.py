#!/usr/bin/env python3
"""上线前强审·机械闸门 (prepush gate)

规则：任何【改动过的】条目 (data/items/*.json)，在推送上线前，
必须在 data/review_audit.json 里有一条 verdict=="PASS"、且 content_sha 与
当前文件内容完全一致 的复审记录。否则本脚本退出码 !=0，阻断 git push。

为什么要内容哈希：复审通过后又改了正文 → 哈希变 → 记录作废 → 必须重审。
这样"审过"不是靠记忆，而是可机械验证的事实。

用法：
  python3 scripts/prepush_check.py            # 自动检测改动条目并校验
  python3 scripts/prepush_check.py --all       # 校验全部条目（全库审计时用）
  python3 scripts/prepush_check.py f1.json ... # 只校验指定文件

由 .git/hooks/pre-push 调用；也可手动跑。
退出码 0 = 放行；1 = 阻断（有条目未通过强审）。
"""
import json, os, sys, subprocess, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ITEMS_DIR = os.path.join(ROOT, "data", "items")
AUDIT_PATH = os.path.join(ROOT, "data", "review_audit.json")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_audit():
    if not os.path.exists(AUDIT_PATH):
        return {}
    try:
        return json.load(open(AUDIT_PATH, encoding="utf-8"))
    except Exception as e:
        print(f"  ✗ review_audit.json 无法解析：{e}")
        return None


def slug_of(path):
    try:
        return json.load(open(path, encoding="utf-8")).get("slug", "")
    except Exception:
        return ""


def git(*args):
    try:
        out = subprocess.run(["git", "-C", ROOT, *args],
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except Exception:
        return ""


def changed_item_files():
    """改动条目 = 相对 origin/main 的提交差异 ∪ 工作区未提交改动 ∪ 暂存区。"""
    rels = set()
    for diff_args in (
        ["diff", "--name-only", "origin/main...HEAD", "--", "data/items"],
        ["diff", "--name-only", "--", "data/items"],
        ["diff", "--name-only", "--cached", "--", "data/items"],
        ["ls-files", "--others", "--exclude-standard", "--", "data/items"],
    ):
        for line in git(*diff_args).splitlines():
            line = line.strip()
            if line.endswith(".json"):
                rels.add(line)
    return [os.path.join(ROOT, r) for r in sorted(rels) if os.path.exists(os.path.join(ROOT, r))]


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    flags = {a for a in argv if a.startswith("--")}

    if args:
        files = [a if os.path.isabs(a) else os.path.join(ROOT, a) for a in args]
    elif "--all" in flags:
        files = [os.path.join(ITEMS_DIR, f) for f in os.listdir(ITEMS_DIR) if f.endswith(".json")]
    else:
        files = changed_item_files()

    if not files:
        print("✓ 强审闸门：无改动条目，放行。")
        return 0

    audit = load_audit()
    if audit is None:
        print("✗ 强审闸门：review_audit.json 损坏，阻断。先修复审计文件。")
        return 1

    failures = []
    for path in files:
        name = os.path.basename(path)
        slug = slug_of(path)
        rec = audit.get(slug)
        if not rec:
            failures.append((name, "无复审记录"))
        elif rec.get("verdict") != "PASS":
            failures.append((name, f"复审判定={rec.get('verdict')}（非 PASS）"))
        elif rec.get("content_sha") != sha(path):
            failures.append((name, "复审后内容已变更（哈希不符），需重审"))

    total = len(files)
    if failures:
        print(f"✗ 强审闸门：{total} 个改动条目中 {len(failures)} 个未过强审，阻断 push：")
        for name, why in failures:
            print(f"    · {name} — {why}")
        print("  → 运行 /health-review 对这些条目强审通过后再推。")
        return 1

    print(f"✓ 强审闸门：{total} 个改动条目全部通过强审，放行。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
