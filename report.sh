#!/bin/bash
# homewatch/report.sh — coleta -> análise (Claude) -> Telegram
# Uso: report.sh [janela] [--speedtest]   ex.: report.sh "1 day"
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
export PATH="$HOME/.local/bin:$PATH"
WINDOW="${1:-1 day}"
SPEEDTEST="${2:-}"
LOG="$DIR/state/last_run.log"

# 1) Coleta determinística
DATA="$("$DIR/collect.sh" "$WINDOW" $SPEEDTEST 2>>"$LOG")"

# 2) Análise pelo Claude (texto puro, sem ferramentas)
PROMPT='Você é o "PIrrai", um vigia doméstico que analisa dados de um Pi-hole e da rede de casa do usuário (família, pt-BR) e escreve um relatório CURTO e ÚTIL para o Telegram.

Regras:
- Português do Brasil, tom direto e amigável. Use emojis com moderação para escanear rápido.
- Máximo ~25 linhas. Vá ao que importa; não repita tabelas cruas.
- Estruture em: 🌐 Internet/Sistema (1-2 linhas, só se houver algo a dizer) · 🛡️ Pi-hole (volume bloqueado, % e destaques) · 📊 Dispositivos que mais consomem/rastreiam · 🚨 Alertas.
- ALERTAS (priorize): dispositivo NOVO desconhecido na rede; cliente batendo em MUITOS domínios de rastreio/ads distintos; domínios novos suspeitos (malware/tracker estranho); internet com perda de pacote/latência alta; disco>80%, temp>70C, throttle!=0x0, serviço falho.
- Para dispositivos, use o fabricante (macVendor) e o IP para dar nome humano provável (ex.: "iPhone (Apple .103)", "NAS Synology .150", "robô iRobot .102", "TV/Tuya .106").
- Se estiver tudo tranquilo, diga isso em 1 linha — não invente problema.
- Não use cabeçalho markdown (#). Pode usar *negrito* simples do Telegram.

Analise os DADOS BRUTOS abaixo e escreva só o relatório final.'

REPORT="$(printf '%s\n\n----\n%s\n' "$PROMPT" "$DATA" | claude -p --model "${CLAUDE_MODEL:-sonnet}" 2>>"$LOG")"

if [ -z "$REPORT" ]; then
  REPORT="⚠️ PIrrai: falha ao gerar relatório (Claude não retornou). Veja $LOG."
fi

# 3) Envia ao Telegram (divide em blocos de 4000 chars)
send_tg(){
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=Markdown" \
    --data-urlencode "disable_web_page_preview=true" >/dev/null
}
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
  echo "[homewatch] Telegram não configurado — relatório abaixo:"; echo "$REPORT"; exit 0
fi
MSG="🏠 *PIrrai* — $(date '+%d/%m %H:%M')
$REPORT"
# Telegram aceita até ~4096 chars/msg; envia em blocos se passar disso.
if [ "${#MSG}" -le 4000 ]; then
  send_tg "$MSG"
else
  printf '%s' "$MSG" | split -b 3900 - /tmp/hw_chunk_
  for f in /tmp/hw_chunk_*; do send_tg "$(cat "$f")"; done
  rm -f /tmp/hw_chunk_*
fi
echo "[homewatch] enviado ao Telegram ($(echo "$REPORT" | wc -l) linhas)."
