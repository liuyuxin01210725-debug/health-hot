# health-hot-submit

极小提交接收端的共享实现：网页无结果时，用户点「提交这条说法待核」，Worker 创建一个带
`待核说法` 标签的 GitHub issue。现有 `collect.py` 已会在每周采集时读取这些 issue，汇入候选清单。

**生产入口不是 `workers.dev`。** 正式前端打的是 Cloudflare Pages Functions：
`https://health-hot-submit.pages.dev/submit`。`submit-pages/_worker.js` 复用这里的
`src/worker.js`，所以改逻辑仍改本目录，但上线生产要部署 `submit-pages/`。

## 生产部署

```bash
cd "/Users/liuyuxin/Documents/AI health"
npx wrangler --cwd submit-pages pages deploy . --project-name=health-hot-submit --branch=main
submit-worker/smoke-cors.sh https://health-hot-submit.pages.dev https://health-hot.vercel.app
```

`GITHUB_TOKEN` 使用 fine-grained token，权限只给本仓库 `Issues: Read and write`。
不要把 token 写入前端或提交到仓库；生产 Pages 项目需要配置该 secret。

`src/worker.js` 的 CORS 白名单采用 `DEFAULT_ALLOWED_ORIGINS ∪ env.ALLOWED_ORIGINS`，
这样 Cloudflare 面板里的旧 `ALLOWED_ORIGINS` 不会覆盖掉代码里的正式站默认源。

## 非生产 Worker 旁路

`npx wrangler deploy` 会部署到 `workers.dev`。这条线可作实验，但不是生产路径；
`workers.dev` 在部分真实网络不可达，不要把前端切过去。

推荐再绑定 KV，用于限流和重复提交合并：

```bash
npx wrangler kv namespace create PENDING_KV
```

把返回的 namespace id 填进 `wrangler.toml` 的 `[[kv_namespaces]]`，再部署一次。

## 接入前端

默认前端已指向生产 Pages endpoint。只有改 endpoint 时才需要重新构建静态站：

```bash
HEALTH_HOT_SUBMIT_ENDPOINT="https://health-hot-submit.pages.dev/submit" python3 build.py
```

未配置 `HEALTH_HOT_SUBMIT_ENDPOINT` 时，网页会自动退回复制/分享，不会假装提交成功。

## 站内搜索计数端点 `/event`（精选「热点度」数据源）

同一 Worker 还有两条路由（复用同一 `PENDING_KV` / CORS / 限流）：

- `POST /event`，body `{term, hit}`：记录站内搜索词命中/未命中计数。存 `evt:q:<sha256(规范化term)>` →
  `{t,h,m,ts}`，TTL 180 天。**隐私**：只存规范化词 + 计数 + 末次日期，不存 IP（仅哈希做 48h 软限流
  `evtrate:`）、不存用户/历史；词长 ≤60、<2 字符丢弃。永远返回 204（fire-and-forget）。软限流上限
  env `EVENT_DAILY_LIMIT_PER_IP`（默认 300）。
- `GET /event/stats?token=<EVENT_STATS_TOKEN>`：按总次数降序读回 `{count, terms:[{term,h,m,ts}]}`（默认 top 200）。
  **token 保护**，不公开裸搜索词；给构建期 / `scripts/search_hotness.py` 读回，喂精选「热点度」打分。

前端打点在 `build.py` 生成的 `all.html` 搜索框：停手约 1 秒才发一条（防抖 + 同词去重，sendBeacon/text-plain 免预检）。
端点默认 `https://health-hot-submit.pages.dev/event`，可用 env `HEALTH_HOT_EVENT_ENDPOINT` 覆盖。
`EVENT_STATS_TOKEN` 走 secret（`wrangler pages secret put EVENT_STATS_TOKEN --project-name=health-hot-submit` 或 CF 面板），不写进 toml / 仓库。
