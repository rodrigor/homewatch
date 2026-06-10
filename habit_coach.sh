#!/bin/bash
# habit_coach.sh <Pessoa> <habit_file> <situacao> [dado]
# Gera UMA mensagem proativa de coach de hábito, na persona/tom da pessoa. (sandbox pirraikid)
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
P="$1"; F="$2"; SIT="$3"; EXTRA="${4:-}"
[ -f "$F" ] || exit 0
NAME=$(jq -r .name "$F"); TINY=$(jq -r '.tiny // ""' "$F"); WHY=$(jq -r '.why // ""' "$F")
TARGET=$(jq -r .target_per_week "$F")

# tom por pessoa
PROF="$DIR/kids/$P/profile.json"
if [ -f "$PROF" ] && grep -qiE '"name": *"(Gabi|Ana)"' "$PROF"; then
  NICK=$(jq -r '.nickname // .name' "$PROF"); BOT=$(jq -r '.bot_name // "PIrrai"' "$PROF")
  TONE="descolado, de amiga/parça da mesma vibe (adolescente), pode gíria"
elif [ -f "$PROF" ]; then
  NICK=$(jq -r '.nickname // .name' "$PROF"); BOT="PIrrai"; TONE="amigável e leve, de adulto pra adulto, sem infantilizar"
else
  NICK="$P"; BOT="PIrrai"; TONE="amigável, leve e direto, de colega"
fi

case "$SIT" in
  pace)    CTX="Estamos no meio/fim da semana e $NICK ainda não bateu a meta do hábito \"$NAME\" (meta: ${TARGET}x/semana; situação: $EXTRA). Dê um empurrãozinho animado e SEM cobrança pra encaixar uma sessão. Lembre que vale a versão mínima: $TINY.";;
  met)     CTX="$NICK BATEU a meta do hábito \"$NAME\" essa semana ($EXTRA)! Comemore junto, genuíno e curto. Valorize a consistência.";;
  logged)  CTX="$NICK acabou de registrar uma sessão do hábito \"$NAME\". Progresso: $EXTRA. Reforce positivo e rapidinho.";;
  adapt)   CTX="O hábito \"$NAME\" não está colando. Comunique de forma leve e parceira a mudança de estratégia que vamos TESTAR: $EXTRA. Nada de sermão; enquadre como experimento, 'bora testar assim'.";;
  *)       CTX="$EXTRA";;
esac

SYS="Você é $BOT, coach de hábitos pessoal e parceiro de $NICK. Gere UMA mensagem curtinha (1-2 frases), $TONE, no máximo 1 emoji.
REGRAS: ZERO sermão, ZERO culpa, ZERO 'você falhou'. Tom de parceria e experimento. Não cite estatísticas frias; fale humano. ${WHY:+Motivação dela: $WHY.}
Situação: $CTX
Responda APENAS a mensagem."
printf '%s' "$SYS" | sudo -H -u pirraikid /usr/local/bin/claude -p --model sonnet 2>/dev/null \
  | sed 's/<<SAVE {.*}>>//g' | sed -e :a -e '/^[[:space:]]*$/{$d;N;ba}'
