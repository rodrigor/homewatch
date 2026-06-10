#!/bin/bash
# homewatch-watchdog.sh — monitora o homewatch-agent e reinicia se necessário
# Detecta dois cenários que o Restart=always do systemd NÃO pega:
#   1. Serviço simplesmente morreu (redundância extra ao systemd)
#   2. Loop travado: processo ainda vivo mas sem heartbeat há >HEARTBEAT_MAX segundos
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
STATE="$DIR/state"
HEARTBEAT_MAX="${WATCHDOG_HEARTBEAT_MAX:-300}"   # 5 min sem heartbeat = loop travado
POLL_INTERVAL="${WATCHDOG_POLL:-60}"             # verifica a cada 60s

tg(){
  curl -s -X POST "$API/sendMessage" \
    --data-urlencode "chat_id=$1" \
    --data-urlencode "text=$2" \
    --data-urlencode "disable_web_page_preview=true" >/dev/null
}

log(){
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$STATE/watchdog.log"
}

alert(){
  local msg="$1"
  log "ALERTA: $msg"
  [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "🔔 Watchdog: $msg" || true
}

restart_agent(){
  local reason="$1"
  alert "⚠️ $reason — reiniciando homewatch-agent..."
  sudo systemctl restart homewatch-agent.service
  sleep 8
  if systemctl is-active --quiet homewatch-agent.service; then
    alert "✅ homewatch-agent reiniciado com sucesso."
    log "Reinício OK após: $reason"
  else
    alert "❌ Falha ao reiniciar homewatch-agent! Intervenção manual necessária."
    log "FALHA no reinício após: $reason"
  fi
}

mkdir -p "$STATE"
log "Watchdog iniciado (heartbeat_max=${HEARTBEAT_MAX}s, poll=${POLL_INTERVAL}s)."

while true; do
  sleep "$POLL_INTERVAL"

  # 1. Serviço ativo?
  if ! systemctl is-active --quiet homewatch-agent.service; then
    restart_agent "homewatch-agent não estava ativo"
    continue
  fi

  # 2. Heartbeat fresco? (detecta loop travado com processo ainda vivo)
  if [ -f "$STATE/heartbeat" ]; then
    NOW=$(date +%s)
    LAST=$(cat "$STATE/heartbeat" 2>/dev/null || echo 0)
    DIFF=$((NOW - LAST))
    if [ "$DIFF" -gt "$HEARTBEAT_MAX" ]; then
      restart_agent "Loop travado há ${DIFF}s sem heartbeat"
    fi
  fi
done
