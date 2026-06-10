#!/bin/bash
# homewatch/collect.sh — coleta determinística de dados (Pi-hole + rede + internet + sistema)
# Saída: texto estruturado no stdout, para ser analisado pelo Claude.
set -uo pipefail
DB=/etc/pihole/pihole-FTL.db
LAN_IFACE=eth0
LAN_CIDR=192.168.54.0/24
GW=192.168.54.1
WINDOW="${1:-1 day}"   # janela de análise (ex.: "1 day", "1 hour")
SQL(){ sudo sqlite3 -noheader -separator ' | ' "$DB" "$1" 2>/dev/null; }

echo "===== HOMEWATCH — DADOS BRUTOS ($(date '+%Y-%m-%d %H:%M:%S %Z')) ====="
echo "Janela analisada: últimas $WINDOW"
echo

echo "----- PI-HOLE: VOLUME (janela) -----"
SQL "SELECT
  CASE WHEN status IN (1,4,5,6,7,8,9,10,11,15) THEN 'bloqueadas'
       WHEN status IN (2,3,12,13,14) THEN 'permitidas' ELSE 'outras' END tipo,
  COUNT(*) total
 FROM queries WHERE timestamp>=strftime('%s','now','-${WINDOW}') GROUP BY tipo;"
echo

echo "----- PI-HOLE: TOP 15 DOMÍNIOS BLOQUEADOS -----"
SQL "SELECT domain, COUNT(*) c FROM queries
 WHERE status IN (1,4,5,6,7,8,9,10,11,15) AND timestamp>=strftime('%s','now','-${WINDOW}')
 GROUP BY domain ORDER BY c DESC LIMIT 15;"
echo

echo "----- PI-HOLE: TOP 15 CLIENTES (por volume) -----"
SQL "SELECT q.client,
  COALESCE((SELECT n.macVendor FROM network n JOIN network_addresses na ON na.network_id=n.id WHERE na.ip=q.client LIMIT 1),'?') vendor,
  COUNT(*) total,
  SUM(CASE WHEN status IN (1,4,5,6,7,8,9,10,11,15) THEN 1 ELSE 0 END) bloq
 FROM queries q WHERE timestamp>=strftime('%s','now','-${WINDOW}')
 GROUP BY q.client ORDER BY total DESC LIMIT 15;"
echo

echo "----- PI-HOLE: DOMÍNIOS NOVOS (1ª vez vistos na janela; top 20 por volume) -----"
SQL "SELECT domain, COUNT(*) c FROM queries
 WHERE timestamp>=strftime('%s','now','-${WINDOW}')
 GROUP BY domain
 HAVING MIN(timestamp) >= strftime('%s','now','-${WINDOW}')
 ORDER BY c DESC LIMIT 20;"
echo

echo "----- PI-HOLE: CLIENTES QUE MAIS BATERAM EM DOMÍNIOS BLOQUEADOS DISTINTOS -----"
SQL "SELECT client, COUNT(DISTINCT domain) dominios_bloq_distintos FROM queries
 WHERE status IN (1,4,5,6,7,8,9,10,11,15) AND timestamp>=strftime('%s','now','-${WINDOW}')
 GROUP BY client ORDER BY dominios_bloq_distintos DESC LIMIT 8;"
echo

echo "----- REDE: DISPOSITIVOS NOVOS (firstSeen na janela) -----"
SQL "SELECT n.hwaddr, COALESCE(n.macVendor,'?') vendor,
  (SELECT na.ip FROM network_addresses na WHERE na.network_id=n.id ORDER BY na.lastSeen DESC LIMIT 1) ip,
  datetime(n.firstSeen,'unixepoch','localtime') visto_em
 FROM network n WHERE n.firstSeen>=strftime('%s','now','-${WINDOW}')
 ORDER BY n.firstSeen DESC;"
echo

echo "----- REDE: VARREDURA AO VIVO (dispositivos online agora) -----"
ARP=$(sudo arp-scan --interface="$LAN_IFACE" --localnet --quiet --plain 2>/dev/null)
echo "$ARP" | awk -F'\t' 'NF>=2{printf "%-15s  %-18s  %s\n",$1,$2,$3}' | sort -t. -k4 -n
echo "Total online agora: $(echo "$ARP" | grep -c .)"
echo

echo "----- INTERNET: SAÚDE -----"
echo "Gateway ($GW):"; ping -c4 -W2 "$GW" 2>/dev/null | tail -2
echo "Externo (1.1.1.1):"; ping -c4 -W2 1.1.1.1 2>/dev/null | tail -2
echo "Resolução DNS (via Pi-hole local):"; dig +short +timeout=2 google.com @127.0.0.1 | head -1
if [ "${2:-}" = "--speedtest" ]; then
  echo "Speedtest:"; speedtest-cli --simple 2>/dev/null || echo "speedtest falhou"
fi
echo

echo "----- SISTEMA (Pi) -----"
echo "Uptime:$(uptime -p)"
echo "Temp: $(vcgencmd measure_temp 2>/dev/null | cut -d= -f2)  Throttle: $(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"
echo "Disco /: $(df -h / | awk 'NR==2{print $5" usado ("$4" livre)"}')"
echo "Memória: $(free -h | awk '/Mem/{print $3" / "$2}')"
echo "Serviços falhos: $(systemctl --failed --no-legend | wc -l)"
echo "Pi-hole FTL: $(systemctl is-active pihole-FTL)"
echo "===== FIM DOS DADOS ====="
