#!/bin/bash
# vivo_watch.sh — checa periodicamente se a instabilidade da operadora Vivo
# (relatada em 30/07/2026) já normalizou. Roda via cron a cada poucos minutos;
# quando detectar que voltou ao normal, avisa no Telegram e se autoremove do
# crontab (é um watch pontual, não recorrente como series/renewal).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
STATE="$DIR/state"
LOG="$STATE/vivo_watch.log"
mkdir -p "$STATE"

notify() {
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true" > /dev/null
}

PROMPT="Pesquise agora (use a data/hora atual) se a operadora de telecom Vivo (Telefônica Brasil) está passando por instabilidade, queda de sinal ou fora do ar significativa neste momento no Brasil (ex.: checar Downdetector Brasil, istheservicedown.com.br/status/vivo-brasil, noticias recentes). Havia um pico de relatos de problema em 30/07/2026 por volta das 9h45. Responda APENAS uma palavra: DOWN se ainda ha relatos relevantes de instabilidade agora, ou OK se os relatos voltaram ao normal / nao ha problema relevante no momento."

result=$(timeout 120 claude -p --model sonnet --dangerously-skip-permissions "$PROMPT" < /dev/null 2>>"$LOG" | tr '\n' ' ' | xargs)
echo "$(date '+%Y-%m-%d %H:%M') resultado: $result" >> "$LOG"

if echo "$result" | grep -qi "^OK"; then
  notify "✅ <b>Vivo normalizou</b>
Os relatos de instabilidade de hoje (30/07) parecem ter voltado ao normal."
  # autoremove este job do crontab (watch pontual, nao precisa continuar rodando)
  crontab -l 2>/dev/null | grep -v "vivo_watch.sh" | crontab -
  echo "$(date '+%Y-%m-%d %H:%M') — normalizado, removido do crontab" >> "$LOG"
fi
