#!/bin/bash
# habitos.sh — fachada do sistema de hábitos (registro + estratégia + rotina + coach).
# Fatia 1: só registro. rotina/coach entram nas fatias seguintes.
#
#   habitos.sh log <habito> <valor|-> <unidade|-> ["nota"] [--data AAAA-MM-DD] [--m campo=valor]...
#   habitos.sh falha <habito> [obstaculo] ["nota"] [--data ...]
#   habitos.sh metrica <habito> <campo> <valor> [unidade] [classe]
#   habitos.sh interpretar <habito> "<texto livre>"   # LLM -> métricas
#   habitos.sh tick [--dry-run] [--agora "AAAA-MM-DD HH:MM"]   # roda a estratégia
#   habitos.sh pausar <habito> [ate] [motivo] | retomar <habito>
#   habitos.sh status [habito]        # resumo legível da semana
#   habitos.sh ativas | validar <habito> | lint
#   habitos.sh avaliar <habito> [--dry-run]   # roda o coach
#   habitos.sh aplicar <habito>               # aprova a proposta pendente
#   habitos.sh simular <habito> [--de DATA]   # replay sobre o histórico
#   habitos.sh nota <habito> "<texto>"
#   habitos.sh semana [habito]        # JSON cru (para o coach/dashboard)
#   habitos.sh eventos [habito] [n]
#   habitos.sh estrategia [habito]    # mostra a spec corrente
#   habitos.sh db                     # caminho do banco
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
REG="$DIR/habitos/registro.py"
EST="$DIR/habitos/estrategias"

# separa flags --chave valor dos argumentos posicionais
DATA=""; MET=(); POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --data) DATA="$2"; shift 2;;
    --m)    MET+=("$2"); shift 2;;   # campo=valor (repetível); o campo tem de
                                     # estar declarado na coleta da estratégia
    *) POS+=("$1"); shift;;
  esac
done
set -- ${POS[@]+"${POS[@]}"}
cmd="${1:-status}"; shift || true
data_flag(){ [ -n "$DATA" ] && printf -- '--data\n%s\n' "$DATA"; }

# A coleta declarada na estratégia é quem diz que campos existem, com que
# unidade, classe e agregação. O núcleo não conhece nenhum campo por nome.
campo_por_unidade(){ # <habito> <unidade> -> nome do campo (ou vazio)
  jq -r --arg u "$2" '[.coleta[]|select((.quando//"")!="falha" and .unidade==$u)|.campo][0] // empty' \
    "$EST/$1.json" 2>/dev/null
}
spec_do_campo(){ # <habito> <campo> -> "unidade:classe:agregacao" (vazio se não declarado)
  jq -r --arg c "$2" '.coleta[]|select(.campo==$c)|
      "\(.unidade // "")|\(.classe // (if .obrigatorio then "resultado" else "contexto" end))|\(.agregacao // "soma")"' \
    "$EST/$1.json" 2>/dev/null | head -1
}
campos_validos(){ jq -r '[.coleta[]|select((.quando//"")!="falha")|
      "\(.campo)\(if .unidade then " ("+.unidade+")" else "" end)"]|join(", ")' "$EST/$1.json" 2>/dev/null; }

metrica_arg(){ # <habito> <campo> <valor> -> "campo=valor:unidade:classe:agregacao"
  local d; d=$(spec_do_campo "$1" "$2")
  [ -z "$d" ] && { echo "campo '$2' não existe na estratégia de $1 (declarados: $(campos_validos "$1"))" >&2; return 1; }
  IFS='|' read -r un cl ag <<< "$d"
  printf '%s=%s:%s:%s:%s' "$2" "$3" "$un" "$cl" "$ag"
}

meta_de(){ # meta de adesão declarada na estratégia corrente (só para exibir)
  local h="$1"; [ -f "$EST/$h.json" ] || return 0
  jq -r '.criterio_sucesso.adesao.min // empty' "$EST/$h.json" 2>/dev/null
}

case "$cmd" in
  log) # registra que FEZ
    h="${1:?uso: habitos.sh log <habito> <valor|-> <unidade|-> [nota]}"
    val="${2:--}"; un="${3:--}"; nota="${4:-}"
    args=(sessao --habito "$h" --origem "${HABITOS_ORIGEM:-manual}")
    mapfile -t df < <(data_flag); args+=(${df[@]+"${df[@]}"})
    if [ "$val" != "-" ] && [ "$un" != "-" ]; then
      campo=$(campo_por_unidade "$h" "$un")
      [ -z "$campo" ] && { echo "unidade '$un' não corresponde a campo nenhum da estratégia de $h (declarados: $(campos_validos "$h"))" >&2; exit 1; }
      m=$(metrica_arg "$h" "$campo" "$val") || exit 1
      args+=(--metrica "$m")
    fi
    for kv in ${MET[@]+"${MET[@]}"}; do
      m=$(metrica_arg "$h" "${kv%%=*}" "${kv#*=}") || exit 1
      args+=(--metrica "$m")
    done
    [ -n "$nota" ] && args+=(--nota "$nota")
    "$REG" "${args[@]}" >/dev/null || exit 1
    "$0" status "$h" ;;

  falha) # registra que NÃO fez, com o motivo (silêncio NÃO é falha)
    h="${1:?uso: habitos.sh falha <habito> [obstaculo] [nota]}"
    args=(falha --habito "$h" --origem "${HABITOS_ORIGEM:-manual}")
    mapfile -t df < <(data_flag); args+=(${df[@]+"${df[@]}"})
    [ -n "${2:-}" ] && args+=(--obstaculo "$2")
    [ -n "${3:-}" ] && args+=(--nota "$3")
    "$REG" "${args[@]}" >/dev/null && echo "ok: falha registrada em $h${2:+ ($2)}" ;;

  metrica)
    h="${1:?uso: habitos.sh metrica <habito> <campo> <valor> [unidade] [classe]}"
    args=(metrica --habito "$h" --campo "${2:?campo}" --valor "${3:?valor}"
          --origem "${HABITOS_ORIGEM:-manual}" --classe "${5:-resultado}")
    [ -n "${4:-}" ] && args+=(--unidade "$4")
    mapfile -t df < <(data_flag); args+=(${df[@]+"${df[@]}"})
    "$REG" "${args[@]}" >/dev/null && echo "ok: $2=$3 ${4:-} em $h" ;;

  status)
    h="${1:-}"
    "$REG" semana ${h:+--habito "$h"} --n 5 | jq -r '
      def dose:   [.metricas[]|select(.agregacao=="soma")  |"\(.valor|floor) \(.unidade // .campo)"];
      def medida: [.metricas[]|select(.agregacao=="ultimo")|"\(.campo) \(.valor)\(.unidade // "" | if . == "" then "" else " " + . end)"];
      def media:  [.metricas[]|select(.agregacao=="media") |"\(.campo) \(.valor|floor)\(.unidade // "")"];
      if length == 0 then "sem registro ainda" else
      (.[0].semana) as $atual |
      .[] | "\(if .semana == $atual then "▸" else " " end) \(.semana)  \(.habito)  \(.sessoes)×" +
            (if (dose|length) > 0    then "  ·  " + (dose|join(", "))   else "" end) +
            (if (media|length) > 0   then "  ·  " + (media|join(", "))  else "" end) +
            (if (medida|length) > 0  then "  ·  📏 " + (medida|join(", ")) else "" end) +
            (if (.obstaculos|length) > 0 then "  ·  ✗ " + ([.obstaculos[]|"\(.obstaculo)×\(.n)"]|join(", ")) else "" end)
      end'
    if [ -n "$h" ]; then
      m=$(meta_de "$h")
      [ -n "$m" ] && echo "meta de adesão: ${m}×/semana (estratégia v$(jq -r .versao "$EST/$h.json"), $(jq -r .estado "$EST/$h.json"))"
    fi ;;

  interpretar) # texto livre -> registro (usa a LLM, valida contra a coleta da estratégia)
    h="${1:?uso: habitos.sh interpretar <habito> \"<texto>\"}"; t="${2:?texto}"
    "$DIR/habitos/sensor.py" interpretar "$h" "$t" --aplicar \
      --origem "${HABITOS_ORIGEM:-telegram}" ${DATA:+--data "$DATA"} ;;
  nota) # contexto em texto livre (resposta a uma pergunta do coach, observação)
    h="${1:?habito}"; t="${2:?texto}"
    "$REG" evento --habito "$h" --tipo nota --origem "${HABITOS_ORIGEM:-manual}" \
      --payload "$(jq -nc --arg t "$t" '{texto:$t}')" >/dev/null && echo "ok: anotado em $h" ;;
  avaliar) "$DIR/habitos/coach.py" avaliar "${1:?habito}" "${@:2}" ;;
  aplicar) "$DIR/habitos/coach.py" aplicar "${1:?habito}" ;;
  simular) "$DIR/habitos/coach.py" simular "${1:?habito}" "${@:2}" ;;
  tick)    "$DIR/habitos/rotina.py" tick "$@" ;;
  pausar)  "$DIR/habitos/rotina.py" pausar "${1:?habito}" ${2:+--ate "$2"} ${3:+--motivo "$3"} ;;
  retomar) "$DIR/habitos/rotina.py" retomar "${1:?habito}" ;;
  validar) "$DIR/habitos/estrategia.py" validar "${1:?habito}" ;;
  ativas)  "$DIR/habitos/estrategia.py" ativas ;;
  lint)    "$DIR/habitos/lint_nucleo.py" ;;   # o núcleo não pode saber de domínio   # o núcleo não pode saber de domínio
  semana)  h="${1:-}"; "$REG" semana ${h:+--habito "$h"} --n "${2:-12}" ;;
  eventos) h="${1:-}"; "$REG" eventos ${h:+--habito "$h"} --n "${2:-20}" ;;
  estrategia)
    h="${1:?uso: habitos.sh estrategia <habito>}"
    [ -f "$EST/$h.json" ] || { echo "sem estratégia para $h"; exit 1; }
    jq . "$EST/$h.json" ;;
  db)      "$REG" init | jq -r .db ;;
  *) sed -n '2,14p' "$0"; exit 1;;
esac
