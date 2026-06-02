# 查过再信 · 健康说法核验库

一个持续收集、查证的中文循证健康说法核验库。每条说法都查到原始证据、标出强度、写清适用人群，
附可点击原文，并区分「✓ 研究支持」「◎ 官方依据」与「◔ 前沿待核」。
把"听来的"和"有据的"分开。

也提供公开机读接口（`docs/claims.json`）和零配置 Skill（`skill/SKILL.md`），可被 AI 助手直接调用。

## 结构

- `data/sources.json` — 信源清单（官方精选目录 / PubMed 主题；RSS / YouTube 仅为可选发现层）
- `data/items/*.json` — 收集到的条目（每条 = 一张卡片 / 一条核验）
- `collect.py` — 从信源抓取候选、去重（纯标准库）
- `audit_library.py` — 审计已发布馆藏：复核到期、证据待补、来源分布和链接可达性（纯标准库）
- `build.py` — 生成静态站到 `docs/`（精选 + 全部 + 关于 + 各条详情页 + `claims.json` 机读 feed；纯标准库）
- `make_og.py` — 生成社交分享卡 `assets/og.png`（需 Pillow，单独运行，不进构建）
- `skill/SKILL.md` — 公开 health-hot Skill，构建时拷进 `docs/skill/`
- 部署：GitHub Pages 从 `main` 分支 `/docs` 目录 serve，推送即更新
- 自动采集：GitHub Actions 每周一北京时间 08:00 抓取候选，并刷新 GitHub issue 审核收件箱；不会绕过人工核验直接发布

## 依据状态

- `study_supported`：存在 PubMed / DOI / Cochrane 研究锚点；对用户显示「研究支持」。
- `official_basis`：存在 WHO、NIH、卫健委、中国疾控等白名单机构的具体页面；显示「官方依据」。
- `frontier_pending`：来自专家、播客或趋势线索，但核验依据尚未补齐；只能称「前沿待核」。
- `evidence_source_urls` 放研究锚点或白名单官方页面；播客、视频、文章入口放 `discovery_source_url`。
- `source_urls` 仅为 feed 兼容字段，包含全部来源，不能当作研究原文列表。
- `verification_status` 是旧版二元兼容字段；新消费者应优先读取 `verification_basis`。

## 候选采集

```bash
python3 collect.py                       # 默认：官方 + PubMed + 专家解释层 + 已配置实验型雷达
python3 collect.py --include-discovery   # 可选：再加入未来配置的额外发现源
python3 collect.py 'PubMed·肌酸'         # 只抓名字匹配的信源
```

候选写入 `/tmp/health_candidates.json`。PubMed 窄主题雷达会附带 `relevance_hint`：
`title_match` 可优先看，`query_match_only` 表示查询命中但标题未命中主题词，必须人工/AI 再判断。
候选提升为正式条目时应保留 `canonical_id`，用于跨次采集去重。
官方精选目录为常青问题池，只接受 WHO、USPSTF、NIH ODS、NIH NCCIH、国家卫健委、中国疾控中心等
白名单官方域名下的具体事实页或指南页。`collect.py` 在代码中再次校验域名，不能只靠配置文件把任意
网站标成官方锚点。

可信专家的播客、YouTube 和博客默认进入每周候选，但与证据锚点分层展示。它们的价值是更早发现问题、
提供解释框架和访谈线索；局限是更新频率高、重复与观点性内容多，不能自动作为证据依据。采集器会从
节目简介或博客摘要提取 `citation_urls_to_review`，供人工或 AI 优先回溯；这些链接仍需确认是否真是
论文、指南或官方原文。完整链接还会保存在 `context_urls_to_review`，其中可能混有内部导航和赞助链接，
不能当作引用。对配置过的专家官方详情页，采集器还会额外跟随一跳，继续寻找 PubMed、DOI、政府机构、
临床试验注册和 Cochrane 链接。自我实验 / 个人方案雷达也会采集，但在审核清单中单独分组，不与专家
访谈或研究锚点混在一起。`python3 collect.py --include-discovery` 保留给未来新增的额外发现源。

GitHub Actions 工作流位于 `.github/workflows/collect-candidates.yml`。它也支持在 Actions 页面手动触发。
每次运行会保存 `health-candidates` Artifact（候选 JSON、采集日志、审核摘要、馆藏审计），并新建或刷新
标题为「每周健康候选采集」的 issue。健康内容仍需人工或 AI 复核后写入 `data/items/*.json`，
再运行 `build.py`；定时采集不会自动发布未经核验的说法。
审核 issue 会先列未来日期、标题弱相关、摘要为空等风险项，再按「官方事实页 / 指南常青候选」、
「PubMed 研究 / 指南锚点」、「PubMed 趋势雷达」、「可选发现来源」分组。`anchor` 表示可作证据依据，
不表示选题自动相关；仍需人工或 AI 判断是否值得入库。末尾的「已发布馆藏健康审计」还会提醒超过
180 天未复核的条目、证据待补条目和疑似失效链接；这些提醒不会自动改写或自动发布内容。

本地也可以单独运行馆藏审计：

```bash
python3 audit_library.py
python3 audit_library.py --check-links
```

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
