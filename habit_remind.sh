#!/bin/bash
# habit_remind.sh — lembretes de hábitos por cue_time + check-in de domingo às 20h
# Roda a cada 30 min via cron: */30 * * * *
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

today=$(date +%Y-%m-%d)
now_hm=$(date +%H:%M)
now_h=$(date +%H)
now_m_raw=$(date +%M)
now_m=$(echo "$now_m_raw" | sed 's/^0*//' || echo 0)
dow=$(date +%u)   # 1=seg … 7=dom

# Converte HH:MM → minutos desde meia-noite
to_min(){ local h m; IFS=: read -r h m <<< "$1"; echo $(( 10#$h * 60 + 10#$m )); }

now_min=$(to_min "$now_hm")

# ──────────────────────────────────────────────
# 1. LEMBRETE POR cue_time
# ──────────────────────────────────────────────
for person_dir in "$DIR/habits"/*/; do
    person=$(basename "$person_dir")
    # Mapeamento de pessoa → canal de notificação
    case "$person" in
        Rodrigo) notify_cmd=("$DIR/tg_notify.sh") ;;
        Gabi)    notify_cmd=("$DIR/notify_kids.sh" "" "Gabi") ;;
        Ana)     notify_cmd=("$DIR/notify_kids.sh" "" "Ana") ;;
        Ayla)    notify_cmd=("$DIR/notify_kids.sh" "" "Ayla") ;;
        *)       continue ;;
    esac

    for f in "$person_dir"*.json; do
        [ -f "$f" ] || continue
        status_h=$(jq -r .status "$f")
        [ "$status_h" = "active" ] || continue

        cue_time=$(jq -r '.cue_time // ""' "$f")
        [ -z "$cue_time" ] || [ "$cue_time" = "null" ] && continue

        cue_min=$(to_min "$cue_time")
        diff=$(( now_min - cue_min ))
        [ $diff -lt 0 ] && diff=$(( -diff ))
        [ $diff -gt 15 ] && continue   # fora da janela de ±15 min

        # Verificar cue_days (se definido): [1=seg,2=ter,3=qua,4=qui,5=sex,6=sab,7=dom]
        cue_days=$(jq -r '.cue_days // [] | length' "$f")
        if [ "$cue_days" -gt 0 ]; then
            dow=$(date +%u)  # dia da semana atual
            day_ok=$(jq --argjson d "$dow" '.cue_days | map(. == $d) | any' "$f")
            [ "$day_ok" != "true" ] && continue
        fi

        # Anti-duplo: não dispara mais de uma vez por hora
        cue_h="${cue_time%%:*}"
        flag="/tmp/habit_remind_${person}_$(jq -r .id "$f")_${today}_${cue_h}.flag"
        [ -f "$flag" ] && continue
        touch "$flag"

        # Já foi feito hoje? Não lembra então.
        done_today=$(jq -r --arg d "$today" '.log[]|select(.date==$d and .done==true)|.date' "$f" 2>/dev/null | head -1)
        [ -n "$done_today" ] && continue

        name=$(jq -r .name "$f")
        tiny=$(jq -r '.tiny // ""' "$f")
        target=$(jq -r .target_per_week "$f")
        # Progresso da semana
        mon=$(date -d "-$(( $(date +%u) - 1 )) days" +%Y-%m-%d)
        cnt=$(jq --arg m "$mon" '[.log[]|select(.done and (.date>=$m))]|length' "$f")

        bar=""
        for i in $(seq 1 "$target"); do
            if [ "$i" -le "$cnt" ]; then bar+="🟢"; else bar+="⚪"; fi
        done

        msg="⏰ <b>Hora do $name!</b> $bar ($cnt/$target esta semana)"
        if [ -n "$tiny" ] && [ "$tiny" != "null" ]; then
            msg+=$'\n'"💡 <i>$tiny</i>"
        fi

        if [ "$person" = "Rodrigo" ]; then
            "${notify_cmd[@]}" "$msg"
        else
            "${notify_cmd[0]}" "$msg" "${notify_cmd[2]}"
        fi
    done
done

# ──────────────────────────────────────────────
# 2. CHECK-IN DE DOMINGO 20:00 → 20:29
# ──────────────────────────────────────────────
if [ "$dow" = "7" ] && [ "$now_h" = "20" ] && [ "${now_m:-0}" -lt 30 ]; then
    flag_sun="/tmp/habit_sunday_checkin_${today}.flag"
    if [ ! -f "$flag_sun" ]; then
        touch "$flag_sun"
        mon=$(date -d "-6 days" +%Y-%m-%d)   # segunda desta semana

        for person_dir in "$DIR/habits"/*/; do
            person=$(basename "$person_dir")
            has_habits=false
            msg="🗓️ <b>Semana quase acabando, $person!</b>"$'\n'

            for f in "$person_dir"*.json; do
                [ -f "$f" ] || continue
                [ "$(jq -r .status "$f")" = "active" ] || continue
                name=$(jq -r .name "$f")
                target=$(jq -r .target_per_week "$f")
                cnt=$(jq --arg m "$mon" '[.log[]|select(.done and (.date>=$m))]|length' "$f")
                streak=$(jq -r .streak_weeks "$f")
                has_habits=true

                bar=""
                for i in $(seq 1 "$target"); do
                    if [ "$i" -le "$cnt" ]; then bar+="🟢"; else bar+="⚪"; fi
                done

                if [ "$cnt" -ge "$target" ]; then
                    msg+="✅ <b>$name</b>: $bar — meta batida!"$'\n'
                else
                    rest=$(( target - cnt ))
                    msg+="⚡ <b>$name</b>: $bar — falta $rest para fechar"$'\n'
                fi
                [ "$streak" -gt 0 ] && msg+="   🔥 Streak atual: $streak semana(s)"$'\n'
            done

            [ "$has_habits" = "true" ] || continue

            case "$person" in
                Rodrigo) "$DIR/tg_notify.sh" "$msg" ;;
                Gabi)    "$DIR/notify_kids.sh" "$msg" "Gabi" ;;
                Ana)     "$DIR/notify_kids.sh" "$msg" "Ana" ;;
                Ayla)    "$DIR/notify_kids.sh" "$msg" "Ayla" ;;
            esac
        done
    fi
fi
