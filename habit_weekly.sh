#!/bin/bash
# habit_weekly.sh — retrospectiva semanal + atualização de streaks (roda toda segunda às 06:00)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

# Semana passada: segunda = hoje-7, domingo = hoje-1
last_mon=$(date -d "-7 days" +%Y-%m-%d)
last_sun=$(date -d "-1 day"  +%Y-%m-%d)
week_label=$(date -d "$last_mon" +"%d/%m")
week_end_label=$(date -d "$last_sun" +"%d/%m")

for person_dir in "$DIR/habits"/*/; do
    person=$(basename "$person_dir")
    has_habits=false
    all_done=true
    msg="📊 <b>Semana $week_label–$week_end_label, $person</b>"$'\n'$'\n'

    for f in "$person_dir"*.json; do
        [ -f "$f" ] || continue
        [ "$(jq -r .status "$f")" = "active" ] || continue
        has_habits=true

        name=$(jq -r .name "$f")
        target=$(jq -r .target_per_week "$f")
        streak=$(jq -r .streak_weeks "$f")

        cnt=$(jq --arg a "$last_mon" --arg b "$last_sun" \
            '[.log[]|select(.done and (.date>=$a) and (.date<=$b))]|length' "$f")

        metric=$(jq -r --arg a "$last_mon" --arg b "$last_sun" \
            '[.log[]|select(.done and (.date>=$a) and (.date<=$b) and (.value!=null) and (.unit!=""))]
             |group_by(.unit)|map("\(map(.value)|add|floor) \(.[0].unit)")|join(", ")' "$f" 2>/dev/null || true)

        bar=""
        for i in $(seq 1 "$target"); do
            if [ "$i" -le "$cnt" ]; then bar+="🟢"; else bar+="⚪"; fi
        done

        if [ "$cnt" -ge "$target" ]; then
            new_streak=$(( streak + 1 ))
            jq --argjson s "$new_streak" '.streak_weeks=$s' "$f" > "$f.tmp" && mv "$f.tmp" "$f"

            fire=""
            [ "$new_streak" -ge 2  ] && fire=" 🔥"
            [ "$new_streak" -ge 4  ] && fire=" 🔥🔥"
            [ "$new_streak" -ge 8  ] && fire=" 🔥🔥🔥"
            [ "$new_streak" -ge 12 ] && fire=" 👑"

            msg+="✅ <b>$name</b>: $bar$fire"$'\n'
            if [ -n "$metric" ] && [ "$metric" != "null" ]; then
                msg+="   📈 $metric na semana"$'\n'
            fi
            msg+="   Streak: <b>$new_streak semana(s)</b>"$'\n'$'\n'
        else
            all_done=false
            jq '.streak_weeks=0' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
            msg+="😅 <b>$name</b>: $bar ($cnt/$target)"$'\n'
            if [ "$streak" -gt 0 ]; then
                msg+="   Streak zerado (era $streak). Nova semana!"$'\n'
            else
                msg+="   Vamos tentar de novo essa semana 💪"$'\n'
            fi
            msg+=$'\n'
        fi
    done

    [ "$has_habits" = "true" ] || continue

    # Encorajamento final
    if [ "$all_done" = "true" ]; then
        msg+="🎯 <i>Todas as metas da semana cumpridas! Continue assim.</i>"
    else
        msg+="💡 <i>Dica: o segredo é não quebrar a sequência. Hoje já é um bom dia pra começar.</i>"
    fi

    case "$person" in
        Rodrigo) "$DIR/tg_notify.sh" "$msg" ;;
        Gabi)    "$DIR/notify_kids.sh" "$msg" "Gabi" ;;
        Ana)     "$DIR/notify_kids.sh" "$msg" "Ana" ;;
        Ayla)    "$DIR/notify_kids.sh" "$msg" "Ayla" ;;
    esac
done
