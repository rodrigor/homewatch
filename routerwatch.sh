#!/usr/bin/env bash
# routerwatch — coletor SNMPv3 do roteador (TP-Link ER605, dual-WAN)
# Mede Claro (WAN) e Vivo (WAN/LAN1) separadamente + LAN, via subinterfaces VLAN.
# Snapshot cru por execução; taxas (bps) calculadas no Grafana via LAG().
set -euo pipefail
export LC_ALL=C   # ponto decimal (não vírgula pt-BR) em awk/printf

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$DIR/routerwatch.env"
# Banco fora do homewatch (700) p/ o Grafana ler via grupo 'grafana'.
DB="${ROUTERWATCH_DB:-/var/lib/routerwatch/routerwatch.db}"

[[ -f "$ENV_FILE" ]] || { echo "routerwatch: falta $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"

SNMP=(-v3 -l "${SNMP_SEC_LEVEL}" -u "${SNMP_USER}" -a "${SNMP_AUTH_PROTO}" -A "${SNMP_AUTH_PASS}")
H="${ROUTER_HOST}"
CL="${IFINDEX_CLARO}"   # Claro  (WAN dedicada)
VI="${IFINDEX_VIVO}"    # Vivo   (WAN/LAN1)
LN="${IFINDEX_LAN}"     # LAN

# --- schema ---
sqlite3 "$DB" <<'SQL'
PRAGMA journal_mode=DELETE;
CREATE TABLE IF NOT EXISTS snap (
  ts          INTEGER PRIMARY KEY,        -- unix epoch (segundos)
  claro_in    INTEGER, claro_out  INTEGER, claro_oper INTEGER, claro_inerr INTEGER,
  vivo_in     INTEGER, vivo_out   INTEGER, vivo_oper  INTEGER, vivo_inerr  INTEGER,
  lan_in      INTEGER, lan_out    INTEGER, lan_oper   INTEGER,
  cpu         REAL,    mem_pct    REAL,
  load1       REAL,    load5      REAL,    load15     REAL,
  uptime      INTEGER,
  active_wan  TEXT                          -- claro | vivo | <ip> (rota default atual)
);
SQL

# OIDs por interface: ifHCInOctets(.6) ifHCOutOctets(.10) ifOperStatus(.8) ifInErrors(.14 em ifTable)
HCIN=1.3.6.1.2.1.31.1.1.1.6;  HCOUT=1.3.6.1.2.1.31.1.1.1.10
OPER=1.3.6.1.2.1.2.2.1.8;     INERR=1.3.6.1.2.1.2.2.1.14

# Uma consulta para todos os contadores das 3 interfaces + uptime
OUT=$(snmpget "${SNMP[@]}" -Oqvt "$H" \
  $HCIN.$CL $HCOUT.$CL $OPER.$CL $INERR.$CL \
  $HCIN.$VI $HCOUT.$VI $OPER.$VI $INERR.$VI \
  $HCIN.$LN $HCOUT.$LN $OPER.$LN \
  1.3.6.1.2.1.1.3.0 2>/dev/null) || { echo "routerwatch: snmpget falhou" >&2; exit 2; }

mapfile -t V <<<"$OUT"
CLARO_IN="${V[0]}";  CLARO_OUT="${V[1]}";  CLARO_OPER="${V[2]}";  CLARO_INERR="${V[3]}"
VIVO_IN="${V[4]}";   VIVO_OUT="${V[5]}";   VIVO_OPER="${V[6]}";   VIVO_INERR="${V[7]}"
LAN_IN="${V[8]}";    LAN_OUT="${V[9]}";    LAN_OPER="${V[10]}"
UPTIME="${V[11]}"    # timeticks (1/100 s)

# CPU = média do hrProcessorLoad entre os núcleos
CPU=$(snmpwalk "${SNMP[@]}" -Oqv "$H" 1.3.6.1.2.1.25.3.3.1.2 2>/dev/null \
      | awk '{s+=$1; n++} END{ if(n>0) printf "%.1f", s/n; else print "" }')

# Memória (UCD): (total - disponível)/total * 100
MTOTAL=$(snmpget "${SNMP[@]}" -Oqv "$H" 1.3.6.1.4.1.2021.4.5.0 2>/dev/null || echo "")
MAVAIL=$(snmpget "${SNMP[@]}" -Oqv "$H" 1.3.6.1.4.1.2021.4.6.0 2>/dev/null || echo "")
MEM_PCT=$(awk -v a="$MAVAIL" -v t="$MTOTAL" 'BEGIN{ if(t+0>0) printf "%.1f", (t-a)/t*100 }')

# Load average 1/5/15 (UCD laLoad)
read -r LOAD1 LOAD5 LOAD15 < <(snmpget "${SNMP[@]}" -Oqv "$H" \
  1.3.6.1.4.1.2021.10.1.3.1 1.3.6.1.4.1.2021.10.1.3.2 1.3.6.1.4.1.2021.10.1.3.3 \
  2>/dev/null | tr -d '"' | paste -sd' ')

# WAN ativa = nexthop da rota default (0.0.0.0). Mapeia gateway -> operadora.
GW=$(snmpget "${SNMP[@]}" -Oqv "$H" 1.3.6.1.2.1.4.21.1.7.0.0.0.0 2>/dev/null | tr -d '"')
case "$GW" in
  "${GW_CLARO:-192.168.15.1}") ACTIVE_WAN=claro ;;
  "${GW_VIVO:-192.168.21.1}")  ACTIVE_WAN=vivo  ;;
  "")                          ACTIVE_WAN="" ;;
  *)                           ACTIVE_WAN="$GW" ;;
esac

TS=$(date +%s)
q(){ [ -n "$1" ] && printf "%s" "$1" || printf "NULL"; }   # valor ou NULL
s(){ [ -n "$1" ] && printf "'%s'" "$1" || printf "NULL"; } # string ou NULL

sqlite3 "$DB" "INSERT OR REPLACE INTO snap
 (ts,claro_in,claro_out,claro_oper,claro_inerr,vivo_in,vivo_out,vivo_oper,vivo_inerr,
  lan_in,lan_out,lan_oper,cpu,mem_pct,load1,load5,load15,uptime,active_wan)
 VALUES ($TS,
  $(q "$CLARO_IN"),$(q "$CLARO_OUT"),$(q "$CLARO_OPER"),$(q "$CLARO_INERR"),
  $(q "$VIVO_IN"),$(q "$VIVO_OUT"),$(q "$VIVO_OPER"),$(q "$VIVO_INERR"),
  $(q "$LAN_IN"),$(q "$LAN_OUT"),$(q "$LAN_OPER"),
  $(q "$CPU"),$(q "$MEM_PCT"),$(q "$LOAD1"),$(q "$LOAD5"),$(q "$LOAD15"),
  $(q "$UPTIME"),$(s "$ACTIVE_WAN"));"

# Retenção
if [[ "${RETENTION_DAYS:-0}" -gt 0 ]]; then
  sqlite3 "$DB" "DELETE FROM snap WHERE ts < $(( TS - RETENTION_DAYS*86400 ));"
fi
