#!/usr/bin/env bash
# demo-telegram.sh — bring the LexBot stack up and send a real Telegram message
# through the Bot API sendMessage endpoint. Idempotent: safe to re-run.
#
# Requires Telegram credentials in the repo-root .env:
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# Optional: TELEGRAM_WEBHOOK_URL (+ TELEGRAM_WEBHOOK_SECRET) to also register
# the inbound webhook so the bot replies in the same chat.
#
# Usage:
#   scripts/demo-telegram.sh [CHAT_ID]   # chat overrides TELEGRAM_CHAT_ID
set -euo pipefail

cd "$(dirname "$0")/.."  # repo root

log() { printf '\n== %s ==\n' "$*"; }

# --- 1. Env check -----------------------------------------------------------
if [[ -f .env ]]; then
  set -a; source .env; set +a
fi

missing=()
for var in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID; do
  if [[ -z "${!var:-}" ]]; then missing+=("$var"); fi
done

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: missing required env var(s): ${missing[*]}" >&2
  echo "Set them in .env (see .env.example) before running the demo." >&2
  exit 1
fi

CHAT_ID="${1:-${TELEGRAM_CHAT_ID:-}}"
if [[ -z "$CHAT_ID" ]]; then
  echo "ERROR: no chat id. Pass one as argument 1 or set TELEGRAM_CHAT_ID." >&2
  echo "Example: $0 123456789" >&2
  exit 1
fi

# --- 2. Stack up ------------------------------------------------------------
log "Starting LexBot stack (db, api)…"
docker compose up -d

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
log "Sending Telegram message to chat $CHAT_ID…"
curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\":\"$CHAT_ID\",\"text\":\"Hola desde LexBot 👋 (demo)\"}"
echo

# --- 4. Inbound webhook (optional) ------------------------------------------
if [[ -n "${TELEGRAM_WEBHOOK_URL:-}" ]]; then
  log "Registering inbound webhook ($TELEGRAM_WEBHOOK_URL)…"
  curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
    -H "Content-Type: application/json" \
    -d "{\"url\":\"$TELEGRAM_WEBHOOK_URL\",\"secret_token\":\"${TELEGRAM_WEBHOOK_SECRET:-}\"}"
  echo
else
  echo "TELEGRAM_WEBHOOK_URL not set — skipping setWebhook (inbound replies need it)."
fi

# --- 5. Inbound instructions ------------------------------------------------
cat <<EOF

== Inbound demo ==
1. Open Telegram on your phone or desktop.
2. Message the bot you created with @BotFather (the token bound to
   TELEGRAM_BOT_TOKEN).
3. The registered webhook routes the message through POST /webhook/telegram
   and the agent replies in the same chat.

Verification:
- Outbound: the sendMessage above arrives in the chat.
- Inbound: message the bot; the reply should arrive in the same chat.
EOF