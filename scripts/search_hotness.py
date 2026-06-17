#!/usr/bin/env python3
"""读回站内搜索打点统计（Worker 的 GET /event/stats），看用户在站内搜什么、命中/未命中。

纯读、可选运行。是"精选热点度"打分的数据源（下一步用）；可 --write 落到 data/search_hotness.json。

用法：
  EVENT_STATS_TOKEN=xxx python3 scripts/search_hotness.py            # 打印 top 搜索词
  EVENT_STATS_TOKEN=xxx python3 scripts/search_hotness.py --write    # 同时写 data/search_hotness.json
  # 端点默认 https://health-hot-submit.pages.dev/event/stats；可用 HEALTH_HOT_EVENT_ENDPOINT 覆盖
  #   （脚本会把结尾的 /event 自动换成 /event/stats）

隐私：只读聚合的"搜索词 + 命中/未命中计数 + 末次日期"，不含 IP / 用户 / 单条历史。
注意：本机沙箱常走代理、可达性不可信——拿不到数据时请在站长真实环境跑。
"""
import json
import os
import sys
import urllib.parse
import urllib.request

DEFAULT_EVENT = "https://health-hot-submit.pages.dev/event"


def stats_url():
    base = os.environ.get("HEALTH_HOT_EVENT_ENDPOINT", DEFAULT_EVENT).strip().rstrip("/")
    if base.endswith("/event"):
        return base + "/stats"
    if base.endswith("/event/stats"):
        return base
    return base + "/event/stats"


def main():
    token = os.environ.get("EVENT_STATS_TOKEN", "").strip()
    if not token:
        print("缺 EVENT_STATS_TOKEN 环境变量（与 Worker 上设的同一个）。", file=sys.stderr)
        return 2
    url = stats_url() + "?" + urllib.parse.urlencode({"token": token, "limit": "500"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "health-hot-search-hotness/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:  # noqa: BLE001 — 读失败如实报，不静默
        print(f"读取失败：{ex}\n（沙箱走代理、可达性不可信，建议在站长真实环境运行）", file=sys.stderr)
        return 1

    terms = data.get("terms", [])
    print(f"搜索词条目：{data.get('count', len(terms))}（显示 {len(terms)} 条，按总次数降序）")
    print(f"{'命中':>6}{'未命中':>7}{'末次':>13}  词")
    for t in terms:
        print(f"{t.get('h', 0):>6}{t.get('m', 0):>7}{t.get('ts', ''):>13}  {t.get('term', '')}")

    if "--write" in sys.argv:
        out = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "search_hotness.json"
        )
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"terms": terms}, fh, ensure_ascii=False, indent=2)
        print(f"已写 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
