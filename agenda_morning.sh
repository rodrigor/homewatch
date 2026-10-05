#!/bin/bash
# agenda_morning.sh — manda no Telegram a agenda do dia (TickTick). Disparado pelo timer às 06:00.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

# sem token válido o today sairia vazio e a mensagem diria "nada agendado"
if ! "$DIR/ticktick.sh" test 2>/dev/null | grep -q '^OK'; then
  "$DIR/tg_notify.sh" "☀️ <b>Bom dia, Rodrigo!</b>

⚠️ Não consegui ler o TickTick (token ausente ou inválido em ticktick.env)."
  exit 1
fi
# o today traz as de hoje e as atrasadas (marcadas); uma varredura só da API
ALL=$("$DIR/ticktick.sh" today 2>/dev/null | grep '^•')
TODAY=$(printf '%s\n' "$ALL" | grep -v 'atrasada$' | sed -E 's/ \[#[^]]*\]$//')
[ -z "$TODAY" ] && TODAY="(vazio)"
OVN=$(printf '%s\n' "$ALL" | grep -c 'atrasada$')

DIA=$(date '+%d/%m')
if [ "$TODAY" = "(vazio)" ]; then
  CORPO="Nada agendado pra hoje 🎉"
else
  CORPO="$TODAY"
fi
MSG="☀️ <b>Bom dia, Rodrigo!</b>  📅 $DIA

<b>📋 Hoje:</b>
$CORPO"
[ "$OVN" -gt 0 ] && MSG="$MSG

⚠️ <b>$OVN atrasada(s)</b> — manda <i>\"tarefas atrasadas\"</i> que eu listo."

"$DIR/tg_notify.sh" "$MSG"
