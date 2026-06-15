# health-hot-submit Pages fallback

Production Cloudflare Pages Functions endpoint for the site submit flow.

It reuses `submit-worker/src/worker.js` through `_worker.js`, but publishes on
`pages.dev`, which is more reliable than `workers.dev` in some networks. The
public production endpoint is:

```text
https://health-hot-submit.pages.dev/submit
```

Deploy from the repository root so `_worker.js` can resolve `../submit-worker/src/worker.js`.
Use `--branch=main`; otherwise Wrangler may publish a preview URL instead of updating the
apex production URL used by the frontend.

```bash
cd "/Users/liuyuxin/Documents/AI health"
npx wrangler --cwd submit-pages pages deploy . --project-name=health-hot-submit --branch=main
submit-worker/smoke-cors.sh https://health-hot-submit.pages.dev https://health-hot.vercel.app
```

Do not switch the frontend to `workers.dev`; that route is a non-production bypass and is
unreliable in some real user networks.
