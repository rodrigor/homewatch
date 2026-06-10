#!/bin/bash
# emprestimos.sh — gerencia catálogo de empréstimos de jogos
# Uso:
#   emprestimos.sh list              → lista todos os empréstimos ativos
#   emprestimos.sh all               → lista todos (incluindo devolvidos)
#   emprestimos.sh devolver <id>     → marca como devolvido
#   emprestimos.sh add "Jogo" "Para" → registra novo empréstimo

DIR="$(cd "$(dirname "$0")" && pwd)"
FILE="$DIR/emprestimos.json"
CMD="${1:-list}"

case "$CMD" in
  list)
    echo "=== EMPRÉSTIMOS ATIVOS ==="
    jq -r '.emprestimos[] | select(.devolvido == false) |
      "#\(.id) \(.jogo)\n    → \(.para) desde \(.data)\(.obs | if . != "" then " | obs: " + . else "" end)\n"' "$FILE"
    ;;
  all)
    echo "=== TODOS OS EMPRÉSTIMOS ==="
    jq -r '.emprestimos[] |
      "#\(.id) [\(if .devolvido then "✓ devolvido" else "emprestado" end)] \(.jogo)\n    → \(.para) desde \(.data)\n"' "$FILE"
    ;;
  devolver)
    ID="${2:-}"
    [ -z "$ID" ] && echo "Uso: emprestimos.sh devolver <id>" && exit 1
    jq --argjson id "$ID" '(.emprestimos[] | select(.id == $id)).devolvido = true' \
      "$FILE" > /tmp/emp_tmp.json && mv /tmp/emp_tmp.json "$FILE"
    NOME=$(jq -r --argjson id "$ID" '.emprestimos[] | select(.id == $id) | .jogo' "$FILE")
    echo "✅ $NOME marcado como devolvido."
    ;;
  add)
    JOGO="${2:-}"; PARA="${3:-}"
    [ -z "$JOGO" ] && echo "Uso: emprestimos.sh add 'Jogo' 'Para'" && exit 1
    DATE=$(date '+%Y-%m-%d')
    LAST_ID=$(jq '.emprestimos | map(.id) | max' "$FILE")
    NEW_ID=$((LAST_ID + 1))
    jq --argjson id "$NEW_ID" --arg jogo "$JOGO" --arg para "$PARA" --arg date "$DATE" \
      '.emprestimos += [{"id": $id, "jogo": $jogo, "para": $para, "data": $date, "devolvido": false, "obs": ""}]' \
      "$FILE" > /tmp/emp_tmp.json && mv /tmp/emp_tmp.json "$FILE"
    echo "✅ Empréstimo registrado: $JOGO → $PARA"
    ;;
  *)
    echo "Comandos: list | all | devolver <id> | add 'Jogo' 'Para'"
    ;;
esac
