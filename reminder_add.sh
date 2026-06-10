#!/bin/bash
# reminder_add.sh <target> <time|presence> <quando> <mensagem...>
#  target: Gabi | Ana | Ayla | admin | all
#  time:     <quando> = datetime p/ `date -d` (ex.: "2026-06-10 18:00", "tomorrow 08:00", "18:00") ou epoch
#  presence: <quando> = "-" (dispara quando o aparelho do target chega na rede)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
F="$DIR/reminders.json"
[ -f "$F" ] || echo '[]' > "$F"
target="${1:-}"; type="${2:-}"; when="${3:-}"; shift 3 2>/dev/null || true; msg="$*"
[ -z "$target" ] || [ -z "$type" ] || [ -z "$msg" ] && { echo "uso: reminder_add.sh <target> <time|presence> <quando|-> <mensagem>"; exit 1; }
at=0
if [ "$type" = "time" ]; then
  if echo "$when" | grep -qE '^[0-9]{9,}$'; then at="$when"; else at=$(date -d "$when" +%s 2>/dev/null || echo ""); fi
  [ -z "$at" ] && { echo "ERRO: não entendi a data/hora '$when'"; exit 1; }
fi
id="r$(date +%s)$RANDOM"
jq --arg id "$id" --arg t "$target" --arg ty "$type" --argjson at "$at" --arg m "$msg" \
  '. += [{"id":$id,"target":$t,"type":$ty,"at":$at,"message":$m,"fired":false}]' "$F" > "$F.tmp" && mv "$F.tmp" "$F"
if [ "$type" = "time" ]; then
  echo "✓ lembrete $id: '$msg' para $target em $(date -d @"$at" '+%d/%m %H:%M')"
else
  echo "✓ lembrete $id: '$msg' para $target quando o aparelho de $target chegar na rede"
fi
