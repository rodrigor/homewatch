#!/bin/bash
# agenda_morning.sh — manda no Telegram a agenda do dia (Todoist). Disparado pelo timer às 06:00.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"

TODAY=$("$DIR/todoist.sh" list "today" 2>/dev/null | sed -E 's/ \[#[^]]*\]$//')
[ -z "$TODAY" ] && TODAY="(vazio)"
OV=$("$DIR/todoist.sh" list "overdue" 2>/dev/null)
if [ "$OV" = "(vazio)" ] || [ -z "$OV" ]; then OVN=0; else OVN=$(printf '%s\n' "$OV" | grep -c '^•'); fi

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
