#!/bin/bash
# finance_alerts.sh — alerta no Telegram quando uma categoria atinge 80% ou estoura (100%) o limite do mês.
# Sem spam: cada nível dispara uma única vez por categoria/mês (tabela budget_alerts).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DB="${FINANCE_DB:-$DIR/finance.db}"
mon=$(date +%Y-%m)
esc(){ printf '%s' "$1" | sed "s/'/''/g"; }
fmt(){ awk -v c="$1" 'BEGIN{printf "R$ %.2f", c/100}' | sed 's/\./,/'; }

# itera categorias com limite recorrente
while IFS='|' read -r cat lim; do
  [ -z "$cat" ] && continue
  ec=$(esc "$cat")
  spent=$(sqlite3 "$DB" "SELECT COALESCE(-SUM(amount),0) FROM transactions WHERE category='$ec' AND amount<0 AND substr(date,1,7)='$mon';")
  [ "$lim" -le 0 ] 2>/dev/null && continue
  pct=$(( spent * 100 / lim ))
  level=0
  if   [ "$pct" -ge 100 ]; then level=100
  elif [ "$pct" -ge 80 ];  then level=80
  fi
  [ "$level" -eq 0 ] && continue
  # já avisou esse nível neste mês?
  seen=$(sqlite3 "$DB" "SELECT COUNT(*) FROM budget_alerts WHERE category='$ec' AND month='$mon' AND level=$level;")
  [ "$seen" -gt 0 ] && continue
  if [ "$level" -eq 100 ]; then
    msg="🚨 <b>Limite estourado: $cat</b>
Gasto: <b>$(fmt "$spent")</b> de $(fmt "$lim") (${pct}%) em $mon."
    # ao estourar, marca o 80 também p/ não mandar o aviso de 80 depois
    sqlite3 "$DB" "INSERT OR IGNORE INTO budget_alerts(category,month,level) VALUES('$ec','$mon',80);"
  else
    msg="⚠️ <b>Atenção: $cat chegou a ${pct}%</b>
Gasto: $(fmt "$spent") de $(fmt "$lim") em $mon. Falta $(fmt $(( lim - spent )))."
  fi
  "$DIR/tg_notify.sh" "$msg" >/dev/null 2>&1
  sqlite3 "$DB" "INSERT OR IGNORE INTO budget_alerts(category,month,level) VALUES('$ec','$mon',$level);"
  echo "alerta $level% enviado: $cat (${pct}%)"
done < <(sqlite3 -separator '|' "$DB" "SELECT category,limit_amount FROM budgets WHERE month='*';")
