#!/usr/bin/env bash
# 提交端 live smoke test —— 部署 Worker 后手动跑，验证真实用户旅程关键环节：
#   1. 正式站 Origin 的 OPTIONS /submit 预检返回正确 CORS（不是 "null"）
#   2. honeypot POST（带 website 字段）被拒（spam_rejected）——确认反垃圾仍生效
#   3. /health 存活
#
# 这是 push CI 之外的一道闸：CI 是离线确定性的，这里专测【已部署】的线上行为。
# honeypot POST 在 worker 里早于建 issue 就被拒，不会真的创建 issue、不消耗限流。
#
# 用法：
#   submit-worker/smoke-cors.sh                       # 用默认端点/正式站 Origin
#   submit-worker/smoke-cors.sh <endpoint> <origin>   # 自定义
set -u

ENDPOINT="${1:-https://health-hot-submit.pages.dev}"
ORIGIN="${2:-https://health-hot.vercel.app}"
fail=0

echo "▶ 提交端 smoke：endpoint=$ENDPOINT  origin=$ORIGIN"

# 1) CORS 预检
acao="$(curl -s -i -X OPTIONS "$ENDPOINT/submit" \
  -H "Origin: $ORIGIN" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type" \
  --max-time 20 2>/dev/null | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2}' | tail -n1)"
if [ "$acao" = "$ORIGIN" ]; then
  echo "  ✓ CORS 预检：access-control-allow-origin=$acao"
else
  echo "  ✗ CORS 预检：期望 ${ORIGIN}，实得 '${acao:-<空>}' —— 正式站提交会被浏览器拦。检查 wrangler.toml ALLOWED_ORIGINS 并重新部署。"
  fail=1
fi

# 2) honeypot POST 应被拒（带 website 字段 = 机器人）
body="$(curl -s -X POST "$ENDPOINT/submit" \
  -H "Origin: $ORIGIN" -H "Content-Type: application/json" \
  --data '{"website":"bot","claim":"smoke honeypot 测试，应被拒"}' \
  --max-time 20 2>/dev/null)"
if printf '%s' "$body" | grep -q "spam_rejected"; then
  echo "  ✓ honeypot：带 website 的提交被拒（spam_rejected）"
else
  echo "  ✗ honeypot：未按预期拒绝，实得：$body"
  fail=1
fi

# 3) /health 存活
code="$(curl -s -o /dev/null -w '%{http_code}' "$ENDPOINT/health" --max-time 20 2>/dev/null)"
if [ "$code" = "200" ]; then
  echo "  ✓ /health：200"
else
  echo "  ✗ /health：HTTP $code"
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "✓ 提交端 smoke 全过"
else
  echo "✗ 提交端 smoke 有失败项（见上）"
fi
exit "$fail"
