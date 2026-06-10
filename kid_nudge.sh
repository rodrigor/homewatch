#!/bin/bash
# kid_nudge.sh <Pessoa> [motivo] — gera UMA mensagem proativa na PERSONA da filha (descolada, sem sermão).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
NAME="${1:?uso: kid_nudge.sh <Pessoa> [motivo]}"; REASON="${2:-pausa}"
KDIR="$DIR/kids/$NAME"; PROF="$KDIR/profile.json"; HIST="$KDIR/history.txt"
mkdir -p "$KDIR"
if [ -f "$PROF" ]; then
  NICK=$(jq -r '.nickname // .name' "$PROF"); BOT=$(jq -r '.bot_name // "PIrrai"' "$PROF"); LIKES=$(jq -c '.likes // {}' "$PROF")
else
  NICK="$NAME"; BOT="PIrrai"; LIKES="{}"
fi
case "$NAME" in
  Gabi|Ana) PERSONA="a parça/companheira virtual de $NICK (adolescente)"; STYLE="SUPER descolada e leve, como amiga da mesma vibe dela, pode usar gíria";;
  *)        PERSONA="o assistente pessoal de $NICK (adulto)"; STYLE="amigável, leve e direto, tom de colega de boa — sem gíria forçada nem infantilizar";;
esac
case "$REASON" in
  pausa) CTX="A pessoa está há um tempão seguido na tela. Chame de leve pra uma pausinha (esticar o corpo, beber água, olhar pra longe um minuto, respirar).";;
  *)     CTX="$REASON";;
esac
SYS="Você é $BOT, $PERSONA. Gere UMA mensagem proativa, curtinha (1 a 2 frases), $STYLE, no máximo 1 emoji.
REGRAS DURAS: PROIBIDO soar como mãe/pai ou chefe; ZERO sermão; ZERO cobrança; NÃO diga 'você está usando muito a tela/celular/computador', NÃO cite horas/minutos/tempo de tela, NÃO dê lição de moral. É só um toque de boa, natural.
Interesses (use só se sair natural, não force): $LIKES.
Contexto: $CTX.
Responda APENAS a mensagem, mais nada."
MSG=$(printf '%s' "$SYS" | sudo -H -u pirraikid /usr/local/bin/claude -p --model sonnet 2>>"$KDIR/err.log")
MSG=$(printf '%s' "$MSG" | sed 's/<<SAVE {.*}>>//g' | sed -e :a -e '/^[[:space:]]*$/{$d;N;ba}')
[ -z "$MSG" ] && exit 0
printf '%s: %s\n' "$BOT" "$MSG" >> "$HIST"
printf '%s' "$MSG"
