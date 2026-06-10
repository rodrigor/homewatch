#!/bin/bash
# notify_kids.sh "<mensagem>" [Nome|all] — envia recado dos pais para as filhas no Telegram
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
MSG="${1:-}"; WHO="${2:-all}"
[ -z "$MSG" ] && { echo "uso: notify_kids.sh \"mensagem\" [Gabi|Ana|all]"; exit 1; }
send(){ curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=$1" --data-urlencode "text=$2" >/dev/null; }
sent=0
while read -r cid name; do
  [ -z "${cid:-}" ] && continue
  if [ "$WHO" = "all" ] || [ "$(echo "$WHO" | tr A-Z a-z)" = "$(echo "$name" | tr A-Z a-z)" ]; then
    send "$cid" "💌 Recado do papai: $MSG"
    echo "enviado para $name"; sent=$((sent+1))
  fi
done < "$DIR/kids/registry.txt"
echo "total enviado: $sent"
