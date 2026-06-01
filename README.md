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

## 信任分层

- `verified`：存在独立研究 / 指南锚点，Agent 可以称「已核验」。
- `curated_pending_evidence`：来自专家、播客或媒体梳理，但原始证据链尚未补齐；只能称「专家梳理·证据待补」。
- `evidence_source_urls` 只放研究 / 指南锚点；播客、视频、文章入口放 `discovery_source_url`。
- `source_urls` 仅为 feed 兼容字段，包含全部来源，不能当作研究原文列表。

## 候选采集

```bash
python3 collect.py                 # 抓全部信源
python3 collect.py 'PubMed·肌酸'   # 只抓名字匹配的信源
```

候选写入 `/tmp/health_candidates.json`。PubMed 窄主题雷达会附带 `relevance_hint`：
`title_match` 可优先看，`query_match_only` 表示查询命中但标题未命中主题词，必须人工/AI 再判断。
候选提升为正式条目时应保留 `canonical_id`，用于跨次采集去重。

## Agent 接入

```bash
# Claude Code
mkdir -p ~/.claude/skills/health-hot
curl -fsSL https://liuyuxin01210725-debug.github.io/health-hot/skill/SKILL.md \
  -o ~/.claude/skills/health-hot/SKILL.md

# Codex
mkdir -p ~/.codex/skills/health-hot
curl -fsSL https://liuyuxin01210725-debug.github.io/health-hot/skill/SKILL.md \
  -o ~/.codex/skills/health-hot/SKILL.md
```

## 本地预览

```bash
python3 build.py
python3 -m http.server 8000 --directory docs
# 浏览器打开 http://localhost:8000
```

## 免责

本站为科普整理，**非医疗建议**；每条结论标注证据等级，点击可回原文核对。
具体执行请咨询持证医生或注册营养师。
