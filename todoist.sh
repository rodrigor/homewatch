#!/bin/bash
# todoist.sh — integração PIrrai <-> Todoist (API unificada v1)
# Token em todoist.env (TODOIST_TOKEN=...). Pega em Todoist > Configurações > Integrações > Desenvolvedor.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/todoist.env" ] && source "$DIR/todoist.env"
TOKEN="${TODOIST_TOKEN:-}"
API="https://api.todoist.com/api/v1"
if [ -z "$TOKEN" ]; then echo "ERRO: TODOIST_TOKEN não configurado em $DIR/todoist.env"; exit 2; fi
auth=(-H "Authorization: Bearer $TOKEN")

# acha o id de um projeto pelo nome (case-insensitive)
proj_id(){ curl -s "${auth[@]}" "$API/projects?limit=200" | jq -r --arg n "$1" '.results[]|select(.name|ascii_downcase==($n|ascii_downcase))|.id' | head -1; }
# lista tarefas via filtro Todoist (query em linguagem natural)
filter_tasks(){ curl -s "${auth[@]}" -G "$API/tasks/filter" --data-urlencode "query=$1"; }

cmd="${1:-help}"; shift 2>/dev/null || true
case "$cmd" in
  add)  # add "texto" [vencimento_pt] [projeto] [prioridade 1-4]
    content="${1:?uso: add \"texto\" [vencimento] [projeto] [prioridade]}"; due="${2:-}"; proj="${3:-}"; prio="${4:-}"
    args=(--data-urlencode "content=$content")
    [ -n "$due" ]  && args+=(--data-urlencode "due_string=$due" --data-urlencode "due_lang=pt")
    [ -n "$prio" ] && args+=(--data-urlencode "priority=$prio")
    if [ -n "$proj" ]; then
      pid=$(proj_id "$proj")
      [ -z "$pid" ] && pid=$(curl -s "${auth[@]}" -X POST "$API/projects" --data-urlencode "name=$proj" | jq -r '.id // empty')
      [ -n "$pid" ] && args+=(--data-urlencode "project_id=$pid")
    fi
    curl -s "${auth[@]}" -X POST "$API/tasks" "${args[@]}" \
      | jq -r 'if .id then "OK: \(.content)\(if .due then " — vence \(.due.string)" else "" end)" else "FALHA: \(tostring)" end'
    ;;
  today|hoje)
    filter_tasks "today | overdue" \
      | jq -r 'if (.results|length)==0 then "Nada pra hoje 🎉" else (.results|sort_by(.due.date)[]|"• \(.content)\(if .due then " (\(.due.string))" else "" end) [#\(.id)]") end'
    ;;
  list)  # list [filtro_todoist]   ex.: "next 7 days", "#Compras", "p1"
    filter_tasks "${1:-today | overdue}" \
      | jq -r 'if (.results|length)==0 then "(vazio)" else (.results[]|"• \(.content) [#\(.id)]") end'
    ;;
  done|concluir)  # done <texto|#id>
    q="${1:?uso: done <texto ou #id>}"
    if [[ "$q" == \#* ]]; then id="${q#\#}"; else  # match por substring no conteúdo (case-insensitive)
      id=$(curl -s "${auth[@]}" "$API/tasks?limit=200" \
        | jq -r --arg q "$q" '[.results[]|select(.content|ascii_downcase|contains($q|ascii_downcase))][0].id // empty')
    fi
    [ -z "$id" ] && { echo "Não achei a tarefa: $q"; exit 1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X POST "$API/tasks/$id/close")
    [ "$code" = "204" ] && echo "OK concluída (#$id)" || echo "FALHA ($code)"
    ;;
  shop|compras)  # shop "item"  -> projeto Compras
    item="${1:?uso: shop \"item\"}"
    exec "$0" add "$item" "" "Compras"
    ;;
  projects|projetos)
    curl -s "${auth[@]}" "$API/projects?limit=200" | jq -r '.results[]|"• \(.name) [#\(.id)]"'
    ;;
  test)
    code=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$API/projects?limit=1")
    [ "$code" = "200" ] && echo "OK — token válido" || echo "FALHA — token inválido ($code)"
    ;;
  *) echo "uso: todoist.sh {add|today|list|done|shop|projects|test}";;
esac
