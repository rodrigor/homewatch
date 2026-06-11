#!/bin/bash
# series.sh — gerencia catálogo de séries
# Uso:
#   series.sh list                         → lista todas
#   series.sh assistindo                   → séries em andamento
#   series.sh concluidas                   → séries concluídas
#   series.sh quero                        → lista "quero ver"
#   series.sh add "Nome" [status] [plat]   → adiciona (status padrão: assistindo)
#   series.sh done "Nome"                  → marca como concluída
#   series.sh pause "Nome"                 → marca como pausada
#   series.sh status "Nome" <novo_status>  → atualiza status
#   series.sh platform "Nome" "Plataforma" → define plataforma
#   series.sh note "Nome" "texto"          → adiciona nota
#   series.sh episode "Nome" "S01E05"      → registra episódio atual
#   series.sh notify "Nome" on|off         → ativa/desativa alerta de novo ep
#   series.sh remove "Nome"                → remove da lista

DIR="$(cd "$(dirname "$0")" && pwd)"
FILE="$DIR/series.json"
CMD="${1:-list}"

STATUS_ICON() {
  case "$1" in
    assistindo) echo "▶️";;
    concluída)  echo "✅";;
    pausada)    echo "⏸️";;
    "quero ver") echo "🔖";;
    *)          echo "❓";;
  esac
}

case "$CMD" in
  list)
    echo "=== TODAS AS SÉRIES ==="
    jq -r '.series | sort_by(.status,.name)[] |
      "\(.status | if . == "assistindo" then "▶️" elif . == "concluída" then "✅" elif . == "pausada" then "⏸️" elif . == "quero ver" then "🔖" else "❓" end) \(.name)\(if .platform != "" then " — " + .platform else "" end)\(if .notes != "" then " | " + .notes else "" end)"' "$FILE"
    ;;

  assistindo)
    echo "=== ASSISTINDO ==="
    jq -r '.series[] | select(.status == "assistindo") | "▶️ \(.name)\(if .platform != "" then " — " + .platform else "" end)\(if (.last_episode // "") != "" then " [" + .last_episode + "]" else "" end)\(if .notes != "" then " | " + .notes else "" end)"' "$FILE"
    ;;

  concluidas|concluídas)
    echo "=== CONCLUÍDAS ==="
    jq -r '.series[] | select(.status == "concluída") | "✅ \(.name)\(if .platform != "" then " — " + .platform else "" end)"' "$FILE"
    ;;

  quero|"quero ver")
    echo "=== QUERO VER ==="
    jq -r '.series[] | select(.status == "quero ver") | "🔖 \(.name)\(if .platform != "" then " — " + .platform else "" end)"' "$FILE"
    ;;

  pausadas)
    echo "=== PAUSADAS ==="
    jq -r '.series[] | select(.status == "pausada") | "⏸️ \(.name)\(if .platform != "" then " — " + .platform else "" end)"' "$FILE"
    ;;

  add)
    NOME="${2:-}"; STATUS="${3:-assistindo}"; PLAT="${4:-}"
    [ -z "$NOME" ] && echo "Uso: series.sh add 'Nome' [status] [plataforma]" && exit 1
    # verifica se já existe
    EXISTS=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase == ($n | ascii_downcase)) | .name' "$FILE")
    [ -n "$EXISTS" ] && echo "Série '$EXISTS' já está no catálogo." && exit 0
    LAST_ID=$(jq '.series | map(.id) | max' "$FILE")
    NEW_ID=$((LAST_ID + 1))
    DATE=$(date '+%Y-%m-%d')
    jq --argjson id "$NEW_ID" --arg nome "$NOME" --arg status "$STATUS" --arg plat "$PLAT" --arg date "$DATE" \
      '.series += [{"id": $id, "name": $nome, "status": $status, "platform": $plat, "notes": "", "added": $date}]' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "✅ '$NOME' adicionada com status: $STATUS"
    ;;

  done|assistida)
    NOME="${2:-}"
    [ -z "$NOME" ] && echo "Uso: series.sh done 'Nome'" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    jq --arg n "$MATCH" '(.series[] | select(.name == $n)).status = "concluída"' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "✅ '$MATCH' marcada como concluída."
    ;;

  pause|pausar)
    NOME="${2:-}"
    [ -z "$NOME" ] && echo "Uso: series.sh pause 'Nome'" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    jq --arg n "$MATCH" '(.series[] | select(.name == $n)).status = "pausada"' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "⏸️ '$MATCH' marcada como pausada."
    ;;

  status)
    NOME="${2:-}"; NOVO="${3:-}"
    [ -z "$NOME" ] || [ -z "$NOVO" ] && echo "Uso: series.sh status 'Nome' <assistindo|concluída|pausada|quero ver>" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    jq --arg n "$MATCH" --arg s "$NOVO" '(.series[] | select(.name == $n)).status = $s' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "✅ '$MATCH' atualizada: $NOVO"
    ;;

  platform|plataforma)
    NOME="${2:-}"; PLAT="${3:-}"
    [ -z "$NOME" ] || [ -z "$PLAT" ] && echo "Uso: series.sh platform 'Nome' 'Plataforma'" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    jq --arg n "$MATCH" --arg p "$PLAT" '(.series[] | select(.name == $n)).platform = $p' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "✅ Plataforma de '$MATCH' definida: $PLAT"
    ;;

  note|nota)
    NOME="${2:-}"; NOTA="${3:-}"
    [ -z "$NOME" ] || [ -z "$NOTA" ] && echo "Uso: series.sh note 'Nome' 'texto'" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    jq --arg n "$MATCH" --arg nota "$NOTA" '(.series[] | select(.name == $n)).notes = $nota' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "✅ Nota adicionada em '$MATCH'."
    ;;

  episode|ep)
    NOME="${2:-}"; EP="${3:-}"
    [ -z "$NOME" ] || [ -z "$EP" ] && echo "Uso: series.sh episode 'Nome' 'S01E05'" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    jq --arg n "$MATCH" --arg ep "$EP" '(.series[] | select(.name == $n)).last_episode = $ep' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "✅ '$MATCH' — progresso atualizado: $EP"
    ;;

  notify|avisar)
    NOME="${2:-}"; ONOFF="${3:-on}"
    [ -z "$NOME" ] && echo "Uso: series.sh notify 'Nome' on|off" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    VAL="true"; [ "$ONOFF" = "off" ] && VAL="false"
    jq --arg n "$MATCH" --argjson v "$VAL" '(.series[] | select(.name == $n)).notify_new = $v' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "✅ Notificação de '$MATCH': $ONOFF"
    ;;

  remove|remover)
    NOME="${2:-}"
    [ -z "$NOME" ] && echo "Uso: series.sh remove 'Nome'" && exit 1
    MATCH=$(jq -r --arg n "$NOME" '.series[] | select(.name | ascii_downcase | contains($n | ascii_downcase)) | .name' "$FILE" | head -1)
    [ -z "$MATCH" ] && echo "Série não encontrada: $NOME" && exit 1
    jq --arg n "$MATCH" '.series = [.series[] | select(.name != $n)]' \
      "$FILE" > /tmp/series_tmp.json && mv /tmp/series_tmp.json "$FILE"
    echo "🗑️ '$MATCH' removida do catálogo."
    ;;

  *)
    echo "Comandos: list | assistindo | concluidas | quero | pausadas | add | done | pause | status | platform | note | episode | notify | remove"
    ;;
esac
