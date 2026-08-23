#!/bin/bash
# finance_installments_check.sh — avisa no Telegram se uma parcela esperada
# (status 'agendado', gerada por finance.sh installment add) não apareceu no
# extrato do cartão N dias depois da data prevista — sinal de que o extrato
# ainda não chegou, o cartão mudou, ou a compra foi quitada/cancelada por fora.
# Roda semanal via cron. Não repete aviso da mesma parcela (dedupe em notes).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"

out=$(python3 "$DIR/finance_installments.py" check-missing-new)
count=$(echo "$out" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))")
[ "$count" -eq 0 ] && { echo "nada pendente"; exit 0; }

msg=$(echo "$out" | python3 -c "
import json,sys
items=json.load(sys.stdin)
lines=['⚠️ <b>Parcela(s) que não bateram com o extrato:</b>']
for i in items:
    v=f\"R\$ {abs(i['amount_cents'])/100:.2f}\".replace('.', ',')
    lines.append(f\"• {i['description']} — {v} (prevista {i['date']})\")
lines.append('')
lines.append('Confira se o extrato do mês já foi importado, ou se a compra foi quitada/cancelada (aí é só <code>finance.sh installment cancel &lt;plano&gt;</code>).')
print('\n'.join(lines))
")
"$DIR/tg_notify.sh" "$msg" >/dev/null 2>&1
echo "avisado: $count parcela(s)"
