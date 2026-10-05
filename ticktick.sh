#!/bin/bash
# ticktick.sh: integração PIrrai <-> TickTick (Open API v1)
# Token em ticktick.env (TICKTICK_TOKEN=...). Cria em TickTick web > avatar >
# Configurações > Conta e segurança > API Token.
# A Open API não tem filtro nem linguagem natural de data: as listagens baixam as
# tarefas abertas de cada lista e filtram aqui; vencimento entra como data ISO.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -f "$DIR/ticktick.env" ] && source "$DIR/ticktick.env"
TOKEN="${TICKTICK_TOKEN:-}"
API="https://api.ticktick.com/open/v1"
TZNAME="${TICKTICK_TZ:-America/Recife}"
if [ -z "$TOKEN" ]; then echo "ERRO: TICKTICK_TOKEN não configurado em $DIR/ticktick.env"; exit 2; fi
auth=(-H "Authorization: Bearer $TOKEN")
json=(-H "Content-Type: application/json")

# listas do usuário + a Inbox (que a API não devolve em /project)
projects(){ curl -s "${auth[@]}" "$API/project" | jq -c '[{id:"inbox",name:"Inbox"}] + [.[]|select(.closed!=true)|{id,name}]'; }
# id de uma lista pelo nome (case-insensitive)
proj_id(){ projects | jq -r --arg n "$1" '.[]|select(.name|ascii_downcase==($n|ascii_downcase))|.id' | head -1; }
# todas as tarefas abertas, uma por linha (JSON), já com o nome da lista
all_tasks(){
  projects | jq -r '.[]|"\(.id)\t\(.name)"' | while IFS=$'\t' read -r pid pname; do
    curl -s "${auth[@]}" "$API/project/$pid/data" | jq -c --arg l "$pname" '.tasks[]?|select(.status==0)|.+{lista:$l}' 2>/dev/null
  done
}
# data local (YYYY-MM-DD) de hoje e normalização de vencimento:
# aceita hoje | amanha | AAAA-MM-DD | AAAA-MM-DD HH:MM  ->  "<iso>|<dia_todo>"
hoje(){ TZ="$TZNAME" date +%Y-%m-%d; }
norm_due(){
  TZ="$TZNAME" python3 -c '
import sys, re, datetime as d
s = sys.argv[1].strip().lower().replace("amanhã", "amanha")
m = re.match(r"^(hoje|amanha|\d{4}-\d{2}-\d{2})(?:[ t](\d{1,2}):(\d{2}))?$", s)
if not m: sys.exit(1)
dia = {"hoje": d.date.today(), "amanha": d.date.today() + d.timedelta(days=1)}.get(m.group(1)) or d.date.fromisoformat(m.group(1))
h, mi = (int(m.group(2)), int(m.group(3))) if m.group(2) else (0, 0)
dt = d.datetime(dia.year, dia.month, dia.day, h, mi).astimezone()
print(dt.strftime("%Y-%m-%dT%H:%M:%S%z") + "|" + ("false" if m.group(2) else "true"))
' "$1"
}
# filtro jq comum: vencimento em hora local e linha de exibição
JQFMT='def venc: if .dueDate then (.dueDate[0:19]+"Z"|fromdateiso8601|localtime|mktime) else null end;
def dia: venc|if . then strftime("%Y-%m-%d") else null end;
def rotulo: (.isAllDay==true) as $t|venc as $v|if $v then ($v|strftime(if $t then "%d/%m" else "%d/%m %H:%M" end)) else null end;
def linha: "• \(.title)\(if .dueDate then " (\(rotulo))" else "" end) [\(.lista)] [#\(.id)]";'
# acha uma tarefa aberta por #id ou por trecho do título -> "projectId<TAB>id<TAB>title"
find_task(){
  local q="$1"
  if [[ "$q" == \#* ]]; then all_tasks | jq -r --arg id "${q#\#}" 'select(.id==$id)|"\(.projectId)\t\(.id)\t\(.title)"' | head -1
  else all_tasks | jq -r --arg q "$q" 'select(.title|ascii_downcase|contains($q|ascii_downcase))|"\(.projectId)\t\(.id)\t\(.title)"' | head -1; fi
}

cmd="${1:-help}"; shift 2>/dev/null || true
case "$cmd" in
  add)  # add "texto" [vencimento] [lista] [prioridade 0|1|3|5] [descricao] [repeticao RRULE]
    title="${1:?uso: add \"texto\" [vencimento] [lista] [prioridade] [descricao] [repeticao]}"; due="${2:-}"; proj="${3:-}"; prio="${4:-}"; desc="${5:-}"; rep="${6:-}"
    body=$(jq -n --arg t "$title" '{title:$t}')
    if [ -n "$due" ]; then
      nd=$(norm_due "$due") || { echo "Vencimento inválido: $due (use hoje, amanha, AAAA-MM-DD ou AAAA-MM-DD HH:MM)"; exit 1; }
      body=$(jq --arg d "${nd%|*}" --argjson a "${nd#*|}" --arg tz "$TZNAME" '.+{dueDate:$d,startDate:$d,isAllDay:$a,timeZone:$tz}' <<< "$body")
    fi
    [ -n "$prio" ] && body=$(jq --argjson p "$prio" '.+{priority:$p}' <<< "$body")
    [ -n "$desc" ] && body=$(jq --arg c "$desc" '.+{content:$c}' <<< "$body")
    if [ -n "$rep" ]; then  # ex.: "RRULE:FREQ=WEEKLY;BYDAY=MO"; a repetição precisa de uma data de início
      [ -z "$due" ] && { echo "Tarefa repetida precisa de vencimento (a primeira ocorrência)."; exit 1; }
      body=$(jq --arg r "RRULE:${rep#RRULE:}" '.+{repeatFlag:$r}' <<< "$body")
    fi
    if [ -n "$proj" ]; then
      pid=$(proj_id "$proj")
      [ -z "$pid" ] && pid=$(curl -s "${auth[@]}" "${json[@]}" -X POST "$API/project" -d "$(jq -n --arg n "$proj" '{name:$n}')" | jq -r '.id // empty')
      [ -n "$pid" ] && body=$(jq --arg p "$pid" '.+{projectId:$p}' <<< "$body")
    fi
    curl -s "${auth[@]}" "${json[@]}" -X POST "$API/task" -d "$body" \
      | jq -r --arg due "$due" 'if .id then "OK: \(.title)\(if $due!="" then " (vence \($due))" else "" end) [#\(.id)]" else "FALHA: \(tostring)" end'
    ;;
  today|hoje)  # atrasadas + as de hoje
    all_tasks | TZ="$TZNAME" jq -rs --arg h "$(hoje)" "$JQFMT"'
      [.[]|select(.dueDate)|select(dia<=$h)]|sort_by(.dueDate)
      |if length==0 then "Nada pra hoje." else (.[]|linha+(if dia<$h then " ⚠ atrasada" else "" end)) end'
    ;;
  overdue|atrasadas)
    all_tasks | TZ="$TZNAME" jq -rs --arg h "$(hoje)" "$JQFMT"'
      [.[]|select(.dueDate)|select(dia<$h)]|sort_by(.dueDate)|if length==0 then "(vazio)" else (.[]|linha) end'
    ;;
  week|semana)  # week [dias]  -> atrasadas + próximos N dias (padrão 7)
    ate=$(TZ="$TZNAME" python3 -c 'import sys,datetime as d; print(d.date.today()+d.timedelta(days=int(sys.argv[1])))' "${1:-7}")
    all_tasks | TZ="$TZNAME" jq -rs --arg a "$ate" "$JQFMT"'
      [.[]|select(.dueDate)|select(dia<=$a)]|sort_by(.dueDate)|if length==0 then "(vazio)" else (.[]|linha) end'
    ;;
  list)  # list [lista]  -> abertas de uma lista (ou de todas)
    if [ -n "${1:-}" ]; then
      pid=$(proj_id "$1"); [ -z "$pid" ] && { echo "Não achei a lista: $1"; exit 1; }
      curl -s "${auth[@]}" "$API/project/$pid/data" | jq -c --arg l "$1" '.tasks[]?|select(.status==0)|.+{lista:$l}'
    else all_tasks; fi | TZ="$TZNAME" jq -rs "$JQFMT"'if length==0 then "(vazio)" else (sort_by(.dueDate // "9")[]|linha) end'
    ;;
  done|concluir)  # done <texto|#id>
    IFS=$'\t' read -r pid id title <<< "$(find_task "${1:?uso: done <texto ou #id>}")"
    [ -z "${id:-}" ] && { echo "Não achei a tarefa: $1"; exit 1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X POST "$API/project/$pid/task/$id/complete")
    [ "$code" = "200" ] && echo "OK concluída: $title (#$id)" || echo "FALHA ($code)"
    ;;
  due|adiar)  # due <texto|#id> <vencimento>
    IFS=$'\t' read -r pid id title <<< "$(find_task "${1:?uso: due <texto ou #id> <vencimento>}")"
    [ -z "${id:-}" ] && { echo "Não achei a tarefa: $1"; exit 1; }
    nd=$(norm_due "${2:?informe o vencimento}") || { echo "Vencimento inválido: $2 (use hoje, amanha, AAAA-MM-DD ou AAAA-MM-DD HH:MM)"; exit 1; }
    body=$(jq -n --arg id "$id" --arg p "$pid" --arg d "${nd%|*}" --argjson a "${nd#*|}" --arg tz "$TZNAME" '{id:$id,projectId:$p,dueDate:$d,startDate:$d,isAllDay:$a,timeZone:$tz}')
    curl -s "${auth[@]}" "${json[@]}" -X POST "$API/task/$id" -d "$body" \
      | jq -r --arg due "$2" 'if .id then "OK: \(.title) (vence \($due))" else "FALHA: \(tostring)" end'
    ;;
  del|apagar)  # del <#id>  (só por id, para não apagar a tarefa errada por trecho de título)
    q="${1:?uso: del <#id>}"; [[ "$q" == \#* ]] || { echo "Para apagar, informe o #id da tarefa (veja em list/today)."; exit 1; }
    IFS=$'\t' read -r pid id title <<< "$(find_task "$q")"
    [ -z "${id:-}" ] && { echo "Não achei a tarefa: $q"; exit 1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X DELETE "$API/project/$pid/task/$id")
    [ "$code" = "200" ] && echo "OK apagada: $title (#$id)" || echo "FALHA ($code)"
    ;;
  shop|compras)  # shop "item"  -> lista Compras
    item="${1:?uso: shop \"item\"}"
    exec "$0" add "$item" "" "Compras"
    ;;
  projects|listas)
    projects | jq -r '.[]|"• \(.name) [#\(.id)]"'
    ;;
  test)
    code=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" "$API/project")
    [ "$code" = "200" ] && echo "OK: token válido" || echo "FALHA: token inválido ($code)"
    ;;
  *) echo "uso: ticktick.sh {add|today|overdue|week|list|done|due|del|shop|projects|test}";;
esac
