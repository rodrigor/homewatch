#!/bin/bash
# apple_keynote_watch.sh — checa periodicamente se a Apple confirmou OFICIALMENTE
# a data do próximo keynote (evento de setembro/2026, linha iPhone). Rumor atual:
# 8 ou 9/set, mas sem confirmação oficial. Quando a Apple anunciar oficialmente
# (convite/press release), avisa no Telegram e se autoremove do crontab (watch
# pontual, não recorrente).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
STATE="$DIR/state"
LOG="$STATE/apple_keynote_watch.log"
mkdir -p "$STATE"

notify() {
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true" > /dev/null
}

PROMPT="Pesquise agora (use a data atual) se a Apple já ANUNCIOU OFICIALMENTE (convite de imprensa / press release / newsroom.apple.com — não rumor/vazamento de site de tecnologia) a data do proximo Apple Keynote/evento de produtos (esperado em setembro de 2026, provavel linha iPhone 18). Responda APENAS neste formato, sem mais nada: 'SIM: <data confirmada, ex. 9 de setembro de 2026>' se ja houver confirmacao OFICIAL da Apple, ou 'NAO' se ainda for so rumor/especulacao sem anuncio oficial."

result=$(timeout 120 claude -p --model sonnet --dangerously-skip-permissions "$PROMPT" < /dev/null 2>>"$LOG" | tr '\n' ' ' | xargs)
echo "$(date '+%Y-%m-%d %H:%M') resultado: $result" >> "$LOG"

if echo "$result" | grep -qi "^SIM"; then
  notify "🍎 <b>Apple confirmou a data do Keynote!</b>
$result"
  # autoremove este job do crontab (watch pontual)
  crontab -l 2>/dev/null | grep -v "apple_keynote_watch.sh" | crontab -
  echo "$(date '+%Y-%m-%d %H:%M') — confirmado, removido do crontab" >> "$LOG"
fi
