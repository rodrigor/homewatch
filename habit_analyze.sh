#!/bin/bash
# habit_analyze.sh <Pessoa> <habit_file> <count> <target> <met:0|1>
# Revisão semanal ESTRATÉGICA com OPUS: analisa resultados+métricas, decide próximo passo
# (comemorar/subir nível se bateu; diagnosticar+adaptar se não), aplica no arquivo, devolve a mensagem.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
P="$1"; F="$2"; CNT="${3:-0}"; TARGET="${4:-1}"; MET="${5:-0}"
[ -f "$F" ] || exit 0
NAME=$(jq -r .name "$F")

PROF="$DIR/kids/$P/profile.json"
if [ -f "$PROF" ] && grep -qiE '"name": *"(Gabi|Ana)"' "$PROF"; then
  NICK=$(jq -r '.nickname // .name' "$PROF"); BOT=$(jq -r '.bot_name // "PIrrai"' "$PROF"); TONE="adolescente, descolado, de parça (pode gíria)"
elif [ -f "$PROF" ]; then
  NICK=$(jq -r '.nickname // .name' "$PROF"); BOT="PIrrai"; TONE="adulto, amigável e leve, de colega"
else
  NICK="$P"; BOT="PIrrai"; TONE="adulto, amigável, de colega"
fi
DATA=$(jq -c '{name,type,target_per_week,cue_time,tiny,why,streak_weeks,miss_streak,adaptations,log}' "$F")

if [ "$MET" = "1" ]; then
  GOAL="$NICK BATEU a meta essa semana ($CNT de $TARGET). Comemore de forma genuína e analise a EVOLUÇÃO pelas métricas do log (ex.: km/páginas/minutos subindo?). Decida se vale SUBIR O NÍVEL (aumentar a meta semanal) — só se houver consistência (streak) e o hábito parecer tranquilo; senão mantenha. change_type: \"level_up\" (com new_target) ou \"none\"."
else
  GOAL="$NICK NÃO bateu a meta ($CNT de $TARGET). Diagnostique o PADRÃO (quais dias falham, efeito das adaptações já tentadas, meta alta demais, falta de gatilho/âncora, motivação fraca) e escolha A ÚNICA próxima mudança mais promissora, SEM repetir uma que já falhou. change_type: set_anchor | shrink_target (com new_target) | focus_minimum | reframe | change_channel | ask."
fi

PROMPT="Você é um COACH DE HÁBITOS estrategista e MUITO analítico. Analise os dados reais (log diário com done/value/unit/nota = métricas como km, páginas, minutos; histórico de adaptações; meta; gatilho; tiny; motivação why).
DADOS: $DATA

$GOAL

Escreva também a MENSAGEM para $NICK: curtíssima (1-2 frases), tom $TONE, framing de parceria/experimento, ZERO sermão/culpa, no máx 1 emoji. Se houver evolução nas métricas, pode mencionar de leve (motiva).
Responda SÓ um JSON: {\"assessment\":\"<análise curta>\",\"change_type\":\"...\",\"new_target\":<int ou null>,\"message\":\"<mensagem pra $NICK>\"}"

OUT=$(printf '%s' "$PROMPT" | sudo -H -u pirraikid /usr/local/bin/claude -p --model opus 2>/dev/null)
JSON=$(printf '%s' "$OUT" | grep -oE '\{.*\}' | head -1)
MSG=""
if [ -n "$JSON" ] && printf '%s' "$JSON" | jq . >/dev/null 2>&1; then
  CT=$(printf '%s' "$JSON" | jq -r '.change_type // "none"')
  NT=$(printf '%s' "$JSON" | jq -r '.new_target // empty')
  AS=$(printf '%s' "$JSON" | jq -r '.assessment // ""')
  MSG=$(printf '%s' "$JSON" | jq -r '.message // ""')
  if [ "$MET" = "1" ]; then
    jq '.streak_weeks=((.streak_weeks // 0)+1) | .miss_streak=0' "$F" > "$F.tmp" && mv "$F.tmp" "$F"
    if [ "$CT" = "level_up" ] && printf '%s' "$NT" | grep -qE '^[0-9]+$' && [ "$NT" -gt "$TARGET" ]; then
      jq --argjson v "$NT" '.target_per_week=$v' "$F" > "$F.tmp" && mv "$F.tmp" "$F"
    fi
  else
    if [ "$CT" = "shrink_target" ] && printf '%s' "$NT" | grep -qE '^[0-9]+$' && [ "$NT" -ge 1 ]; then
      jq --argjson v "$NT" '.target_per_week=$v' "$F" > "$F.tmp" && mv "$F.tmp" "$F"
    fi
    jq '.miss_streak=((.miss_streak // 0)+1)' "$F" > "$F.tmp" && mv "$F.tmp" "$F"
  fi
  jq --arg ct "$CT" --arg a "$AS" --arg ts "$(date +%Y-%m-%d)" \
    '.adaptations += [{date:$ts,result:("'"$CNT"'/'"$TARGET"'"),change_type:$ct,assessment:$a,by:"opus"}]' "$F" > "$F.tmp" && mv "$F.tmp" "$F"
fi
if [ -z "$MSG" ]; then
  if [ "$MET" = "1" ]; then MSG="Boa, $NICK! Meta de $NAME batida essa semana ($CNT/$TARGET) 🔥"
  else MSG="Ei $NICK, essa semana o $NAME não fechou — bora ajustar e testar de novo na próxima. 🧪"; fi
fi
printf '%s' "$MSG"
