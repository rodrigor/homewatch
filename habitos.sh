#!/bin/bash
# habitos.sh — fachada do sistema de hábitos (registro + estratégia + rotina + coach).
# Fatia 1: só registro. rotina/coach entram nas fatias seguintes.
#
#   habitos.sh log <habito> <valor|-> <unidade|-> ["nota"] [--data AAAA-MM-DD] [--fc 122]
#   habitos.sh falha <habito> [obstaculo] ["nota"] [--data ...]
#   habitos.sh metrica <habito> <campo> <valor> [unidade] [classe]
#   habitos.sh interpretar <habito> "<texto livre>"   # LLM -> métricas
#   habitos.sh tick [--dry-run] [--agora "AAAA-MM-DD HH:MM"]   # roda a estratégia
#   habitos.sh pausar <habito> [ate] [motivo] | retomar <habito>
#   habitos.sh status [habito]        # resumo legível da semana
#   habitos.sh ativas | validar <habito>
#   habitos.sh semana [habito]        # JSON cru (para o coach/dashboard)
#   habitos.sh eventos [habito] [n]
#   habitos.sh estrategia [habito]    # mostra a spec corrente
#   habitos.sh db                     # caminho do banco
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
REG="$DIR/habitos/registro.py"
EST="$DIR/habitos/estrategias"

# separa flags --chave valor dos argumentos posicionais
DATA=""; FC=""; POS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --data) DATA="$2"; shift 2;;
    --fc)   FC="$2";   shift 2;;
    *) POS+=("$1"); shift;;
  esac
done
set -- ${POS[@]+"${POS[@]}"}
cmd="${1:-status}"; shift || true
data_flag(){ [ -n "$DATA" ] && printf -- '--data\n%s\n' "$DATA"; }

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
      case "$un" in min) campo=minutos;; km) campo=distancia;; *) campo="$un";; esac
      args+=(--metrica "$campo=$val:$un:resultado")
    fi
    [ -n "$FC" ] && args+=(--metrica "fc_media=$FC:bpm:contexto")
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
  tick)    "$DIR/habitos/rotina.py" tick "$@" ;;
  pausar)  "$DIR/habitos/rotina.py" pausar "${1:?habito}" ${2:+--ate "$2"} ${3:+--motivo "$3"} ;;
  retomar) "$DIR/habitos/rotina.py" retomar "${1:?habito}" ;;
  validar) "$DIR/habitos/estrategia.py" validar "${1:?habito}" ;;
  ativas)  "$DIR/habitos/estrategia.py" ativas ;;
  semana)  h="${1:-}"; "$REG" semana ${h:+--habito "$h"} --n "${2:-12}" ;;
  eventos) h="${1:-}"; "$REG" eventos ${h:+--habito "$h"} --n "${2:-20}" ;;
  estrategia)
    h="${1:?uso: habitos.sh estrategia <habito>}"
    [ -f "$EST/$h.json" ] || { echo "sem estratégia para $h"; exit 1; }
    jq . "$EST/$h.json" ;;
  db)      "$REG" init | jq -r .db ;;
  *) sed -n '2,14p' "$0"; exit 1;;
esac
