#!/usr/bin/env bash
# aws-smoke.sh — post-deploy smoke + load check for the deployed LexBot stack
# (SDD aws-deploy AWS-17; INF-1 MEDIUM-risk task-sizing validation).
#
# Three parts:
#   1. /health gate: assert db == "ok" AND vector_count > 0. HARD GATE —
#      exits non-zero on failure.
#   2. Three scripted POST /chat calls (LangGraph + Gemini + retrieval) with
#      per-call and average latency (informational load signal).
#   3. Peak MemoryUtilized (ECS/ContainerInsights, last 15 min) report —
#      best-effort: missing aws CLI, cluster/service, or datapoints only warn.
#
# Usage:
#   BASE_URL=https://<cloudfront-domain> ./scripts/aws-smoke.sh
#   BASE_URL=... AWS_REGION=us-east-1 TASK_MEMORY_MIB=2048 ./scripts/aws-smoke.sh
#
# Requirements: bash, curl, python3, and (for the memory report only) the AWS
# CLI with credentials able to read ECS + CloudWatch. GNU date (Linux) for the
# %N nanosecond latency capture.
set -euo pipefail

BASE_URL="${BASE_URL:-}"
REGION="${AWS_REGION:-us-east-1}"
PROBE_MESSAGE="${PROBE_MESSAGE:-What should I bring to the first consultation?}"
# Matches the cdk context default (-c taskMemoryMiB=1024); override when the
# stack was deployed with a different size.
TASK_MEMORY_MIB="${TASK_MEMORY_MIB:-1024}"

log() { printf '\n== %s ==\n' "$*"; }
fail() { echo "ERROR: $*" >&2; exit 1; }

BASE_URL="${BASE_URL%/}" # tolerate a trailing slash

command -v curl >/dev/null || fail "curl is required"
command -v python3 >/dev/null || fail "python3 is required"
[[ -n "$BASE_URL" ]] || fail "BASE_URL is required (https://<cloudfront-domain>)"

# --- 1. /health gate (AWS-16 semantics) -------------------------------------
log "GET $BASE_URL/health"
health="$(curl -fsS --max-time 30 "$BASE_URL/health")" || fail "health request failed (curl exit $?)"
printf 'health: %s\n' "$health"
db="$(printf '%s' "$health" | python3 -c 'import json, sys; print(json.load(sys.stdin)["db"])')"
count="$(printf '%s' "$health" | python3 -c 'import json, sys; print(json.load(sys.stdin)["vector_count"])')"
[[ "$db" == "ok" ]] || fail "health db=$db (expected ok) — database not reachable"
[[ "$count" -gt 0 ]] || fail "health vector_count=$count (expected > 0) — knowledge store not seeded"
echo "gate passed: db=$db vector_count=$count"

# --- 2. Scripted /chat calls (latency capture) --------------------------------
total_ms=0
for i in 1 2 3; do
  log "POST $BASE_URL/chat ($i/3)"
  payload="$(printf '{"message": %s}' "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$PROBE_MESSAGE")")"
  start="$(date +%s%N)"
  resp="$(curl -fsS --max-time 120 -X POST "$BASE_URL/chat" \
    -H 'Content-Type: application/json' \
    --data "$payload")" || fail "/chat call $i failed (curl exit $?)"
  end="$(date +%s%N)"
  ms=$(( (end - start) / 1000000 ))
  total_ms=$(( total_ms + ms ))
  answer="$(printf '%s' "$resp" | python3 -c 'import json, sys; print(json.load(sys.stdin)["answer"][:80])')"
  printf 'chat %d: %dms | answer: %s\n' "$i" "$ms" "$answer"
done
printf '\naverage /chat latency: %dms\n' "$(( total_ms / 3 ))"

# --- 3. Peak MemoryUtilized (Container Insights) — best-effort report --------
log "Peak MemoryUtilized (last 15 min, $REGION)"
if ! command -v aws >/dev/null 2>&1; then
  echo "warning: aws CLI not found — skipping memory report (informational)"
  exit 0
fi

cluster=""
for arn in $(aws ecs list-clusters --region "$REGION" --query 'clusterArns[]' --output text 2>/dev/null || true); do
  name="${arn##*/}"
  if aws ecs describe-clusters --region "$REGION" --clusters "$name" \
    --query 'clusters[0].tags[?key==`app` && value==`lexbot`].key' --output text 2>/dev/null | grep -q lexbot; then
    cluster="$name"
    break
  fi
done
if [[ -z "$cluster" ]]; then
  echo "warning: no ECS cluster tagged app=lexbot found — skipping memory report"
  exit 0
fi

service=""
for arn in $(aws ecs list-services --region "$REGION" --cluster "$cluster" --query 'serviceArns[]' --output text 2>/dev/null || true); do
  name="${arn##*/}"
  if aws ecs describe-services --region "$REGION" --cluster "$cluster" --services "$name" \
    --query 'services[0].tags[?key==`app` && value==`lexbot`].key' --output text 2>/dev/null | grep -q lexbot; then
    service="$name"
    break
  fi
done
if [[ -z "$service" ]]; then
  echo "warning: no ECS service tagged app=lexbot found in $cluster — skipping memory report"
  exit 0
fi

start_ts="$(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%SZ)"
end_ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
values="$(aws cloudwatch get-metric-statistics --region "$REGION" \
  --namespace 'ECS/ContainerInsights' --metric-name 'MemoryUtilized' \
  --dimensions "Name=ClusterName,Value=$cluster" "Name=ServiceName,Value=$service" \
  --statistics Maximum --period 60 --start-time "$start_ts" --end-time "$end_ts" \
  --query 'Datapoints[].Maximum' --output text 2>/dev/null || true)"
if [[ -z "$values" ]]; then
  echo "warning: no MemoryUtilized datapoints in the last 15 min — report skipped (Container Insights may be warming up)"
  exit 0
fi
peak="$(printf '%s\n' $values | sort -n | tail -1)"
pct="$(awk -v p="$peak" -v m="$TASK_MEMORY_MIB" 'BEGIN { printf "%.0f", p * 100 / m }')"
echo "peak MemoryUtilized: ${peak} MiB (${pct}% of ${TASK_MEMORY_MIB} MiB — memory alarm threshold is 85%)"
