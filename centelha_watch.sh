#!/bin/bash
# Verifica se a página do Centelha 3 PB ganhou link novo (ex.: resultado final da Fase 2).
# Compara contra um baseline de links já conhecidos; se achar link novo, avisa no Telegram
# e se remove do crontab (não precisa continuar rodando depois de avisar).
set -euo pipefail

URL="https://programacentelha.com.br/pb/"
STATE_DIR=/home/rodrigor/homewatch/state
BASELINE="$STATE_DIR/centelha_pb_links_baseline.txt"
DONE_FLAG="$STATE_DIR/centelha_fase2_resultado.flag"
NOTIFY=/home/rodrigor/homewatch/tg_notify.sh

mkdir -p "$STATE_DIR"
[ -f "$DONE_FLAG" ] && exit 0
[ -f "$BASELINE" ] || exit 0

HTML=$(curl -s -A "Mozilla/5.0" --max-time 20 "$URL") || exit 0
[ -n "$HTML" ] || exit 0

echo "$HTML" | grep -oE 'drive\.google\.com/file/d/[A-Za-z0-9_-]+' | sort -u > "$STATE_DIR/centelha_pb_links_current.txt"

NOVOS=$(comm -13 "$BASELINE" "$STATE_DIR/centelha_pb_links_current.txt" || true)

if [ -n "$NOVOS" ]; then
    touch "$DONE_FLAG"
    TRECHO=$(echo "$HTML" | grep -oi '[^<>]*resultado[^<>]*fase[^<>]*2[^<>]*' | sort -u | head -5)
    MSG="📢 <b>Mudou algo na página do Centelha 3 PB</b> (programacentelha.com.br/pb) — pode ser o resultado final da Fase 2.

Trechos encontrados:
${TRECHO}

Confira: ${URL}"
    "$NOTIFY" "$MSG" || true
    # já avisou, tira do crontab
    crontab -l 2>/dev/null | grep -v "centelha_watch.sh" | crontab -
fi
