#!/bin/bash
# tg_notify.sh — envia mensagem de progresso ao chat admin durante execução do agente
# Uso: tg_notify.sh "texto da mensagem"
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
MSG="${1:-}"
[ -z "$MSG" ] && exit 1
curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${MSG}" \
  --data-urlencode "parse_mode=HTML" \
  --data-urlencode "disable_web_page_preview=true" >/dev/null
