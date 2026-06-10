#!/bin/bash
# screen_usage.sh <Pessoa> — uso de tela (proxy via Pi-hole) do(s) aparelho(s) da pessoa.
# Saída: ACTIVE_TODAY (min ativos hoje), LAST90 (min ativos últimos 90), categorias de tráfego.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PDB=/etc/pihole/pihole-FTL.db
MDB="$DIR/web/devices.db"
person="${1:?uso: screen_usage.sh <Pessoa>}"
start=$(date -d 'today 00:00' +%s); now=$(date +%s); w90=$((now-5400))

macs=$(sqlite3 "$MDB" "SELECT lower(mac) FROM device_meta WHERE lower(owner)=lower('$person')" 2>/dev/null)
if [ -z "$macs" ]; then echo "ACTIVE_TODAY=0"; echo "LAST90=0"; echo "NODEV=1"; exit 0; fi
macin=$(echo "$macs" | sed "s/.*/'&'/" | paste -sd,)
ips=$(sudo sqlite3 "$PDB" "SELECT DISTINCT na.ip FROM network_addresses na JOIN network n ON n.id=na.network_id WHERE lower(n.hwaddr) IN ($macin) AND na.lastSeen>=$start" 2>/dev/null)
if [ -z "$ips" ]; then echo "ACTIVE_TODAY=0"; echo "LAST90=0"; exit 0; fi
ipin=$(echo "$ips" | sed "s/.*/'&'/" | paste -sd,)

at=$(sudo sqlite3 "$PDB" "SELECT COUNT(DISTINCT CAST(timestamp AS INT)/60) FROM queries WHERE client IN ($ipin) AND timestamp>=$start" 2>/dev/null)
l90=$(sudo sqlite3 "$PDB" "SELECT COUNT(DISTINCT CAST(timestamp AS INT)/60) FROM queries WHERE client IN ($ipin) AND timestamp>=$w90" 2>/dev/null)
echo "ACTIVE_TODAY=${at:-0}"
echo "LAST90=${l90:-0}"
echo "CATEGORIES:"
sudo sqlite3 -separator '|' "$PDB" "SELECT domain, COUNT(*) c FROM queries WHERE client IN ($ipin) AND timestamp>=$start GROUP BY domain" 2>/dev/null | \
awk -F'|' '
function cat(d){
 if(d~/tiktok|musical\.ly|pangle|byteoversea|ibyteimg|instagram|facebook|fbcdn|snapchat|sc-cdn|twitter|threads|pinterest|kwai/)return "redes";
 if(d~/youtube|ytimg|googlevideo|netflix|nflx|twitch|primevideo|aiv-cdn|disney|globoplay|hbomax|max\.com|crunchyroll/)return "video";
 if(d~/roblox|minecraft|epicgames|steam|supercell|nintendo|playstation|xbox|miniclip|unity3d|king\.com|garena|riotgames/)return "jogos";
 if(d~/spotify|deezer|soundcloud|music\.apple|pandora|amazonmusic/)return "musica";
 if(d~/whatsapp|telegram|discord/)return "mensagens";
 if(d~/(docs|classroom|drive)\.google|wikipedia|khanacademy|brainly|\.edu|duolingo|geekie|qranio/)return "escola";
 return "outros";
}
function app(d){
 if(d~/instagram|cdninstagram/)return "Instagram";
 if(d~/tiktok|musical\.ly|byteoversea|ibyteimg|tiktokv|tiktokcdn|pangle/)return "TikTok";
 if(d~/youtube|ytimg|googlevideo|youtubei/)return "YouTube";
 if(d~/whatsapp/)return "WhatsApp";
 if(d~/spotify/)return "Spotify";
 if(d~/snapchat|sc-cdn/)return "Snapchat";
 if(d~/facebook|fbcdn/)return "Facebook";
 if(d~/netflix|nflx/)return "Netflix";
 if(d~/discord/)return "Discord";
 if(d~/roblox/)return "Roblox";
 if(d~/twitch/)return "Twitch";
 if(d~/pinterest/)return "Pinterest";
 if(d~/kwai/)return "Kwai";
 if(d~/twitter|twimg|x\.com/)return "Twitter_X";
 if(d~/threads/)return "Threads";
 if(d~/telegram/)return "Telegram";
 return "";
}
{c[cat($1)]+=$2; a=app($1); if(a!="")ap[a]+=$2; tot+=$2}
END{ for(k in c) printf "CAT_%s=%d\n", k, c[k];
     for(k in ap) printf "APP_%s=%d\n", k, ap[k];
     print "TOTAL="tot+0 }'
