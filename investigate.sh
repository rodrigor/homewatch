#!/bin/bash
# investigate.sh <ip|mac> — coleta evidências para identificar um dispositivo da rede.
# Saída: texto estruturado p/ o Claude/PIrrai deduzir o que é. Usa sudo p/ sqlite/nmap.
set -uo pipefail
DB=/etc/pihole/pihole-FTL.db
IFACE=eth0
ARG="${1:-}"
[ -z "$ARG" ] && { echo "uso: investigate.sh <ip|mac>"; exit 1; }
SQL(){ sudo sqlite3 -noheader -separator ' | ' "$DB" "$1" 2>/dev/null; }

# normaliza alvo -> IP e MAC
IP=""; MAC=""
if echo "$ARG" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
  IP="$ARG"
  MAC=$(SQL "SELECT n.hwaddr FROM network n JOIN network_addresses na ON na.network_id=n.id WHERE na.ip='$IP' LIMIT 1")
  [ -z "$MAC" ] && { ping -c1 -W2 "$IP" >/dev/null 2>&1; MAC=$(ip neigh show "$IP" 2>/dev/null | awk '/lladdr/{print $5}' | head -1); }
elif echo "$ARG" | grep -qiE '^([0-9a-f]{2}:){5}[0-9a-f]{2}$'; then
  MAC=$(echo "$ARG" | tr 'A-Z' 'a-z')
  IP=$(SQL "SELECT na.ip FROM network_addresses na JOIN network n ON n.id=na.network_id WHERE lower(n.hwaddr)='$MAC' ORDER BY na.lastSeen DESC LIMIT 1")
else
  echo "alvo inválido (use IP ou MAC)"; exit 1
fi
MAC=$(echo "$MAC" | tr 'A-Z' 'a-z')

echo "===== INVESTIGAÇÃO: ${IP:-?}  (MAC ${MAC:-?}) ====="
echo "--- IDENTIDADE BÁSICA (Pi-hole) ---"
SQL "SELECT 'fabricante: '||COALESCE(n.macVendor,'?'),
      'firstSeen: '||datetime(n.firstSeen,'unixepoch','localtime'),
      'lastQuery: '||datetime(n.lastQuery,'unixepoch','localtime'),
      'numQueries: '||n.numQueries
     FROM network n WHERE lower(n.hwaddr)='${MAC}';" 2>/dev/null | tr '|' '\n' | sed 's/^ *//'
HOST=$(SQL "SELECT na.name FROM network_addresses na JOIN network n ON n.id=na.network_id WHERE lower(n.hwaddr)='${MAC}' AND na.name IS NOT NULL ORDER BY na.lastSeen DESC LIMIT 1")
echo "hostname: ${HOST:-(nenhum)}"
ONLINE=$(ping -c1 -W2 "$IP" >/dev/null 2>&1 && echo "SIM" || echo "não respondeu ao ping")
echo "online agora: $ONLINE"
echo

echo "--- DNS: TOP 20 DOMÍNIOS NAS ÚLTIMAS 24h (dispositivo ATUAL) ---"
echo "ATENÇÃO: consultas são por IP; o IP pode ter sido de outro aparelho antes (DHCP). Priorize as 24h."
[ -n "$IP" ] && SQL "SELECT domain, COUNT(*) c FROM queries WHERE client='$IP' AND timestamp>=strftime('%s','now','-1 day') GROUP BY domain ORDER BY c DESC LIMIT 20;"
echo

echo "--- DNS: ASSINATURAS DE MARCA (histórico) ---"
[ -n "$IP" ] && SQL "SELECT DISTINCT domain FROM queries WHERE client='$IP'" | grep -ioE 'alexa|avs-alexa|echo|firetv|amazonvideo|atv-ps|pix-star|tuya|xiaomi|mi\.com|tplink|tp-link|ring\.com|nest|roku|samsung|smartthings|sonos|spotify|philips|hue|shelly|sonoff|ecovacs|roborock|irobot|synology|qnap|hikvision|dahua|reolink|sony|playstation|xbox|nintendo|whatsapp|icloud|apple|garmin|fitbit|tesla|svc\.ourhome' | sort | uniq -c | sort -rn | head -15
echo "(vazio = sem marca óbvia nos domínios)"
echo

echo "--- NMAP: PORTAS/SERVIÇOS ---"
[ -n "$IP" ] && sudo nmap -Pn -T4 --top-ports 100 -sV "$IP" 2>/dev/null | grep -E '^[0-9]+/(tcp|udp)|Service Info|MAC Address' | head -15
echo

echo "--- SMB (se 139/445 abertos): nome/compartilhamentos ---"
if [ -n "$IP" ] && sudo nmap -Pn -p139,445 "$IP" 2>/dev/null | grep -q 'open'; then
  sudo nmap -Pn -p139,445 --script smb-os-discovery,smb-enum-shares "$IP" 2>/dev/null | grep -iE 'computer name|netbios|os:|\\\\|workgroup|System time' | head -12
else
  echo "(sem SMB)"
fi
echo "===== FIM ====="
