#!/bin/bash
# service_health.sh — Watchdog dos serviços PIrrai
# Detecta: serviço inativo/falho, travado em 'activating', HTTP fora do ar
# Alerta via Telegram e tenta reiniciar automaticamente
set -uo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/config.env" ] && source "$DIR/config.env"
STATE="$DIR/state"
mkdir -p "$STATE"

ALERT_COOLDOWN=1800   # só re-alerta o mesmo problema após 30 min
STUCK_MAX_SECS=180    # serviço em 'activating' por mais que isso = travado

# ── Serviços contínuos (devem estar sempre 'active running') ──────────────────
ALWAYS_ON=(
  "homewatch-agent.service:Agente Telegram"
  "homewatch-web.service:Painel dispositivos (8080)"
  "finance-web.service:Painel financeiro (8090)"
  "habit-web.service:Painel hábitos (8091)"
  "pirrai-landing.service:Landing page (80)"
)

# ── Serviços one-shot/timer (verificar se NÃO estão travados em activating) ──
ONESHOT=(
  "finance-email.service:E-mails financeiros:$STUCK_MAX_SECS"
  "finance-alerts.service:Alertas de limite:60"
  "email-watch.service:Monitor e-mails:60"
  "agenda-morning.service:Resumo matinal:120"
  "finance-backup.service:Backup financeiro:300"
)

# ── Endpoints HTTP (separador | para não conflitar com : das URLs) ────────────
HTTP_CHECKS=(
  "http://127.0.0.1:8090/|Painel financeiro"
  "http://127.0.0.1:8080/api/devices|API dispositivos"
  "http://127.0.0.1:8091/|Painel hábitos"
  "http://127.0.0.1:80/|Landing page"
)

# ── Helpers ────────────────────────────────────────────────────────────────────
notify(){
  local msg="$1"
  local sh="$DIR/tg_notify.sh"
  [ -f "$sh" ] && bash "$sh" "$msg" || true
}

# Cooldown: evita spam do mesmo alerta
should_alert(){
  local key="$1"
  local cf="$STATE/health_alert_${key//[^a-zA-Z0-9_]/_}.ts"
  local now; now=$(date +%s)
  local last=0
  [ -f "$cf" ] && last=$(cat "$cf")
  if [ $((now - last)) -gt $ALERT_COOLDOWN ]; then
    echo "$now" > "$cf"
    return 0   # pode alertar
  fi
  return 1     # ainda em cooldown
}

clear_alert(){
  local key="$1"
  local cf="$STATE/health_alert_${key//[^a-zA-Z0-9_]/_}.ts"
  rm -f "$cf"
}

service_state(){
  systemctl show "$1" --property=ActiveState --value 2>/dev/null || echo "unknown"
}

service_state_change_secs(){
  # segundos desde a última mudança de estado
  local ts
  ts=$(systemctl show "$1" --property=StateChangeTimestamp --value 2>/dev/null || echo "")
  [ -z "$ts" ] && echo 999999 && return
  local epoch; epoch=$(date -d "$ts" +%s 2>/dev/null || echo 0)
  echo $(( $(date +%s) - epoch ))
}

# ── 1. Serviços always-on ──────────────────────────────────────────────────────
problems=()
recoveries=()

for entry in "${ALWAYS_ON[@]}"; do
  svc="${entry%%:*}"; desc="${entry##*:}"
  state=$(service_state "$svc")
  if [ "$state" != "active" ]; then
    if should_alert "down_$svc"; then
      problems+=("🔴 <b>$desc</b> (<code>$svc</code>) — estado: <b>$state</b>\nTentando reiniciar...")
      sudo systemctl restart "$svc" 2>/dev/null || true
    fi
  else
    clear_alert "down_$svc"
  fi
done

# ── 2. Serviços one-shot: detectar travados em 'activating' ───────────────────
for entry in "${ONESHOT[@]}"; do
  IFS=':' read -r svc desc max_secs <<< "$entry"
  state=$(service_state "$svc")
  if [ "$state" = "activating" ]; then
    secs=$(service_state_change_secs "$svc")
    if [ "$secs" -gt "$max_secs" ]; then
      if should_alert "stuck_$svc"; then
        mins=$(( secs / 60 ))
        problems+=("⚠️ <b>$desc</b> (<code>$svc</code>) travado em <i>activating</i> há ${mins}min\nMatando e reiniciando...")
        sudo systemctl stop "$svc" 2>/dev/null || true
        sudo pkill -f "$(systemctl show "$svc" --property=ExecStart --value 2>/dev/null | awk '{print $1}')" 2>/dev/null || true
        sudo systemctl start "$svc" 2>/dev/null || true
      fi
    else
      clear_alert "stuck_$svc"
    fi
  else
    clear_alert "stuck_$svc"
  fi
done

# ── 3. Checks HTTP ─────────────────────────────────────────────────────────────
for entry in "${HTTP_CHECKS[@]}"; do
  url="${entry%%|*}"; desc="${entry##*|}"
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo "000")
  if [[ "$code" != 2* && "$code" != "301" && "$code" != "302" ]]; then
    if should_alert "http_$url"; then
      problems+=("🌐 <b>$desc</b> — HTTP $code (<code>$url</code>)")
    fi
  else
    clear_alert "http_$url"
  fi
done

# ── 4. Verificar se timers críticos não rodaram há muito tempo ─────────────────
check_timer_age(){
  local timer="$1" desc="$2" max_mins="$3"
  local last
  last=$(systemctl show "$timer" --property=LastTriggerUSec --value 2>/dev/null || echo "")
  [ -z "$last" ] || [ "$last" = "n/a" ] && return
  local epoch; epoch=$(date -d "$last" +%s 2>/dev/null || echo 0)
  [ "$epoch" -eq 0 ] && return
  local age_mins=$(( ( $(date +%s) - epoch ) / 60 ))
  if [ "$age_mins" -gt "$max_mins" ]; then
    if should_alert "timer_$timer"; then
      problems+=("⏰ <b>$desc</b> (<code>$timer</code>) não rodou há ${age_mins}min (limite: ${max_mins}min)")
    fi
  else
    clear_alert "timer_$timer"
  fi
}

check_timer_age "finance-email.timer"  "E-mails financeiros" 30
check_timer_age "finance-alerts.timer" "Alertas de limite"   75  # roda a cada 1h; tolerância de 15min
check_timer_age "email-watch.timer"    "Monitor e-mails"     10

# ── 5. Enviar alerta consolidado ───────────────────────────────────────────────
if [ ${#problems[@]} -gt 0 ]; then
  msg="🚨 <b>PIrrai Watchdog — Problemas detectados:</b>\n\n"
  for p in "${problems[@]}"; do
    msg+="$p\n\n"
  done
  msg+="<i>$(date '+%d/%m %H:%M')</i>"
  notify "$msg"
fi

exit 0
