#!/bin/bash
# check_new_episodes.sh — verifica novos episódios via TVmaze API
# Roda via cron diariamente. Notifica via Telegram se houver ep novo.

set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
FILE="$DIR/series.json"
TODAY=$(date '+%Y-%m-%d')
STATE="$DIR/state"
MAP_FILE="$STATE/episode_notify_map.json"
mkdir -p "$STATE"
[ -f "$MAP_FILE" ] || echo '{}' > "$MAP_FILE"

notify() {
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true" > /dev/null
}

# notify_track <texto> <series_id> <nome> <episodio>
# Igual notify(), mas guarda o message_id retornado associado à série/episódio,
# pra permitir marcar como assistido depois via reação 👍 no Telegram
# (ver telegram_agent.sh / mark_episode_watched).
notify_track() {
  local text="$1" sid="$2" name="$3" ep="$4" resp mid
  resp=$(curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$text" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true")
  mid=$(echo "$resp" | jq -r '.result.message_id // empty')
  [ -z "$mid" ] && return 0
  python3 - "$MAP_FILE" "$mid" "$sid" "$name" "$ep" <<'PYEOF'
import json, sys
path, mid, sid, name, ep = sys.argv[1:6]
try:
    d = json.load(open(path))
except Exception:
    d = {}
d[mid] = {"series_id": int(sid), "name": name, "episode": ep}
json.dump(d, open(path, "w"), ensure_ascii=False, indent=2)
PYEOF
}

# Busca ID do show no TVmaze por nome (retorna id|nome_oficial)
tvmaze_search() {
  local name="$1"
  curl -s --max-time 10 \
    "https://api.tvmaze.com/singlesearch/shows?q=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$name")" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(str(d.get('id','0'))+'|'+d.get('name',''))" 2>/dev/null || echo "0|"
}

# Retorna último ep já exibido (S01E05) e próximo ep agendado (S01E06|titulo|2026-06-12)
tvmaze_episodes() {
  local show_id="$1" t="$TODAY"
  curl -s --max-time 10 "https://api.tvmaze.com/shows/$show_id/episodes" \
    | python3 -c "
import json,sys
today='$t'
eps=json.load(sys.stdin)
aired=[e for e in eps if (e.get('airdate') or '')<=today and e.get('airdate')]
future=[e for e in eps if (e.get('airdate') or '')>today and e.get('airdate')]
last=aired[-1] if aired else None
nxt=future[0] if future else None
print('S{:02d}E{:02d}'.format(last['season'],last['number']) if last else '')
print('S{:02d}E{:02d}|{}|{}'.format(nxt['season'],nxt['number'],nxt['name'],nxt['airdate']) if nxt else '')
" 2>/dev/null || echo -e "\n"
}

# Compara dois episódios (ep_gt A B → A > B)
ep_gt() {
  local as ae bs be
  as=$(echo "$1" | sed 's/S0*\([0-9]*\)E.*/\1/'); ae=$(echo "$1" | sed 's/.*E0*\([0-9]*\)/\1/')
  bs=$(echo "$2" | sed 's/S0*\([0-9]*\)E.*/\1/'); be=$(echo "$2" | sed 's/.*E0*\([0-9]*\)/\1/')
  [ "${as:-0}" -gt "${bs:-0}" ] && return 0
  [ "${as:-0}" -eq "${bs:-0}" ] && [ "${ae:-0}" -gt "${be:-0}" ] && return 0
  return 1
}

# Lista séries com notify_new=true e status=assistindo
python3 -c "
import json
with open('$FILE') as f:
    data = json.load(f)
for s in data['series']:
    if s.get('notify_new') and s.get('status') == 'assistindo':
        print('|'.join([str(s['id']), s['name'], s.get('last_episode',''), str(s.get('tvmaze_id',0))]))
" | while IFS='|' read -r sid name last_ep tvmaze_id; do

  # Resolve tvmaze_id se não tiver
  if [ "${tvmaze_id:-0}" = "0" ]; then
    result=$(tvmaze_search "$name")
    tvmaze_id="${result%%|*}"
    if [ "${tvmaze_id:-0}" != "0" ]; then
      python3 - <<PYEOF
import json
with open('$FILE') as f:
    data = json.load(f)
for s in data['series']:
    if s['name'] == '$name':
        s['tvmaze_id'] = $tvmaze_id
with open('$FILE', 'w') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PYEOF
    fi
  fi

  [ "${tvmaze_id:-0}" = "0" ] && echo "Aviso: não encontrei '$name' no TVmaze" && continue

  # Busca episódios
  ep_info=$(tvmaze_episodes "$tvmaze_id")
  latest=$(echo "$ep_info" | sed -n '1p')
  next_raw=$(echo "$ep_info" | sed -n '2p')

  # Notifica se há ep novo além do que o usuário assistiu
  if [ -n "$latest" ] && { [ -z "$last_ep" ] || ep_gt "$latest" "$last_ep"; }; then
    notify_track "📺 <b>Novo episódio disponível!</b>

<b>$name</b> — <b>$latest</b>
Você estava em: <i>${last_ep:-início}</i> 🍿
(dê 👍 nesta mensagem quando assistir, pra eu marcar sozinho)" "$sid" "$name" "$latest"
  fi

  # Notifica sobre próximo ep agendado (apenas uma vez por ep, no dia do lançamento)
  if [ -n "$next_raw" ]; then
    next_ep="${next_raw%%|*}"
    next_rest="${next_raw#*|}"
    next_title="${next_rest%%|*}"
    next_date="${next_rest##*|}"
    if [ "$next_date" = "$TODAY" ]; then
      notify_track "📅 <b>Hoje estreia novo episódio!</b>

<b>$name</b> — <b>$next_ep</b>: <i>$next_title</i>
Plataforma: Paramount+ 🎬
(dê 👍 nesta mensagem quando assistir, pra eu marcar sozinho)" "$sid" "$name" "$next_ep"
    fi
  fi

done

echo "$(date '+%Y-%m-%d %H:%M') — check_new_episodes concluído"
