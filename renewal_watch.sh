#!/bin/bash
# renewal_watch.sh — monitora noticias de renovacao/data de estreia para series
# "paradas" (que terminaram a temporada atual e nao tem proximo episodio agendado
# na TVmaze), e tambem data de lancamento/mudancas de data para filmes aguardados
# (movies.json). Roda semanalmente via cron. So notifica quando a informacao MUDA
# em relacao ao que ja sabiamos (evita spam repetindo a mesma noticia).
#
# Usa `claude -p --dangerously-skip-permissions` (com WebSearch) pra checar o
# status atual e resumir em 1 linha. Compara com o ultimo status salvo em
# state/renewal/<prefixo><id>.txt; se mudou, avisa no Telegram e atualiza o arquivo.

set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
SERIES_FILE="$DIR/series.json"
MOVIES_FILE="$DIR/movies.json"
STATE="$DIR/state/renewal"
mkdir -p "$STATE"
LOG="$DIR/state/renewal_watch.log"

notify() {
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$1" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true" > /dev/null
}

check_one() {
  local statekey="$1" name="$2" prompt="$3" label="$4"
  local statefile="$STATE/${statekey}.txt"
  local last=""
  [ -f "$statefile" ] && last=$(cat "$statefile")

  local current
  current=$(timeout 120 claude -p --model sonnet --dangerously-skip-permissions "$prompt" < /dev/null 2>>"$LOG" | tr '\n' ' ' | xargs)

  if [ -z "$current" ]; then
    echo "  [$name] falha ao checar" >> "$LOG"
    return
  fi

  if [ "$current" != "$last" ]; then
    notify "🔔 <b>$label</b>

<b>$name</b>
$current"
    echo "$current" > "$statefile"
    echo "  [$name] MUDOU: $current" >> "$LOG"
  else
    echo "  [$name] sem mudanca" >> "$LOG"
  fi
}

echo "$(date '+%Y-%m-%d %H:%M') — renewal_watch iniciado" >> "$LOG"

# ---- series paradas (renovacao/proxima temporada) ----
python3 -c "
import json
with open('$SERIES_FILE') as f:
    data = json.load(f)
for s in data['series']:
    if s.get('watch_renewal') and s.get('status') in ('assistindo', 'quero ver'):
        print(str(s['id']) + '|' + s['name'] + '|' + s.get('platform',''))
" | while IFS='|' read -r id name platform; do
  [ -z "$id" ] && continue
  prompt="Pesquise na web o status MAIS RECENTE de renovacao/proxima temporada da serie de TV \"$name\" (plataforma: $platform). Responda em UMA UNICA LINHA, em portugues, curto (max ~200 caracteres), com: se foi renovada ou nao, e a data de estreia da proxima temporada se houver (ou a estimativa mais recente). NAO inclua fontes, links, citacoes ou a secao 'Sources' — so a linha de resumo, nada mais."
  check_one "s${id}" "$name" "$prompt" "Atualização de temporada!"
done

# ---- filmes aguardados (data de lancamento/mudancas) ----
if [ -f "$MOVIES_FILE" ]; then
  python3 -c "
import json
with open('$MOVIES_FILE') as f:
    data = json.load(f)
for m in data.get('movies', []):
    if m.get('watch_updates') and m.get('status') == 'aguardando':
        print(str(m['id']) + '|' + m['name'])
" | while IFS='|' read -r id name; do
    [ -z "$id" ] && continue
    prompt="Pesquise na web o status MAIS RECENTE da data de lancamento do filme \"$name\". Responda em UMA UNICA LINHA, em portugues, curto (max ~200 caracteres), com a data de estreia atual (confirmada ou rumor de mudanca, se houver). NAO inclua fontes, links, citacoes ou a secao 'Sources' — so a linha de resumo, nada mais."
    check_one "m${id}" "$name" "$prompt" "Atualização de filme!"
  done
fi

echo "$(date '+%Y-%m-%d %H:%M') — renewal_watch concluído" >> "$LOG"
