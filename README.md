# 查过再信 · 健康说法核验库

一个持续收集、查证的中文循证健康说法核验库。每条说法都查到原始证据、标出强度、写清适用人群，
附可点击原文，并区分「✓ 已核验」（有独立 PubMed/指南/Cochrane 支撑）与「◔ 专家梳理·证据待补」。
把"听来的"和"有据的"分开。

也提供公开机读接口（`docs/claims.json`）和零配置 Skill（`skill/SKILL.md`），可被 AI 助手直接调用。

## 结构

- `data/sources.json` — 信源清单（RSS / YouTube 频道 / PubMed 主题）
- `data/items/*.json` — 收集到的条目（每条 = 一张卡片 / 一条核验）
- `collect.py` — 从信源抓取候选、去重（纯标准库）
- `build.py` — 生成静态站到 `docs/`（精选 + 全部 + 关于 + 各条详情页 + `claims.json` 机读 feed；纯标准库）
- `make_og.py` — 生成社交分享卡 `assets/og.png`（需 Pillow，单独运行，不进构建）
- `skill/SKILL.md` — 公开 health-hot Skill，构建时拷进 `docs/skill/`
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
