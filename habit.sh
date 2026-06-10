#!/bin/bash
# habit.sh — núcleo de hábitos (store JSON por pessoa). Subcomandos: create|log|status|list|adapt|show
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
H="$DIR/habits"
cmd="${1:-}"; shift || true

monday(){ local dow; dow=$(date +%u); date -d "-$((dow-1)) days" +%Y-%m-%d; }

find_habit(){ # <person> <id-or-substr-name> -> arquivo
  local p="$1" q="$2" f id name
  for f in "$H/$p"/*.json; do
    [ -f "$f" ] || continue
    id=$(jq -r .id "$f"); name=$(jq -r .name "$f")
    if [ "$id" = "$q" ] || printf '%s' "$name" | grep -qiF "$q"; then echo "$f"; return 0; fi
  done
  return 1
}

case "$cmd" in
  create) # <person> <type:weekly_count|daily> <target> <nome...>
    p="$1"; type="$2"; target="$3"; shift 3; name="$*"
    mkdir -p "$H/$p"
    id="h$(date +%s)$RANDOM"
    jq -n --arg id "$id" --arg p "$p" --arg t "$type" --argjson tg "${target:-1}" --arg n "$name" \
      '{id:$id,person:$p,type:$t,target_per_week:$tg,name:$n,channel:"telegram",cue_time:"",why:"",tiny:"",created:(now|floor),status:"active",log:[],streak_weeks:0,adaptations:[]}' \
      > "$H/$p/$id.json"
    echo "$id" ;;

  log) # <person> <id|nome> <valor|-> <unidade|-> [nota...]   (registra que FEZ + métrica)
    p="$1"; q="$2"; val="${3:--}"; unit="${4:--}"; shift 4 2>/dev/null || true; note="${*:-}"
    f=$(find_habit "$p" "$q") || { echo "habito nao encontrado"; exit 1; }
    today=$(date +%Y-%m-%d)
    if printf '%s' "$val" | grep -qE '^[0-9]+([.][0-9]+)?$'; then valj="$val"; else valj=null; fi
    [ "$unit" = "-" ] && unit=""
    jq --arg d "$today" --argjson v "$valj" --arg u "$unit" --arg note "$note" \
      '.log = ([.log[]|select(.date != $d)] + [{date:$d,done:true,value:$v,unit:$u,note:$note}])' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "ok" ;;

  skip) # <person> <id|nome> [nota...]   (registra que NÃO fez)
    p="$1"; q="$2"; shift 2; note="${*:-}"
    f=$(find_habit "$p" "$q") || { echo "habito nao encontrado"; exit 1; }
    today=$(date +%Y-%m-%d)
    jq --arg d "$today" --arg note "$note" \
      '.log = ([.log[]|select(.date != $d)] + [{date:$d,done:false,value:null,unit:"",note:$note}])' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "ok" ;;

  status) # <person> -> progresso da semana
    p="$1"; mon=$(monday)
    for f in "$H/$p"/*.json; do
      [ -f "$f" ] || continue
      [ "$(jq -r .status "$f")" = active ] || continue
      name=$(jq -r .name "$f"); tg=$(jq -r .target_per_week "$f"); strk=$(jq -r .streak_weeks "$f")
      cnt=$(jq --arg m "$mon" '[.log[]|select(.done and (.date>=$m))]|length' "$f")
      metric=$(jq -r --arg m "$mon" '[.log[]|select(.done and (.date>=$m) and (.value!=null) and (.unit!=""))]|group_by(.unit)|map("\(map(.value)|add) \(.[0].unit)")|join(", ")' "$f")
      echo "$name|$cnt|$tg|$strk|$(jq -r .id "$f")|$metric"
    done ;;

  list) # <person> ids
    p="$1"; for f in "$H/$p"/*.json; do [ -f "$f" ] && echo "$(jq -r .id "$f")  $(jq -r .name "$f")  [$(jq -r .status "$f")]"; done ;;

  show) # <person> <id|nome> -> json
    p="$1"; q="$2"; f=$(find_habit "$p" "$q") && jq . "$f" ;;

  adapt) # <person> <id|nome> <descricao da mudanca...>
    p="$1"; q="$2"; shift 2; desc="$*"
    f=$(find_habit "$p" "$q") || { echo "nao encontrado"; exit 1; }
    jq --arg d "$desc" --arg ts "$(date +%Y-%m-%d)" '.adaptations += [{date:$ts,change:$d}]' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "ok" ;;

  set) # <person> <id|nome> <campo> <valor>  (ex.: cue_time 18:00, target_per_week 3, why "...")
    p="$1"; q="$2"; field="$3"; shift 3; val="$*"
    f=$(find_habit "$p" "$q") || { echo "nao encontrado"; exit 1; }
    if printf '%s' "$val" | grep -qE '^[0-9]+$'; then jq --arg k "$field" --argjson v "$val" '.[$k]=$v' "$f" > "$f.tmp"; else jq --arg k "$field" --arg v "$val" '.[$k]=$v' "$f" > "$f.tmp"; fi
    mv "$f.tmp" "$f"; echo "ok" ;;

  *) echo "uso: habit.sh create|log|status|list|show|adapt|set ..." ; exit 1 ;;
esac
