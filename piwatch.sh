#!/usr/bin/env bash
# piwatch — coletor de saúde do próprio Raspberry Pi.
# Estilo homewatch: snapshot por minuto no SQLite; Grafana plota.
# Grava na mesma base do routerwatch (datasource 'routerwatch' já existe).
set -uo pipefail
export LC_ALL=C
DB="${ROUTERWATCH_DB:-/var/lib/routerwatch/routerwatch.db}"
NET_IF="${PIWATCH_NETIF:-eth0}"

sqlite3 "$DB" <<'SQL'
PRAGMA journal_mode=DELETE;
CREATE TABLE IF NOT EXISTS pistat (
  ts          INTEGER PRIMARY KEY,
  cpu_pct     REAL,
  load1 REAL, load5 REAL, load15 REAL,
  mem_pct     REAL, mem_used_mb INTEGER, mem_total_mb INTEGER,
  swap_pct    REAL,
  temp_c      REAL, freq_mhz REAL, volt_v REAL,
  disk_pct    REAL,
  throttled   INTEGER,        -- valor cru de vcgencmd get_throttled
  uv_now INTEGER, uv_ever INTEGER, thr_now INTEGER, thr_ever INTEGER,
  net_rx INTEGER, net_tx INTEGER,   -- contadores crus (taxa via LAG no Grafana)
  uptime_s    INTEGER
);
SQL

# --- CPU % (delta de /proc/stat em 1s) ---
read_cpu(){ read -r _ u n s i io irq si st _ < /proc/stat; CTOT=$((u+n+s+i+io+irq+si+st)); CIDLE=$((i+io)); }
read_cpu; t1=$CTOT; i1=$CIDLE; sleep 1; read_cpu; t2=$CTOT; i2=$CIDLE
CPU_PCT=$(awk -v dt=$((t2-t1)) -v di=$((i2-i1)) 'BEGIN{ if(dt>0) printf "%.1f", (1-di/dt)*100; else print "" }')

# --- load ---
read -r LOAD1 LOAD5 LOAD15 _ < /proc/loadavg

# --- memória / swap (MB) ---
read -r MEM_TOTAL MEM_USED MEM_AVAIL < <(free -m | awk '/^Mem/{print $2, $3, $7}')
MEM_PCT=$(awk -v t="$MEM_TOTAL" -v a="$MEM_AVAIL" 'BEGIN{ if(t>0) printf "%.1f", (t-a)/t*100 }')
read -r SW_TOTAL SW_USED < <(free -m | awk '/^Swap/{print $2, $3}')
SWAP_PCT=$(awk -v t="$SW_TOTAL" -v u="$SW_USED" 'BEGIN{ if(t>0) printf "%.1f", u/t*100; else print 0 }')

# --- temperatura / freq / voltagem ---
TEMP_C=$(awk '{printf "%.1f", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
FREQ_MHZ=$(vcgencmd measure_clock arm 2>/dev/null | awk -F= '{printf "%.0f", $2/1000000}')
VOLT_V=$(vcgencmd measure_volts core 2>/dev/null | grep -o '[0-9.]*')

# --- disco raiz ---
DISK_PCT=$(df --output=pcent / 2>/dev/null | tail -1 | tr -dc '0-9')

# --- throttling / subtensão ---
THR_HEX=$(vcgencmd get_throttled 2>/dev/null | grep -o '0x[0-9a-fA-F]*')
THR=$(( ${THR_HEX:-0} ))
UV_NOW=$(( (THR & 0x1)     ? 1 : 0 ))   # subtensão agora
THR_NOW=$(( (THR & 0x4)    ? 1 : 0 ))   # throttled agora
UV_EVER=$(( (THR & 0x10000)? 1 : 0 ))   # subtensão já ocorreu (desde boot)
THR_EVER=$(((THR & 0x40000)? 1 : 0 ))   # throttling já ocorreu (desde boot)

# --- rede (contadores crus) ---
NET_RX=$(cat /sys/class/net/$NET_IF/statistics/rx_bytes 2>/dev/null || echo "")
NET_TX=$(cat /sys/class/net/$NET_IF/statistics/tx_bytes 2>/dev/null || echo "")

# --- uptime ---
UPTIME_S=$(awk '{printf "%d", $1}' /proc/uptime)

TS=$(date +%s)
q(){ [ -n "$1" ] && printf "%s" "$1" || printf "NULL"; }

sqlite3 "$DB" "INSERT OR REPLACE INTO pistat
 (ts,cpu_pct,load1,load5,load15,mem_pct,mem_used_mb,mem_total_mb,swap_pct,
  temp_c,freq_mhz,volt_v,disk_pct,throttled,uv_now,uv_ever,thr_now,thr_ever,
  net_rx,net_tx,uptime_s)
 VALUES ($TS,$(q "$CPU_PCT"),$(q "$LOAD1"),$(q "$LOAD5"),$(q "$LOAD15"),
  $(q "$MEM_PCT"),$(q "$MEM_USED"),$(q "$MEM_TOTAL"),$(q "$SWAP_PCT"),
  $(q "$TEMP_C"),$(q "$FREQ_MHZ"),$(q "$VOLT_V"),$(q "$DISK_PCT"),
  $(q "$THR"),$UV_NOW,$UV_EVER,$THR_NOW,$THR_EVER,
  $(q "$NET_RX"),$(q "$NET_TX"),$(q "$UPTIME_S"));"

chmod 640 "$DB" 2>/dev/null || true
