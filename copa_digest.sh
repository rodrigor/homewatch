#!/bin/bash
# copa_digest.sh — digest diário da Copa do Mundo 2026 via Telegram
# Roda todo dia às 06:00 via cron
# Dados: ESPN public API (sem chave). Narrativa: claude CLI.

set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"

# Copa do Mundo 2026: 11/jun – 19/jul
FINAL_COPA="2026-07-19"
if [[ "$(date '+%Y-%m-%d')" > "$FINAL_COPA" ]]; then
  echo "Copa encerrada. Removendo cron..."
  (crontab -l 2>/dev/null | grep -v "copa_digest") | crontab -
  exit 0
fi

HOJE=$(date '+%Y%m%d')
ONTEM=$(date -d "yesterday" '+%Y%m%d')
HOJE_BR=$(date '+%d/%m/%Y')
ONTEM_BR=$(date -d "yesterday" '+%d/%m/%Y')

notify(){
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true" > /dev/null
}

# ---- busca jogos via ESPN ----
fetch_games(){
  local date="$1"
  curl -s --max-time 15 \
    "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=$date"
}

# ---- parse jogos -> texto ----
parse_games(){
  local json="$1" mode="$2"  # mode: resultado | agenda
  python3 -c "
import json, sys
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
data = json.loads('''$json'''.replace(\"'\", \"'\"))
events = data.get('events', [])
lines = []
for e in events:
    comp = e.get('competitions', [{}])[0]
    teams = comp.get('competitors', [])
    status_type = comp.get('status', {}).get('type', {}).get('name', '')
    status_desc = comp.get('status', {}).get('type', {}).get('description', '')
    if len(teams) < 2:
        continue
    home = next((t for t in teams if t.get('homeAway') == 'home'), teams[0])
    away = next((t for t in teams if t.get('homeAway') == 'away'), teams[1])
    h_name = home['team']['displayName']
    a_name = away['team']['displayName']
    h_score = home.get('score', '')
    a_score = away.get('score', '')
    # Hora BRT
    dt_str = e.get('date', '')
    hora = ''
    if dt_str:
        try:
            dt = datetime.fromisoformat(dt_str.replace('Z','+00:00')).astimezone(BRT)
            hora = dt.strftime('%H:%M')
        except:
            pass
    mode = '$mode'
    if mode == 'resultado':
        winner = ''
        if h_score and a_score:
            if int(h_score) > int(a_score): winner = f' ← {h_name}'
            elif int(a_score) > int(h_score): winner = f' ← {a_name}'
            else: winner = ' (empate)'
        lines.append(f'{h_name} {h_score} x {a_score} {a_name}{winner}')
    else:
        lines.append(f'{hora} BRT — {h_name} vs {a_name}')
print('\n'.join(lines) if lines else '(nenhum)')
" 2>/dev/null || echo "(erro ao processar)"
}

# ---- busca dados ----
JSON_ONTEM=$(fetch_games "$ONTEM")
JSON_HOJE=$(fetch_games "$HOJE")

RESULTADOS=$(parse_games "$JSON_ONTEM" "resultado")
AGENDA=$(parse_games "$JSON_HOJE" "agenda")

# ---- fato do dia via Claude ----
FATO=$(claude --dangerously-skip-permissions -p "Copa do Mundo 2026. Resultados de ontem ($ONTEM_BR): $RESULTADOS. Jogos de hoje ($HOJE_BR): $AGENDA. Escreva em PT-BR 2-3 linhas destacando algo interessante: surpresa, destaque individual, curiosidade ou situação na tabela. Sem título, sem markdown, só o texto simples." 2>/dev/null | head -4 || echo "")

# ---- monta mensagem ----
MSG="⚽ <b>Copa do Mundo 2026 — $HOJE_BR</b>

<b>📊 Ontem ($ONTEM_BR):</b>
$(echo "$RESULTADOS" | sed 's/^/• /')

<b>📅 Hoje:</b>
$(echo "$AGENDA" | sed 's/^/• /')"

if [ -n "$FATO" ]; then
  MSG="$MSG

<b>💡 Destaque:</b>
<i>$FATO</i>"
fi

notify "$MSG"
echo "$(date '+%Y-%m-%d %H:%M') — copa_digest enviado"
