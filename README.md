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
- `build.py` — 生成静态站到 `docs/`（精选 + 全部 + 关于 + 各条详情页 + `claims.json` 机读 feed；纯标准库）。**自带发布闸门 + 强审硬锁**，详见「强审与发布闸门」。
- `scripts/prepush_check.py` — 增量强审闸门：改动条目须有 PASS 强审记录才放行（本机 pre-push 钩子与 CI 都调它）
- `scripts/search_hotness.py` — 读回站内搜索计数（`/event`，见「用户提交闭环」），供精选「热点度」打分（纯读，需 `EVENT_STATS_TOKEN`）
- `data/review_audit.json` — `/health-review` 强审账本，按 `content_sha` 绑定正文（正文一改记录即作废）
- `data/strong_review_grandfather.json` — 待强审存量固化清单（与 `review_audit.json` 互斥，随强审瘦身；**勿手工重生成**）
- `data/topic_backlog.json` — 常青选题清单（不分新旧的高价值待做话题；周更从「新候选 + 此清单」一起挑，常青话题按最强证据搜、不按日期）
- `data/source_blocklist.json` — 噱头 / 带货 / 伪科学黑名单（惰性：未接入 `collect.py` 采集；兼作小红书打假选题库）
- `make_og.py` — 生成社交分享卡 `assets/og.png`（需 Pillow，单独运行，不进构建）
- `submit-worker/` — 一键提交接收端的共享 Worker 实现：把搜索无结果时的用户提交创建成 GitHub issue；并提供 `/event` 站内搜索计数端点（精选「热点度」数据源，见「用户提交闭环」）
- `submit-pages/` — 生产提交端（Cloudflare Pages Functions），复用 `submit-worker/src/worker.js`，公开端点为 `https://health-hot-submit.pages.dev`
- `skill/SKILL.md` — 公开 health-hot Skill，构建时拷进 `docs/skill/`
- 部署：**Vercel** 以 `python3 build.py` 为 buildCommand 构建上线（见 `vercel.json`）；`docs/` 也提交入库。因此 build.py 的闸门就是线上站的部署硬锁。
- 早警 CI：`.github/workflows/ci.yml` 在 push/PR 上跑构建 + 单测 + 审计 + 强审；自动采集：`.github/workflows/collect-candidates.yml` 每周一北京时间 08:00 抓候选并刷新 GitHub issue 收件箱；均不会绕过人工核验直接发布

## 依据状态

- `study_supported`：存在 PubMed / DOI / Cochrane 研究锚点；对用户显示「研究支持」。
- `official_basis`：存在 WHO、NIH、卫健委、中国疾控等白名单机构的具体页面；显示「官方依据」。
- `frontier_pending`：来自专家、播客或趋势线索，但核验依据尚未补齐；只能称「前沿待核」。
- `evidence_source_urls` 放研究锚点或白名单官方页面；播客、视频、文章入口放 `discovery_source_url`。
- `source_urls` 仅为 feed 兼容字段，包含全部来源，不能当作研究原文列表。
- `verification_status` 是旧版二元兼容字段；新消费者应优先读取 `verification_basis`。

## 强审与发布闸门

两层把关，定位不同——别把「会报警的东西」当成「会拦截的东西」：

1. **数据发布闸门**（`build.py`）：缺来源 / 未来日期 / 伪链接 / 字段缺失 / `status≠reviewed` 的条目一律拦下，构建退码 1、`docs/` 不替换（保留旧站）。
2. **强审硬锁**（`build.py` 第二段）：任何**新增或被编辑过**的条目，必须先过 `/health-review` 对抗式强审、在 `data/review_audit.json` 留下 `verdict=PASS` 且 `content_sha` 与当前正文一致的记录，否则同样被拦、上不了线。

**为什么这是真锁：** 部署走 Vercel，`buildCommand` 就是 `python3 build.py`（见 `vercel.json`）。上面两道闸门在每次部署时由 Vercel 强制执行，无需任何 GitHub 设置；构建失败 = 部署失败 = 线上保留上一个成功版本。

**全库强审 vs 增量强审（诚实说明）：**

- **增量强审已是硬锁**：从现在起，改动 / 新增条目不过 `/health-review` 就上不了线。
- **audit 权威，grandfather 只兜底**：条目一旦在 `review_audit.json` 有记录就以它为准——`FIX` / `BLOCK`、或 `PASS` 但 `content_sha` 不符，一律拦，grandfather **不能**覆盖否决；grandfather 仅对【无 audit 记录】的条目按 `content_sha` 兜底放行。
- **全库强审尚未完成**：当前 **18 条**有 PASS 记录（走 audit 权威路径），**134 条**仅由 `data/strong_review_grandfather.json` 固化兜底——**不代表已被强审**，只是冻结了当时正文、让硬锁上线当天不冻结全站。
- **grandfather = 真实待审存量，会瘦身**：`record_review.py` 记任何 verdict 时即把该 slug 移出 grandfather，所以 `len(grandfather)` 就是「从未强审过」的条数（现 134），两个账本互斥。**编辑任一固化条目**（哪怕改错字）→ 哈希变 → 脱离兜底 → 必须强审。
- **切勿手工重新生成** `strong_review_grandfather.json`——那等于把当前未审内容重新「洗白」。要消化存量，就逐条跑 `/health-review`（自动瘦身）。

**早警 CI（`.github/workflows/ci.yml`，push / PR 触发）** 复刻 build.py 全库闸门 + 单测 + 馆藏审计 + 对改动条目跑 `scripts/prepush_check.py`（本机 pre-push 钩子的云端镜像）。它是**早警，不是合并硬门**：仓库若「直推 main + Vercel 自动部署」，CI 拦不住部署本身。要让它成为合并硬门，需在 GitHub 仓库设置开 **Branch protection**（要求本 workflow 通过 + 禁直推 main，改走 PR 流）。本机 `.git/hooks/pre-push` 不进版本库，仅本机有效。

## 精选 / 重点核验怎么选

首页「重点核验」**不靠手动标记，由 `build.py` 算「重点核验分」自动选取**（`select_featured`）：
`0.45·证据强度 + 0.20·rank(编辑重要性) + 0.20·新鲜度 + 0.15·热点度`，只取已核验层（前沿待核不进门面），
类目均衡（每类 ≤6）取约 24 条，每次构建自动刷新——新加的强证据 / 新条目会自动浮上来，不会冻住。
`featured` 由算分在内存标记（数据文件不写回手动值，首页精选块 / ✦ 星标 / `claims.json` 统一用它）。
`rank`(0–100) 是**编辑拉杆**：想让 expert / 综述层但认知差大的条目顶门面，把它 `rank` 设高即可。
热点度来自 `data/search_hotness.json`（站内搜索 `/event` 计数，文件在场才生效；暂无数据时记 0、其余三项照常驱动）。

## 候选采集

```bash
python3 collect.py                       # 默认：官方 + PubMed + 专家解释层 + 已配置实验型雷达
python3 collect.py --include-discovery   # 可选：再加入未来配置的额外发现源
python3 collect.py 'PubMed·肌酸'         # 只抓名字匹配的信源
python3 collect.py --doctor              # 信源体检：逐源探活检索/抓取机制（只读、不写候选；--check-urls 另巡检官方锚点）
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

## 用户提交闭环

静态主站不能自己保存用户输入。公开站的「没找到 → 一键提交待核」走一个极小接收端：
生产端是 **Cloudflare Pages Functions** `https://health-hot-submit.pages.dev`，源码在 `submit-pages/`，
并通过 `_worker.js` 复用 `submit-worker/src/worker.js`。它把用户主动提交的健康说法创建为带
`待核说法` 标签的 GitHub issue。`collect.py` 每周会读取这些 issue，汇入候选清单；仍需人工或 AI
复核，不会自动发布。

更新生产提交端：

```bash
npx wrangler --cwd submit-pages pages deploy . --project-name=health-hot-submit --branch=main
submit-worker/smoke-cors.sh https://health-hot-submit.pages.dev https://health-hot.vercel.app
```

`submit-worker/src/worker.js` 的 CORS 白名单采用 `DEFAULT_ALLOWED_ORIGINS ∪ env.ALLOWED_ORIGINS`，
避免 Cloudflare 面板旧环境变量覆盖掉代码里的生产默认源。直接 `wrangler deploy` 到 `workers.dev`
不是生产路径；`workers.dev` 在部分真实网络不可达，不要把前端切过去。

如需改 endpoint 后重新构建：

```bash
HEALTH_HOT_SUBMIT_ENDPOINT="https://health-hot-submit.pages.dev/submit" python3 build.py
```

当前默认接收端是 `https://health-hot-submit.pages.dev/submit`；未配置
`HEALTH_HOT_SUBMIT_ENDPOINT` 且默认端点被清空时，页面会自动退回复制 / 分享，不会假装提交成功。

本地也可以单独运行馆藏审计：

```bash
python3 audit_library.py
python3 audit_library.py --check-links
```

### 待核管理面板（私有运营视图）

把「待核说法」issue 堆变成可处理的选题池。`scripts/pending_dashboard.py` 用 `gh` 读取后，按归一化说法分组、统计「被提交 N 次」、解出用户「搜了但没命中」的原词，生成本地 HTML 面板（写到 `/tmp`，不进 `docs/`、不公开）。

```bash
python3 scripts/pending_dashboard.py                            # 看板（只读）→ 终端摘要 + /tmp/health_pending_dashboard.html
python3 scripts/pending_dashboard.py --mark <issue#> ingested   # 标「已入库」并关闭
python3 scripts/pending_dashboard.py --mark <issue#> rejected   # 标「已拒绝」并关闭
```

- **状态约定**：开放无状态标签 = 待处理；`已入库` / `已拒绝` 标签（首次 `--mark` 自动创建）+ 关闭 = 已处理；`collect.py` 只读 open issue，所以关闭即退出候选池。
- **「被提交 N 次」**= 同一归一化说法各 issue 的提交次数之和；单条 = `1 + 提交端去重时追加的「🔁」评论数`。提交端是否开 KV 去重，口径都一致（去重前=多条 issue，去重后=1 条+🔁评论）。
- **去重 / 限流 / 重复计数**需要给提交端绑 KV：`npx wrangler kv namespace create PENDING_KV`，把 id 填进 `submit-worker/wrangler.toml` 与 `submit-pages/wrangler.toml`，再用 `npx wrangler --cwd submit-pages pages deploy . …` 部署（见 `submit-worker/README.md`）。

## Agent 接入

```bash
# Claude Code
mkdir -p ~/.claude/skills/health-hot
curl -fsSL https://health-hot.vercel.app/skill/SKILL.md \
  -o ~/.claude/skills/health-hot/SKILL.md

# Codex
mkdir -p ~/.codex/skills/health-hot
curl -fsSL https://health-hot.vercel.app/skill/SKILL.md \
  -o ~/.codex/skills/health-hot/SKILL.md
```

## 访客统计（可选）

构建脚本支持 Cloudflare Web Analytics。默认不注入任何统计脚本；只有设置
`HEALTH_HOT_CF_ANALYTICS_TOKEN` 时，`build.py` 才会在所有 HTML 页面的 `</body>` 前注入
Cloudflare beacon。`claims.json`、`sitemap.xml`、`robots.txt` 和 Skill 文件不会被注入。

推荐把 token 只配置在 Vercel 项目的 Environment Variables 里，不写进仓库：

```bash
HEALTH_HOT_CF_ANALYTICS_TOKEN="cloudflare-token" python3 build.py
```

Cloudflare Web Analytics 适合看页面访问、来源和热门 URL；它不记录站内搜索词，也不支持自定义事件。
站内「搜了什么、有没有命中」由独立的 `/event` 事件端点统计（见「用户提交闭环」），与 CF Analytics 互补。

## 本地预览

```bash
python3 build.py
python3 -m http.server 8000 --directory docs
# 浏览器打开 http://localhost:8000
```

## 免责

本站为科普整理，**非医疗建议**；每条结论标注证据等级，点击可回原文核对。
具体执行请咨询持证医生或注册营养师。
