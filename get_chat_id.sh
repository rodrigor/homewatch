#!/bin/bash
# Descobre o chat_id: rode DEPOIS de mandar qualquer mensagem ("oi") para o seu bot no Telegram.
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/config.env"
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then echo "Defina TELEGRAM_BOT_TOKEN em config.env primeiro."; exit 1; fi
echo "Buscando atualizações do bot..."
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates" \
 | jq -r '.result[].message | "chat_id=\(.chat.id)  de: \(.chat.first_name // .chat.title)  texto: \(.text)"' \
 | tail -5
echo "---"
echo "Pegue o chat_id acima e cole em config.env (TELEGRAM_CHAT_ID)."
