#!/usr/bin/env bash
# routerspeed.sh — teste de velocidade por operadora (dual-WAN).
# Amarra cada teste a um IP de origem; o ER605 (Policy Routing) roteia
# cada origem por uma WAN. Grava download/upload/ping no SQLite.
#
# Uso:
#   routerspeed.sh           roda os testes e grava no banco
#   routerspeed.sh check     só mostra o IP público de cada origem (validação)
set -uo pipefail
export LC_ALL=C
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$DIR/routerwatch.env"
DB="${ROUTERWATCH_DB:-/var/lib/routerwatch/routerwatch.db}"
# shellcheck disable=SC1090
source "$ENV_FILE"

SRC_CLARO="${SPEEDTEST_SRC_CLARO:-192.168.54.60}"
SRC_VIVO="${SPEEDTEST_SRC_VIVO:-192.168.54.61}"
# Ookla CLI oficial (satura gigabit; amarra por IP de origem com --ip).
OOKLA="${SPEEDTEST_BIN:-/usr/local/bin/speedtest-ookla}"

pubip(){ curl -s --interface "$1" --max-time 12 https://api.ipify.org 2>/dev/null; }

if [ "${1:-}" = "check" ]; then
  printf "Claro (origem %s) -> IP público: %s\n" "$SRC_CLARO" "$(pubip "$SRC_CLARO")"
  printf "Vivo  (origem %s) -> IP público: %s\n" "$SRC_VIVO"  "$(pubip "$SRC_VIVO")"
  exit 0
fi

sqlite3 "$DB" <<'SQL'
PRAGMA journal_mode=DELETE;
CREATE TABLE IF NOT EXISTS speedtest (
  ts       INTEGER,          -- unix epoch da rodada
  wan      TEXT,             -- 'claro' | 'vivo'
  down_bps REAL, up_bps REAL, ping_ms REAL,
  server   TEXT, pub_ip TEXT,
  ok       INTEGER,          -- 1 sucesso, 0 falha
  PRIMARY KEY (ts, wan)
);
SQL

TS=$(date +%s)

run_one(){
  local wan="$1" src="$2" json down up ping server pub ok
  # Servidor fixo é opcional (vazio = automático, escolhe o de menor latência).
  local srv_arg=(); [ -n "${SPEEDTEST_SERVER:-}" ] && srv_arg=(--server-id="$SPEEDTEST_SERVER")
  json=$(timeout 150 "$OOKLA" --ip "$src" "${srv_arg[@]}" \
           --accept-license --accept-gdpr -f json 2>/dev/null) || json=""
  if [ -n "$json" ]; then
    # Ookla: bandwidth em BYTES/s -> *8 = bits/s
    # nome do servidor (multi-palavra) vai por ÚLTIMO p/ o read não quebrar campos
    read -r down up ping pub server < <(python3 - "$json" <<'PY'
import json,sys
try:
    d=json.loads(sys.argv[1])
    print(int(d["download"]["bandwidth"])*8,
          int(d["upload"]["bandwidth"])*8,
          d["ping"]["latency"],
          d.get("interface",{}).get("externalIp","") or "-",
          str(d.get("server",{}).get("name","")).replace("'"," "))
except Exception:
    print("")
PY
)
    [ -n "$down" ] && ok=1 || ok=0
  else
    down=; up=; ping=; server=; pub=; ok=0
  fi
  sqlite3 "$DB" "INSERT OR REPLACE INTO speedtest(ts,wan,down_bps,up_bps,ping_ms,server,pub_ip,ok)
    VALUES ($TS,'$wan',${down:-NULL},${up:-NULL},${ping:-NULL},'${server//\'/}','${pub}',$ok);"
  if [ "$ok" = 1 ]; then
    awk -v w="$wan" -v d="$down" -v u="$up" -v p="$ping" \
      'BEGIN{printf "%-6s  ↓ %.0f Mbps  ↑ %.0f Mbps  ping %.0f ms\n", w, d/1e6, u/1e6, p}'
  else
    echo "$wan: FALHOU"
  fi
}

# Testes sequenciais (não saturar as duas WANs ao mesmo tempo)
run_one claro "$SRC_CLARO"
run_one vivo  "$SRC_VIVO"

chmod 640 "$DB" 2>/dev/null || true
