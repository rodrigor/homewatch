#!/usr/bin/env bash
# routerspeed.sh — teste de velocidade por operadora (dual-WAN).
# Amarra cada teste a um IP de origem; o ER605 (Policy Routing) roteia
# cada origem por uma WAN. Grava download/upload/ping no SQLite.
#
# Além do Ookla (multi-fluxo, servidor local), mede um download de fluxo
# ÚNICO contra CDN (cdn_bps). Motivo: em 2026-08-06 a Vivo dava 467 Mbps
# no Ookla mas ~3 Mbps por fluxo para CDNs — degradação que o Ookla não vê
# e que derruba streaming de vídeo.
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
# URL do teste de CDN de fluxo único (25 MB da Cloudflare).
CDN_URL="${SPEEDTEST_CDN_URL:-https://speed.cloudflare.com/__down?bytes=25000000}"
# Faixas de IP público de cada operadora (prefixos, separados por espaço).
# Servem para detectar FAILOVER: quando uma WAN cai, o ER605 manda a origem dela
# pela outra WAN e o teste mede a operadora errada com o rótulo errado.
# Se a operadora mudar de faixa, o script avisa "faixa desconhecida" — atualize aqui.
WANIP_CLARO="${WANIP_CLARO:-187.64.}"
WANIP_VIVO="${WANIP_VIVO:-177.158. 179.181. 179.224.}"

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
  cdn_bps  REAL,             -- download de fluxo único contra CDN
  server   TEXT, pub_ip TEXT,
  ok       INTEGER,          -- 1 sucesso, 0 falha
  wan_ok   INTEGER,          -- 1 saiu pela WAN certa, 0 failover, NULL indeterminado
  PRIMARY KEY (ts, wan)
);
SQL
# migração p/ bancos criados antes da coluna cdn_bps
sqlite3 "$DB" "ALTER TABLE speedtest ADD COLUMN cdn_bps REAL;" 2>/dev/null || true
sqlite3 "$DB" "ALTER TABLE speedtest ADD COLUMN wan_ok INTEGER;" 2>/dev/null || true

TS=$(date +%s)

# Fluxo único contra CDN; curl dá BYTES/s -> *8 = bits/s. Vazio = falha (NULL).
cdn_test(){
  local bps
  bps=$(curl -s --interface "$1" -o /dev/null -w '%{speed_download}' \
          --max-time 30 "$CDN_URL" 2>/dev/null) || bps=
  awk -v b="${bps:-0}" 'BEGIN{ if (b+0 > 0) printf "%.0f", b*8 }'
}

run_one(){
  local wan="$1" src="$2" json down up ping server pub ok cdn
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
  # CDN roda mesmo se o Ookla falhar — são falhas independentes.
  cdn=$(cdn_test "$src")
  sqlite3 "$DB" "INSERT OR REPLACE INTO speedtest(ts,wan,down_bps,up_bps,ping_ms,cdn_bps,server,pub_ip,ok)
    VALUES ($TS,'$wan',${down:-NULL},${up:-NULL},${ping:-NULL},${cdn:-NULL},'${server//\'/}','${pub}',$ok);"
  if [ "$ok" = 1 ]; then
    awk -v w="$wan" -v d="$down" -v u="$up" -v p="$ping" -v c="${cdn:-0}" \
      'BEGIN{printf "%-6s  ↓ %.0f Mbps  ↑ %.0f Mbps  ping %.0f ms  CDN(1 fluxo) %.1f Mbps\n", w, d/1e6, u/1e6, p, c/1e6}'
  else
    echo "$wan: FALHOU${cdn:+  (CDN 1 fluxo: $(awk -v c="$cdn" 'BEGIN{printf "%.1f", c/1e6}') Mbps)}"
  fi
}

# Testes sequenciais (não saturar as duas WANs ao mesmo tempo)
run_one claro "$SRC_CLARO"
run_one vivo  "$SRC_VIVO"

# ── Validação da rodada: cada teste saiu mesmo pela WAN que diz o rótulo? ──────
# Roda DEPOIS das duas medições porque a checagem mais confiável é comparar os
# dois IPs entre si: iguais = as duas saíram pela mesma WAN.
# wan_ok: 1 = WAN certa · 0 = failover (dado não comparável) · NULL = indeterminado
match_prefix(){ # match_prefix <ip> <lista de prefixos>
  local ip="$1"; shift
  for pfx in $*; do case "$ip" in "$pfx"*) return 0;; esac; done
  return 1
}
classify(){ # classify <wan> <ip-proprio> <ip-da-outra> -> imprime 1|0|NULL
  local wan="$1" ip="$2" outro="$3" meus outros
  [ -z "$ip" ] || [ "$ip" = "-" ] && { echo NULL; return; }
  [ -n "$outro" ] && [ "$ip" = "$outro" ] && { echo 0; return; }   # mesma saída p/ os dois
  if [ "$wan" = claro ]; then meus="$WANIP_CLARO"; outros="$WANIP_VIVO"
                        else meus="$WANIP_VIVO";  outros="$WANIP_CLARO"; fi
  match_prefix "$ip" "$meus"   && { echo 1; return; }
  match_prefix "$ip" "$outros" && { echo 0; return; }
  echo NULL
}

IP_CLARO=$(sqlite3 "$DB" "SELECT COALESCE(pub_ip,'') FROM speedtest WHERE ts=$TS AND wan='claro';")
IP_VIVO=$( sqlite3 "$DB" "SELECT COALESCE(pub_ip,'') FROM speedtest WHERE ts=$TS AND wan='vivo';")
OK_CLARO=$(classify claro "$IP_CLARO" "$IP_VIVO")
OK_VIVO=$( classify vivo  "$IP_VIVO"  "$IP_CLARO")
sqlite3 "$DB" "UPDATE speedtest SET wan_ok=$OK_CLARO WHERE ts=$TS AND wan='claro';
               UPDATE speedtest SET wan_ok=$OK_VIVO  WHERE ts=$TS AND wan='vivo';"

for pair in "claro:$OK_CLARO:$IP_CLARO" "vivo:$OK_VIVO:$IP_VIVO"; do
  w="${pair%%:*}"; rest="${pair#*:}"; v="${rest%%:*}"; i="${rest#*:}"
  case "$v" in
    0)    echo "⚠️  $w: FAILOVER — saiu por $i, que não é a WAN da $w. Medição não vale p/ comparar." ;;
    NULL) [ -n "$i" ] && [ "$i" != "-" ] &&
            echo "⚠️  $w: IP $i fora das faixas conhecidas — confira se a operadora mudou de faixa (WANIP_$(echo $w | tr a-z A-Z) em routerwatch.env)." ;;
  esac
done

chmod 640 "$DB" 2>/dev/null || true
