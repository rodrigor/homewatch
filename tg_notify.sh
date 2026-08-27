#!/bin/bash
# tg_notify.sh — envia mensagem de progresso ao chat admin durante execução do agente
# Uso: tg_notify.sh "texto da mensagem"
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
# --id: imprime o message_id da mensagem enviada (para quem precisa saber em que
# mensagem a reação 👍/👎 vai cair). Sem a flag, o comportamento é o de sempre.
QUER_ID=0
[ "${1:-}" = "--id" ] && { QUER_ID=1; shift; }
MSG="${1:-}"
[ -z "$MSG" ] && exit 1
RESP=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=${MSG}" \
  --data-urlencode "parse_mode=HTML" \
  --data-urlencode "disable_web_page_preview=true")
[ "$QUER_ID" = "1" ] && printf '%s\n' "$(printf '%s' "$RESP" | jq -r '.result.message_id // empty')"
exit 0
