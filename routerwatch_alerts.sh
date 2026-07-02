#!/bin/bash
# routerwatch_alerts.sh — alerta no Telegram sobre o roteador (ER605 dual-WAN).
# Dispara só na MUDANÇA de estado (sem spam). Estado na tabela alert_state do DB.
# Cobre: Claro caiu/voltou, Vivo caiu/voltou, failover da rota default,
#        reboot, coletor parado, load alto.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DB="${ROUTERWATCH_DB:-/var/lib/routerwatch/routerwatch.db}"
LOAD_LIMIT="${LOAD_ALERT_LIMIT:-4.0}"   # ER605 = 4 núcleos

[ -f "$DB" ] || exit 0
sqlite3 "$DB" "CREATE TABLE IF NOT EXISTS alert_state (key TEXT PRIMARY KEY, value TEXT);"

get(){ sqlite3 "$DB" "SELECT value FROM alert_state WHERE key='$1';"; }
set_(){ sqlite3 "$DB" "INSERT INTO alert_state(key,value) VALUES('$1','$2') ON CONFLICT(key) DO UPDATE SET value=excluded.value;"; }
notify(){ "$DIR/tg_notify.sh" "$1" >/dev/null 2>&1 || true; }

# Última amostra
read -r TS CLARO VIVO LAN UP LOAD5 ACTIVE < <(sqlite3 -separator ' ' "$DB" \
  "SELECT ts,claro_oper,vivo_oper,lan_oper,uptime,COALESCE(load5,-1),COALESCE(active_wan,'') \
   FROM snap ORDER BY ts DESC LIMIT 1;")
[ -z "${TS:-}" ] && exit 0
NOW=$(date +%s); AGE=$(( NOW - TS ))

# 1) Coletor parado? (dados velhos > 3 min)
prev_coll=$(get collector); [ -z "$prev_coll" ] && prev_coll=ok
if [ "$AGE" -gt 180 ]; then
  if [ "$prev_coll" != stale ]; then
    notify "⚠️ <b>routerwatch parou de coletar</b>
Última amostra há $(( AGE/60 )) min."
    set_ collector stale
  fi
  exit 0
else
  [ "$prev_coll" = stale ] && notify "✅ <b>routerwatch voltou a coletar</b>"
  set_ collector ok
fi

# 2) Status de cada WAN (oper: 1=up, 2=down) — alerta por operadora
check_wan(){ # $1=nome $2=oper_atual $3=chave_estado
  local nome="$1" op="$2" key="$3" prev
  prev=$(get "$key"); [ -z "$prev" ] && prev="$op"   # 1ª vez: baseline
  if [ "$op" != "$prev" ]; then
    if [ "$op" = 2 ]; then notify "🔴 <b>$nome caiu</b>
Link da $nome sem conexão."
    elif [ "$op" = 1 ]; then notify "🟢 <b>$nome voltou</b>
Link da $nome restabelecido."; fi
  fi
  set_ "$key" "$op"
}
check_wan "Internet Claro" "$CLARO" claro_oper
check_wan "Internet Vivo"  "$VIVO"  vivo_oper

# 3) Failover: rota default (internet) mudou de operadora
prev_active=$(get active_wan); [ -z "$prev_active" ] && prev_active="$ACTIVE"
if [ -n "$ACTIVE" ] && [ "$ACTIVE" != "$prev_active" ]; then
  notify "🔀 <b>Failover de internet</b>
Rota padrão mudou de <b>${prev_active:-?}</b> para <b>${ACTIVE}</b>."
fi
set_ active_wan "$ACTIVE"

# 4) Roteador reiniciou (uptime caiu)
prev_up=$(get last_uptime)
if [ -n "$prev_up" ] && [ "$UP" -lt "$prev_up" ] 2>/dev/null; then
  notify "🔄 <b>Roteador reiniciou</b>
Uptime atual: $(( UP/100/60 )) min."
fi
set_ last_uptime "$UP"

# 5) Load average alto (load5 acima do limite)
if [ "$(awk -v l="$LOAD5" 'BEGIN{print (l>=0)?1:0}')" = 1 ]; then
  high=$(awk -v l="$LOAD5" -v lim="$LOAD_LIMIT" 'BEGIN{print (l>lim)?1:0}')
  prev_load=$(get load_high); [ -z "$prev_load" ] && prev_load=0
  if [ "$high" = 1 ] && [ "$prev_load" = 0 ]; then
    notify "🟠 <b>Roteador sobrecarregado</b>
Load (5 min): <b>$LOAD5</b> — acima de $LOAD_LIMIT (4 núcleos)."
    set_ load_high 1
  elif [ "$high" = 0 ] && [ "$prev_load" = 1 ]; then
    notify "✅ <b>Load normalizado</b>
Load (5 min): $LOAD5."
    set_ load_high 0
  fi
fi
