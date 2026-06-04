# health-hot-submit

极小提交接收端：网页无结果时，用户点「提交这条说法待核」，Worker 创建一个带 `待核说法`
标签的 GitHub issue。现有 `collect.py` 已会在每周采集时读取这些 issue，汇入候选清单。

## 部署

```bash
cd submit-worker
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
```

`GITHUB_TOKEN` 使用 fine-grained token，权限只给本仓库 `Issues: Read and write`。
不要把 token 写入前端或提交到仓库。

推荐再绑定 KV，用于限流和重复提交合并：

```bash
npx wrangler kv namespace create PENDING_KV
```

把返回的 namespace id 填进 `wrangler.toml` 的 `[[kv_namespaces]]`，再部署一次。

## 接入前端

拿到 Worker URL 后重新构建静态站：

```bash
HEALTH_HOT_SUBMIT_ENDPOINT="https://health-hot-submit.liuyuxin-health-hot.workers.dev/submit" python3 build.py
```

未配置 `HEALTH_HOT_SUBMIT_ENDPOINT` 时，网页会自动退回复制/分享，不会假装提交成功。
