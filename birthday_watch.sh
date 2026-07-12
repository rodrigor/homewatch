#!/bin/bash
# birthday_watch.sh — avisa no Telegram (admin) os aniversariantes do dia.
# Roda todo dia as 09:00 via cron. Fonte: birthdays.json (MM-DD, sem ano —
# recorrente todo ano). Nao precisa de "fired"/estado: so dispara se a data
# bater com hoje.

set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
FILE="$DIR/birthdays.json"
TODAY=$(date '+%m-%d')

notify() {
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=HTML" > /dev/null
}

[ -f "$FILE" ] || exit 0

python3 -c "
import json
with open('$FILE') as f:
    data = json.load(f)
for b in data.get('birthdays', []):
    if b.get('date') == '$TODAY':
        label = f\" ({b['label']})\" if b.get('label') else ''
        print(b['name'] + label)
" | while IFS= read -r name; do
  [ -z "$name" ] && continue
  notify "🎂 <b>Aniversário hoje!</b>

$name está de aniversário hoje. Bora mandar um parabéns? 🎉"
done
