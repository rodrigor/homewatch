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
projects(){ curl -s "${auth[@]}" "$API/project" | jq -ce 'if type=="array" then [{id:"inbox",name:"Inbox"}] + [.[]|select(.closed!=true)|{id,name}] else empty end'; }
# id de uma lista pelo nome (case-insensitive)
proj_id(){ projects | jq -r --arg n "$1" '.[]|select(.name|ascii_downcase==($n|ascii_downcase))|.id' | head -1; }
# todas as tarefas abertas, uma por linha (JSON), já com o nome da lista.
# A API só entrega tarefa lista a lista e limita a 200 requisições por minuto: a
# varredura (uma requisição por lista) vai em paralelo e fica em cache por 60s,
# para comandos em sequência (listar e depois concluir) não estourarem o limite.
CACHE="$DIR/state/ticktick_tasks.jsonl"
cache_drop(){ rm -f "$CACHE"; }
all_tasks(){
  if [ -f "$CACHE" ] && [ $(( $(date +%s) - $(date -r "$CACHE" +%s) )) -lt 60 ]; then cat "$CACHE"; return; fi
  local P T; P=$(projects 2>/dev/null)
  [ -z "$P" ] && { echo "FALHA: a API do TickTick não respondeu (token inválido ou limite de requisições)" >&2; return 1; }
  T=$(mktemp -d)
  # um arquivo por lista: as respostas em paralelo se misturariam no mesmo pipe
  jq -r '.[].id' <<< "$P" | xargs -P 8 -I{} curl -s "${auth[@]}" -o "$T/{}.json" "$API/project/{}/data"
  if grep -lq '"exceed_query_limit"' "$T"/*.json 2>/dev/null; then
    rm -rf "$T"; echo "FALHA: limite de requisições do TickTick (200/min); tente de novo em um minuto" >&2; return 1
  fi
  mkdir -p "$DIR/state"
  cat "$T"/*.json 2>/dev/null \
    | jq -c --argjson P "$P" '(.project.id // "inbox") as $pid|($P|map(select(.id==$pid))[0].name // "Inbox") as $l|.tasks[]?|select(.status==0)|.+{lista:$l}' 2>/dev/null > "$CACHE.$$"
  mv "$CACHE.$$" "$CACHE"; rm -rf "$T"; cat "$CACHE"
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
    cache_drop
    curl -s "${auth[@]}" "${json[@]}" -X POST "$API/task" -d "$body" \
      | jq -r --arg due "$due" 'if .id then "OK: \(.title)\(if $due!="" then " (vence \($due))" else "" end) [#\(.id)]" else "FALHA: \(tostring)" end'
    ;;
  today|hoje)  # atrasadas + as de hoje
    TASKS=$(all_tasks) || exit 1
    TZ="$TZNAME" jq -rs --arg h "$(hoje)" "$JQFMT"'
      [.[]|select(.dueDate)|select(dia<=$h)]|sort_by(.dueDate)
      |if length==0 then "Nada pra hoje." else (.[]|linha+(if dia<$h then " ⚠ atrasada" else "" end)) end' <<< "$TASKS"
    ;;
  overdue|atrasadas)
    TASKS=$(all_tasks) || exit 1
    TZ="$TZNAME" jq -rs --arg h "$(hoje)" "$JQFMT"'
      [.[]|select(.dueDate)|select(dia<$h)]|sort_by(.dueDate)|if length==0 then "(vazio)" else (.[]|linha) end' <<< "$TASKS"
    ;;
  postpone|mover-atrasadas)  # passa todas as atrasadas para hoje (dia todo); uma varredura só
    TASKS=$(all_tasks) || exit 1
    nd=$(norm_due hoje)
    ATR=$(TZ="$TZNAME" jq -rs --arg h "$(hoje)" "$JQFMT"'.[]|select(.dueDate)|select(dia<$h)|"\(.projectId)\t\(.id)\t\(.title)"' <<< "$TASKS")
    [ -z "$ATR" ] && { echo "Nenhuma atrasada."; exit 0; }
    n=0
    while IFS=$'\t' read -r pid id title; do
      body=$(jq -n --arg id "$id" --arg p "$pid" --arg d "${nd%|*}" --arg tz "$TZNAME" '{id:$id,projectId:$p,dueDate:$d,startDate:$d,isAllDay:true,timeZone:$tz}')
      if curl -s "${auth[@]}" "${json[@]}" -X POST "$API/task/$id" -d "$body" | jq -e '.id' >/dev/null 2>&1; then
        echo "movida: $title"; n=$((n+1))
      else echo "FALHA: $title (#$id)"; fi
    done <<< "$ATR"
    cache_drop
    echo "$n atrasada(s) movida(s) pra hoje"
    ;;
  week|semana)  # week [dias]  -> atrasadas + próximos N dias (padrão 7)
    ate=$(TZ="$TZNAME" python3 -c 'import sys,datetime as d; print(d.date.today()+d.timedelta(days=int(sys.argv[1])))' "${1:-7}")
    TASKS=$(all_tasks) || exit 1
    TZ="$TZNAME" jq -rs --arg a "$ate" "$JQFMT"'
      [.[]|select(.dueDate)|select(dia<=$a)]|sort_by(.dueDate)|if length==0 then "(vazio)" else (.[]|linha) end' <<< "$TASKS"
    ;;
  list)  # list [lista]  -> abertas de uma lista (ou de todas)
    TASKS=$(all_tasks) || exit 1
    [ -n "${1:-}" ] && TASKS=$(jq -c --arg l "$1" 'select(.lista|ascii_downcase==($l|ascii_downcase))' <<< "$TASKS")
    TZ="$TZNAME" jq -rs "$JQFMT"'if length==0 then "(vazio)" else (sort_by(.dueDate // "9")[]|linha) end' <<< "$TASKS"
    ;;
  done|concluir)  # done <texto|#id>
    IFS=$'\t' read -r pid id title <<< "$(find_task "${1:?uso: done <texto ou #id>}")"
    [ -z "${id:-}" ] && { echo "Não achei a tarefa: $1"; exit 1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X POST "$API/project/$pid/task/$id/complete"); cache_drop
    [ "$code" = "200" ] && echo "OK concluída: $title (#$id)" || echo "FALHA ($code)"
    ;;
  due|adiar)  # due <texto|#id> <vencimento>
    IFS=$'\t' read -r pid id title <<< "$(find_task "${1:?uso: due <texto ou #id> <vencimento>}")"
    [ -z "${id:-}" ] && { echo "Não achei a tarefa: $1"; exit 1; }
    nd=$(norm_due "${2:?informe o vencimento}") || { echo "Vencimento inválido: $2 (use hoje, amanha, AAAA-MM-DD ou AAAA-MM-DD HH:MM)"; exit 1; }
    body=$(jq -n --arg id "$id" --arg p "$pid" --arg d "${nd%|*}" --argjson a "${nd#*|}" --arg tz "$TZNAME" '{id:$id,projectId:$p,dueDate:$d,startDate:$d,isAllDay:$a,timeZone:$tz}')
    cache_drop
    curl -s "${auth[@]}" "${json[@]}" -X POST "$API/task/$id" -d "$body" \
      | jq -r --arg due "$2" 'if .id then "OK: \(.title) (vence \($due))" else "FALHA: \(tostring)" end'
    ;;
  del|apagar)  # del <#id>  (só por id, para não apagar a tarefa errada por trecho de título)
    q="${1:?uso: del <#id>}"; [[ "$q" == \#* ]] || { echo "Para apagar, informe o #id da tarefa (veja em list/today)."; exit 1; }
    IFS=$'\t' read -r pid id title <<< "$(find_task "$q")"
    [ -z "${id:-}" ] && { echo "Não achei a tarefa: $q"; exit 1; }
    code=$(curl -s -o /dev/null -w '%{http_code}' "${auth[@]}" -X DELETE "$API/project/$pid/task/$id"); cache_drop
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
  *) echo "uso: ticktick.sh {add|today|overdue|postpone|week|list|done|due|del|shop|projects|test}";;
esac
