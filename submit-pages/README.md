# health-hot-submit Pages fallback

Cloudflare Pages fallback for the same submit endpoint. It reuses `submit-worker/src/worker.js`
but publishes on `pages.dev`, which is more reliable than `workers.dev` in some networks.
