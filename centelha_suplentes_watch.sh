#!/bin/bash
# Verifica se a página do Centelha 3 PB ganhou link novo (lista de suplentes/fila de espera
# da Fase 2). Compara contra o baseline capturado em 02/10/2026 (dia da divulgação do resultado
# final). Pensado para rodar via cron só na janela 04-09/01/2027, 4x/dia (9h/12h/15h/18h).
# Chamar com "--eod" na rodada das 18h: nesse horário, se não mudou nada, avisa "sem mudança"
# mesmo assim (resumo do fim do dia). Nas outras rodadas, só avisa se mudou algo.
set -euo pipefail

EOD=0
[ "${1:-}" = "--eod" ] && EOD=1

URL="https://programacentelha.com.br/pb/"
STATE_DIR=/home/rodrigor/homewatch/state
BASELINE="$STATE_DIR/centelha_pb_links_baseline_suplentes.txt"
DONE_FLAG="$STATE_DIR/centelha_suplentes_resultado.flag"
NOTIFY=/home/rodrigor/homewatch/tg_notify.sh

mkdir -p "$STATE_DIR"
[ -f "$DONE_FLAG" ] && exit 0
[ -f "$BASELINE" ] || exit 0

HTML=$(curl -s -A "Mozilla/5.0" --max-time 20 "$URL") || exit 0
if [ -z "$HTML" ]; then
    [ "$EOD" = 1 ] && "$NOTIFY" "⚠️ Centelha PB: não consegui carregar a página às 18h pra conferir a lista de suplentes. Tento de novo amanhã." || true
    exit 0
fi

echo "$HTML" | grep -oE 'drive\.google\.com/file/d/[A-Za-z0-9_-]+' | sort -u > "$STATE_DIR/centelha_pb_links_current_suplentes.txt"

NOVOS=$(comm -13 "$BASELINE" "$STATE_DIR/centelha_pb_links_current_suplentes.txt" || true)

if [ -n "$NOVOS" ]; then
    touch "$DONE_FLAG"
    TRECHO=$(echo "$HTML" | grep -oiE '[^<>]*(suplente|lista de espera|chamada)[^<>]*' | sort -u | head -8)
    MSG="📢 <b>A página do Centelha 3 PB mudou</b> (programacentelha.com.br/pb) — pode ser a chamada de suplentes.

Trechos encontrados:
${TRECHO:-"(nenhum trecho com 'suplente'/'chamada' encontrado, mas apareceu link novo)"}

Confira: ${URL}"
    "$NOTIFY" "$MSG" || true
    # já avisou, tira do crontab
    crontab -l 2>/dev/null | grep -v "centelha_suplentes_watch.sh" | crontab -
elif [ "$EOD" = 1 ]; then
    "$NOTIFY" "🔎 Centelha PB: conferi às 18h, o site ainda não foi atualizado com a lista de suplentes. Sigo checando amanhã." || true
fi
