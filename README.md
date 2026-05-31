# 查过再信 · 健康资讯流

一个持续收集、查证的健康信息流。每条结论都标注来源、证据强度，附可点击原文。
把"听来的"和"有据的"分开。

## 结构

- `data/sources.json` — 信源清单（RSS / YouTube 频道 / PubMed 主题）
- `data/items/*.json` — 收集到的条目（每条 = 一张卡片 / 一条核验）
- `collect.py` — 从信源抓取候选、去重（纯标准库）
- `build.py` — 生成静态站到 `docs/`（精选 + 全部 + 关于 + 各条详情页；纯标准库）
- 部署：GitHub Pages 从 `main` 分支 `/docs` 目录 serve，推送即更新（当前未用 GitHub Actions；如需每周自动化再加 workflow，需 `workflow` 授权）

## 本地预览

```bash
python3 build.py
python3 -m http.server 8000 --directory docs
# 浏览器打开 http://localhost:8000
```

## 免责

本站为科普整理，**非医疗建议**；每条结论标注证据等级，点击可回原文核对。
具体执行请咨询持证医生或注册营养师。
