#!/usr/bin/env bash
# demo-whatsapp.sh — bring the LexBot stack up and send a real WhatsApp message
# through the n8n bridge (Milestone 4). Idempotent: safe to re-run.
#
# Requires Meta WhatsApp Cloud API credentials in the repo-root .env:
#   WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_VERIFY_TOKEN
# Optional: WHATSAPP_RECIPIENT (defaults to WHATSAPP_PHONE_NUMBER_ID's test number).
#
# Usage:
#   scripts/demo-whatsapp.sh [+1234567890]   # recipient overrides WHATSAPP_RECIPIENT
set -euo pipefail

cd "$(dirname "$0")/.."  # repo root

log() { printf '\n== %s ==\n' "$*"; }

# --- 1. Env check -----------------------------------------------------------
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

missing=()
for var in WHATSAPP_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_VERIFY_TOKEN; do
  if [[ -z "${!var:-}" ]]; then missing+=("$var"); fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: missing required env var(s): ${missing[*]}" >&2
  echo "Set them in .env (see .env.example) before running the demo." >&2
  exit 1
fi

RECIPIENT="${1:-${WHATSAPP_RECIPIENT:-}}"
if [[ -z "$RECIPIENT" ]]; then
  echo "ERROR: no recipient. Pass a phone number as argument 1 or set WHATSAPP_RECIPIENT." >&2
  echo "Example: $0 +5491123456789" >&2
  exit 1
fi

# --- 2. Stack up ------------------------------------------------------------
log "Starting LexBot stack (db, api, n8n)…"
docker compose up -d

log "Waiting for n8n health (:5679/healthz)…"
for i in $(seq 1 60); do
  if docker compose exec -T n8n wget -qO- http://localhost:5678/healthz >/dev/null 2>&1; then
    echo "n8n healthy after ${i}s"
    break
  fi
  [[ "$i" -eq 60 ]] && { echo "ERROR: n8n not healthy after 60s" >&2; exit 1; }
  sleep 1
done

log "Waiting for api health (:8000/health)…"
for i in $(seq 1 60); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    echo "api healthy after ${i}s"
    break
  fi
  [[ "$i" -eq 60 ]] && { echo "ERROR: api not healthy after 60s" >&2; exit 1; }
  sleep 1
done

# --- 3. Outbound send -------------------------------------------------------
log "Sending outbound WhatsApp message to $RECIPIENT…"
curl -fsS -X POST http://localhost:5679/webhook/outbound-whatsapp \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$RECIPIENT\",\"message\":\"Hola desde LexBot 👋 (demo)\"}"
echo

# --- 4. Inbound instructions ------------------------------------------------
cat <<EOF

== Inbound demo ==
1. Open WhatsApp on your phone (or the Meta test number's paired device).
2. Message the test number bound to WHATSAPP_PHONE_NUMBER_ID.
3. The n8n inbound webhook routes it through POST /chat and replies.

Verification:
- Outbound: check the n8n UI (http://localhost:5679) → executions for the
  outbound workflow → the Meta send node result.
- Inbound: message the test number, then check the inbound workflow
  execution for the reply step.
EOF