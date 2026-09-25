#!/usr/bin/env bash
# display.sh: controla o display USB da estante (Turing 3.5", painel netpanel)
#   display.sh status          painel rodando?, tela ligada?, brilho
#   display.sh brilho <0-100>  ajusta o brilho
#   display.sh desliga|liga    apaga/acende a tela
#   display.sh reinicia        reinicia o serviço netpanel
# O painel lê a configuração só na partida: cada mudança reinicia o serviço
# (a tela apaga por ~10 s).
# Horário automático: netpanel-off.timer (23:59) e netpanel-on.timer (06:00).
set -euo pipefail
CTL="$HOME/.local/state/netpanel/ctl.json"
mkdir -p "$(dirname "$CTL")"

# atualiza um campo do JSON de controle (escrita atômica)
set_ctl(){ # $1=campo $2=valor JSON
  python3 - "$CTL" "$1" "$2" <<'PY'
import json, os, sys
path, key, val = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
try:
    c = json.load(open(path))
except (OSError, ValueError):
    c = {}
c.setdefault("brightness", 20); c.setdefault("on", True)
c[key] = val
tmp = path + ".tmp"
json.dump(c, open(tmp, "w")); os.replace(tmp, path)
PY
  sudo -n systemctl restart netpanel
}

status(){
  local svc on br
  svc=$(systemctl is-active netpanel 2>/dev/null || true)
  read -r on br < <(python3 -c 'import json,sys
try: c=json.load(open(sys.argv[1]))
except Exception: c={}
print("ligada" if c.get("on",True) else "desligada", c.get("brightness",20))' "$CTL")
  echo "painel: $svc | tela: $on | brilho: $br%"
  systemctl list-timers netpanel-off.timer netpanel-on.timer --no-pager 2>/dev/null \
    | awk 'NR>1 && /netpanel/ {print "próximo: " $NF " em " $1 " " $2 " " $3}'
}

case "${1:-status}" in
  status) status ;;
  brilho|brightness)
    n="${2:-}"
    [[ "$n" =~ ^[0-9]+$ ]] && (( n <= 100 )) || { echo "uso: display.sh brilho <0-100>" >&2; exit 1; }
    set_ctl brightness "$n"; echo "brilho: $n%" ;;
  desliga|off) set_ctl on false; echo "tela desligada" ;;
  liga|on)     set_ctl on true;  echo "tela ligada" ;;
  reinicia|restart) sudo -n systemctl restart netpanel; echo "netpanel reiniciado" ;;
  *) sed -n '2,10p' "$0" >&2; exit 1 ;;
esac
