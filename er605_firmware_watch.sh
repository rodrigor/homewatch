#!/bin/bash
# er605_firmware_watch.sh — verifica semanalmente se saiu firmware novo para o
# roteador TP-Link Omada ER605 v2.20 (o roteador de casa, dual WAN Claro+Vivo).
# Avisa no Telegram quando a versão mais recente publicada mudar.
#
# A página do fabricante é HTML estático o bastante para o curl — não precisa de
# navegador nem de LLM. Se a estrutura mudar e nada casar com o padrão de versão,
# o script avisa UMA vez e não mexe no estado (falha visível, não silenciosa).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
STATE_DIR="$DIR/state"
STATE="$STATE_DIR/er605_firmware.txt"
LOG="$STATE_DIR/er605_firmware_watch.log"
mkdir -p "$STATE_DIR"

URL="https://support.omadanetworks.com/en/download/firmware/er605/v2.20/"
# Versão instalada no roteador. ATUALIZAR AQUI depois de aplicar um upgrade.
INSTALADA="2.4.5 Build 20260721"

log() { echo "$(date '+%Y-%m-%d %H:%M') $*" >> "$LOG"; }

notify() {
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true" > /dev/null
}

html=$(curl -sL -m 40 -A "Mozilla/5.0 (X11; Linux aarch64)" "$URL" 2>>"$LOG")
if [ -z "$html" ]; then
  log "ERRO: download vazio"
  exit 1
fi

# Todas as versões da página, ordenadas pela data de build (a maior é a mais nova).
LATEST=$(printf '%s' "$html" \
  | grep -oE '[0-9]+\.[0-9]+\.[0-9]+ Build [0-9]{8}' \
  | sort -u \
  | sort -t' ' -k3,3n \
  | tail -1)

if [ -z "$LATEST" ]; then
  # Estrutura da página mudou. Avisa uma vez só, sem gravar estado.
  if [ ! -f "$STATE_DIR/.er605_parse_fail" ]; then
    touch "$STATE_DIR/.er605_parse_fail"
    notify "⚠️ <b>ER605 firmware watch</b>
Não consegui extrair a versão da página do fabricante — o layout deve ter mudado.
Conferir manualmente: $URL"
  fi
  log "ERRO: nenhuma versão casou com o padrão"
  exit 1
fi
rm -f "$STATE_DIR/.er605_parse_fail"

ANTERIOR=$(cat "$STATE" 2>/dev/null || echo "")
log "instalada='$INSTALADA' publicada='$LATEST' anterior='$ANTERIOR'"

if [ "$LATEST" = "$ANTERIOR" ]; then
  exit 0
fi

echo "$LATEST" > "$STATE"

if [ "$LATEST" = "$INSTALADA" ]; then
  log "publicada == instalada, sem aviso"
  exit 0
fi

notify "🛜 <b>Firmware novo para o ER605</b>

Instalada:  <code>${INSTALADA}</code>
Publicada:  <code>${LATEST}</code>

Download: ${URL}
Upgrade em System Tools → Firmware Upgrade (upload manual do arquivo).

<i>Depois de atualizar, editar INSTALADA em er605_firmware_watch.sh.</i>"
log "avisado: $LATEST"
