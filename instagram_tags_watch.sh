#!/bin/bash
# instagram_tags_watch.sh: avisa no Telegram quando alguém marca o @ayty.ufpb num post ou reel.
# A API da Meta não reposta; o aviso traz o link para o Rodrigo repostar pelo app.
# Cron: 0 8-22/2 * * *   Estado: state/instagram_tags_seen.json (1ª execução só registra, sem avisar).
DIR="$(cd "$(dirname "$0")" && pwd)"
IG="$HOME/.claude/skills/instagram/ig.py"
STATE_F="$DIR/state/instagram_tags_seen.json"
OUT=$(python3 "$IG" tags --new "$STATE_F" 2>&1) || { echo "[$(date '+%F %T')] erro: $OUT"; exit 1; }
[ -z "$OUT" ] && exit 0
FMT='
import sys, json, html
m = json.load(sys.stdin)
e = html.escape
linhas = ["📌 <b>@%s</b> marcou o AYTY num %s (%s)" % (e(m["username"] or "?"), e(m["tipo"]), m["data"])]
if m["legenda"]:
    linhas.append("<i>%s</i>" % e(m["legenda"]))
linhas.append(e(m["link"] or ""))
linhas.append("Para repostar: abra o link no app e toque em Repostar.")
print("\n".join(linhas))
'
while IFS= read -r linha; do
  MSG=$(printf '%s' "$linha" | python3 -c "$FMT") || { echo "[$(date '+%F %T')] erro ao formatar: $linha"; continue; }
  "$DIR/tg_notify.sh" "$MSG"
  echo "[$(date '+%F %T')] avisado: $linha"
done <<< "$OUT"
