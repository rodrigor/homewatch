#!/bin/bash
# parent_summary.sh — resumo diário do uso de tela das filhas, enviado ao admin (Rodrigo).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
export PATH="$HOME/.local/bin:$PATH"

DATA=""
for p in Ana Gabi; do
  DATA="$DATA
== $p ==
$("$DIR/screen_usage.sh" "$p" 2>/dev/null)"
done

PROMPT='Você escreve um resumo CURTO e direto para o pai (Rodrigo) sobre o uso de tela das filhas Ana (15) e Gabi (12) hoje. Tom de parceria, objetivo, SEM alarmismo.
Os dados vêm do Pi-hole (proxy): ACTIVE_TODAY = minutos ativos aprox. no dia; LAST90 = minutos ativos na última 1h30; CAT_* = tráfego por categoria; APP_* = tráfego por APP ESPECÍFICO (Instagram, YouTube, TikTok, WhatsApp, Spotify, Snapchat, etc.). IMPORTANTE: são iPHONES (Private Relay/DNS criptografado escondem boa parte), então os minutos SUBESTIMAM o uso real — deixe isso claro de leve. Ignore a categoria "outros" (ruído de sistema). Para cada filha: diga o tempo ativo aproximado e DESTAQUE OS APPS ESPECÍFICOS mais usados (ex.: "hoje foi bastante Instagram e YouTube"); sinalize se algum app de rede social/vídeo está claramente dominando o dia. Tom de parceria, sem alarmismo. Máximo 8 linhas, pt-BR, pode usar 1-2 emojis. Dados:'

REPORT=$(printf '%s\n%s' "$PROMPT" "$DATA" | claude -p --model sonnet 2>>"$DIR/state/summary.log")
[ -z "$REPORT" ] && REPORT="(não consegui gerar o resumo hoje)"

curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=📊 Resumo de tela das meninas (hoje)

$REPORT" >/dev/null
echo "resumo enviado"
