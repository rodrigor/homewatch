#!/bin/bash
# backlog.sh — gerencia o backlog de funcionalidades do PIrrai
# Uso:
#   backlog.sh add "titulo" "descricao"   → adiciona item
#   backlog.sh list                        → lista todos
#   backlog.sh done <id>                   → marca como concluído
#   backlog.sh remove <id>                 → remove item

DIR="$(cd "$(dirname "$0")" && pwd)"
FILE="$DIR/backlog.json"
CMD="${1:-list}"

case "$CMD" in
  add)
    TITLE="${2:-}"
    DESC="${3:-}"
    [ -z "$TITLE" ] && echo "Uso: backlog.sh add 'titulo' 'descricao'" && exit 1
    ID=$(date +%s)
    DATE=$(date '+%Y-%m-%d')
    jq --arg id "$ID" --arg title "$TITLE" --arg desc "$DESC" --arg date "$DATE" \
      '.backlog += [{"id": $id, "title": $title, "description": $desc, "status": "backlog", "created": $date, "notes": ""}]' \
      "$FILE" > /tmp/backlog_tmp.json && mv /tmp/backlog_tmp.json "$FILE"
    echo "✅ Adicionado: $TITLE"
    ;;
  list)
    COUNT=$(jq '.backlog | length' "$FILE")
    if [ "$COUNT" -eq 0 ]; then
      echo "Backlog vazio."
    else
      echo "=== BACKLOG PIrrai ($COUNT itens) ==="
      jq -r '.backlog[] | "[\(.status)] #\(.id[-4:]) \(.title)\n    \(.description)\n    Criado: \(.created)\n"' "$FILE"
    fi
    ;;
  done)
    ID="${2:-}"
    [ -z "$ID" ] && echo "Uso: backlog.sh done <id>" && exit 1
    jq --arg id "$ID" '(.backlog[] | select(.id == $id or (.id | endswith($id)))) .status = "concluido"' \
      "$FILE" > /tmp/backlog_tmp.json && mv /tmp/backlog_tmp.json "$FILE"
    echo "✅ Marcado como concluído."
    ;;
  remove)
    ID="${2:-}"
    [ -z "$ID" ] && echo "Uso: backlog.sh remove <id>" && exit 1
    jq --arg id "$ID" '.backlog = [.backlog[] | select(.id != $id and (.id | endswith($id) | not))]' \
      "$FILE" > /tmp/backlog_tmp.json && mv /tmp/backlog_tmp.json "$FILE"
    echo "🗑️ Removido."
    ;;
  *)
    echo "Comandos: add | list | done | remove"
    ;;
esac
