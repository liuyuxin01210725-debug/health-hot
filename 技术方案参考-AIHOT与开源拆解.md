# 技术方案参考：AI HOT 逆向 + 开源近亲拆解 + 我们的取舍

> 目的：把 AI HOT 的技术方案扒清楚，对照开源实现，定出我们健康版"能直接用 / 不能照搬 / 可优化"的清单。
> 日期：2026-05-31

---

## 一、AI HOT（闭源，逆向自 live API）

**重要：AI HOT 平台本身不开源**，GitHub 上开源的只是它的客户端 skill（curl API 的封装）。后端代码扒不到，以下是从公开 API 逆向的。

- **信源 ~76 个**，类型与比例：
  - **RSS（主力）**：IT之家(20)、OpenAI 官网(8)、HuggingFace 论文(8)、NVIDIA 博客(7)、TechCrunch / The Verge / Bloomberg / Google 开发者博客…
  - **X 账号（数量最多、单个量少）**：阿里云、OpenRouter、Replit、Greg Brockman、Gemini、Qwen、Kling、Runway… 一大批
  - **Hacker News**（经 buzzing.cc 中文翻译）
  - **网页爬取**（无 RSS 的官网）：Anthropic Newsroom、Claude Blog
- **获取方式比例**：RSS 主力 + X 账号铺广度 + HN 补热度 + 网页爬补缺口
- **分类 5 类**：tip / ai-products / industry / paper / ai-models
- **留存/归档**：每条带 `publishedAt`，游标分页；按日期归档（`/daily/2026-05-07`、`/all?page=47`）= **月级存档库**，可回溯
- **对外接口**：`/api/public/items`(分页) + `/daily` + `/rss/curated|daily|all` + `/agent`(skill 接入)
- **pipeline 推断**：信源 → 抓取 → LLM(摘要"推荐理由" + 分类 + 精选排名) → 每日 digest + 全量归档 + RSS 输出 + API/skill

## 二、开源近亲（可读源码）

### CloudFlare-AI-Insight-Daily（跟我们最像）
- 模式：**定时抓取 → AI 处理(Gemini) → 生成静态站 → GitHub Pages**
- 调度：GitHub Actions + Cloudflare Workers；JS
- 信源：行业新闻 / 开源项目 / 论文 / 科技大V
- 输出：GitHub Pages 日报（前端 Hugo + Hextra 主题）
- **价值：它的部署方式跟我们完全一致（GitHub Pages）**

### TrendRadar（GPL-3.0，成熟）
- 信源：`config.yaml` 配 RSS；`frequency_words.txt` 关键词过滤(+必含 / !排除 / 正则)
- AI：**LiteLLM**（100+ 模型：DeepSeek/OpenAI/Gemini/Claude/Ollama），能力 = 智能打分筛选(1-10) + 分析 + 翻译
- 存储：本地 SQLite(`output/{type}/{date}.db`) + 远程 S3；**guid 去重 + 保留策略**
- 输出：HTML 报告 + Markdown + 9 个推送渠道 + **MCP(21+ 工具，AI 可对话访问)**
- 栈：Python + requests/pyyaml/litellm/boto3；GitHub Actions(`crawler.yml`) + Docker
- ⚠️ **GPL-3.0**：fork 改它的代码 → 我们的衍生品也必须开源

## 三、共同模式（三者一致）

> **定时抓取（RSS/X/爬） → AI 处理（摘要+分类+排序+去重） → 生成静态站 → 部署 + RSS/API 输出**

## 四、我们的取舍

### ✅ 直接用 / 借鉴
1. **核心架构**：GitHub Actions(定时) + Python(抓取+处理) + 我们的 `build.py`(生成卡片站) + GitHub Pages
2. **config 驱动信源**（仿 TrendRadar 的 `config.yaml`）：信源写配置，加源=改配置。我们已有《资料采集清单》转成 `sources.yaml`
3. **去重 + 归档**（guid 去重 + 按日期存）：健康站的留存机制直接借
4. **LiteLLM 模型无关**：用 Claude / Kimi / DeepSeek 均可，不锁死
5. **对外接口**：RSS 输出（让人订阅精选）+ 一个 skill（对应"聊一句"愿景）

### ❌ 不能照搬 / 必须改（健康特性）
1. **信源不要 76 个、不要 X 热搜流**。AI HOT 求"量"（AI 每天几十条），健康求"权威"。我们 = 少而精：播客(Attia/Huberman/FoundMyFitness) + 期刊(Lancet/Nature Med) + PubMed + Examine/Cochrane。**X 在健康里权重低**
2. **不要日更 / 按热度排**。我们按**权威 + 证据等级**排，节奏"本周精选"
3. **必须加 7 铁律层**：证据分级 / 引用追溯 / 医疗免责 / 不给剂量 / 自媒体红线——这是 AI HOT 和开源项目都没有的，是我们的护城河
4. **不 fork TrendRadar（GPL-3.0 传染）**：借鉴设计，用我们自己干净的 Python 实现，保留闭源/商业化自由

### ⭐ 可优化 / 我们更好
1. **证据等级 + 推荐理由结合**：AI HOT 只有推荐理由，我们加证据分级，对健康更有用
2. **慢节奏的存在感设计**：知识库优先 + 本周精选 + 旧结论重审——治健康更新慢，AI HOT 的"新闻流"模式做不到

## 五、我们的收集引擎（"收集 skill"）设计

```
sources.yaml（信源，来自《资料采集清单》）
   ↓  Python 抓取（YouTube频道RSS / 播客RSS / PubMed RSS / 期刊RSS）
   ↓  guid 去重（已收过的不重复）
   ↓  LLM 按 7 铁律 处理：摘要 + 证据等级 + 推荐理由 + 分类（+ 红线检查）
   ↓  写出 data/items/*.json
   ↓  build.py 生成卡片站  →  git push  →  GitHub Pages
```
- 触发：GitHub Actions **每周**（合健康节奏）+ 按需 skill（"收集一下 FoundMyFitness 最近的"）
- 全程纯标准库 + 一个 LLM 调用，无 GPL 依赖
