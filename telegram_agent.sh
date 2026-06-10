#!/bin/bash
# homewatch/telegram_agent.sh — assistente Claude via Telegram (AGENTE TOTAL)
# Escuta o Telegram (long polling) e encaminha SÓ mensagens do chat autorizado para o Claude.
# Segurança: ignora qualquer remetente != TELEGRAM_CHAT_ID.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/config.env"
export PATH="$HOME/.local/bin:$PATH"
export HOME="${HOME:-/home/rodrigor}"
API="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
STATE="$DIR/state"
SESSION_FLAG="$STATE/agent_session_active"
OFFSET_FILE="$STATE/agent_offset"
MODEL_FILE="$STATE/agent_model"
get_model(){ cat "$MODEL_FILE" 2>/dev/null || echo "${CLAUDE_MODEL:-sonnet}"; }
WORKDIR="$DIR/agentwork"   # sessão isolada do agente (não colide com a sessão interativa em /home/rodrigor)
mkdir -p "$STATE"

tg(){ # tg <chat_id> <texto>  (texto puro — mensagens do sistema)
  curl -s -X POST "$API/sendMessage" \
    --data-urlencode "chat_id=$1" \
    --data-urlencode "text=$2" \
    --data-urlencode "disable_web_page_preview=true" >/dev/null
}
tg_html(){ # tg_html <chat_id> <texto_html>  (respostas do Claude com parse_mode=HTML)
  # se o Telegram rejeitar o HTML (tag quebrada etc.), reenvia como texto puro p/ não perder a mensagem
  local ok
  ok=$(curl -s -X POST "$API/sendMessage" \
    --data-urlencode "chat_id=$1" \
    --data-urlencode "text=$2" \
    --data-urlencode "parse_mode=HTML" \
    --data-urlencode "disable_web_page_preview=true" | jq -r '.ok // false')
  [ "$ok" = "true" ] || tg "$1" "$2"
}
tg_typing(){ curl -s -X POST "$API/sendChatAction" --data-urlencode "chat_id=$1" --data-urlencode "action=typing" >/dev/null; }
normalize_html(){ # converte Markdown→HTML (ponto único de normalização para Telegram)
  python3 "$DIR/normalize.py" html "$1"
}
tg_send_long(){ # normaliza MD→HTML e envia; divide em blocos de ~3900 quebrando em LINHAS
  # (split -b cortava bytes no meio de tag HTML ou de caractere UTF-8 → Telegram rejeitava o bloco)
  local cid="$1" raw="$2" txt chunk="" line nl=$'\n'
  txt=$(normalize_html "$raw")
  if [ "${#txt}" -le 3900 ]; then tg_html "$cid" "$txt"; return; fi
  while IFS= read -r line; do
    while [ "${#line}" -gt 3900 ]; do  # linha gigante (sem \n): corte duro por caracteres
      [ -n "$chunk" ] && { tg_html "$cid" "$chunk"; chunk=""; }
      tg_html "$cid" "${line:0:3900}"; line="${line:3900}"
    done
    if [ $(( ${#chunk} + ${#line} + 1 )) -gt 3900 ]; then
      tg_html "$cid" "$chunk"; chunk="$line"
    else
      chunk="${chunk}${chunk:+$nl}${line}"
    fi
  done <<< "$txt"
  [ -n "$chunk" ] && tg_html "$cid" "$chunk"
}
tg_voice(){ curl -s -F "chat_id=$1" -F "voice=@$2" "$API/sendVoice" >/dev/null; }
transcribe_voice(){ # <file_id> -> texto (stdout)
  local fid="$1" fp tmp
  fp=$(curl -s "$API/getFile?file_id=$fid" | jq -r '.result.file_path // empty')
  [ -z "$fp" ] && return
  tmp="/tmp/voice_$$_${RANDOM}.oga"
  curl -s -o "$tmp" "https://api.telegram.org/file/bot${TELEGRAM_BOT_TOKEN}/${fp}"
  "$DIR/transcribe.sh" "$tmp"
  rm -f "$tmp"
}
speak_to(){ # <chat> <texto> — gera voz pt-BR e envia como mensagem de voz
  local cid="$1" txt ogg="/tmp/say_$$_${RANDOM}.ogg"
  txt=$(printf '%s' "$2" | head -c 900)
  "$DIR/tts.sh" "$txt" "$ogg" && tg_voice "$cid" "$ogg"
  rm -f "$ogg"
}

PRINTER="${PRINTER:-EPSON_L4260}"
PQ="$DIR/print_queue"
mkdir -p "$PQ"
printer_host(){ lpstat -v "$PRINTER" 2>/dev/null | sed -n 's#.*://\([^:/]*\).*#\1#p' | head -1; }
printer_online(){ local h; h=$(printer_host); [ -n "$h" ] && ping -c1 -W2 "$h" >/dev/null 2>&1; }

print_telegram_file(){ # <chat> <file_id> <nome>
  local cid="$1" fid="$2" name="$3" cap="${4:-}"
  local fp tmp mime safe pages popt pmsg
  fp=$(curl -s "$API/getFile?file_id=$fid" | jq -r '.result.file_path // empty')
  if [ -z "$fp" ]; then tg "$cid" "❌ Não consegui baixar o arquivo do Telegram."; return; fi
  # páginas a partir da legenda (ex.: "1", "página 1", "2-4", "1,3"); vazio = todas
  pages=$(echo "$cap" | grep -oiE '[0-9]+([,-][0-9]+)*' | head -1)
  safe=$(echo "$name" | tr -c 'A-Za-z0-9._-' '_')
  tmp="$PQ/$(date +%s)~~${pages:-all}~~${safe}"
  curl -s -o "$tmp" "https://api.telegram.org/file/bot${TELEGRAM_BOT_TOKEN}/${fp}"
  mime=$(file -b --mime-type "$tmp" 2>/dev/null)
  case "$mime" in
    application/pdf|image/*|text/*) : ;;
    *) rm -f "$tmp"
       tg "$cid" "⚠️ Não imprimo \"$name\" ($mime) direto. Suporto PDF, imagens (JPG/PNG) e texto. (DOCX/XLSX precisariam de conversor — posso instalar se quiser.)"
       return ;;
  esac
  popt=""; pmsg=""
  if [ -n "$pages" ]; then popt="-P $pages"; pmsg=" (pág. $pages)"; fi
  if printer_online; then
    lp -d "$PRINTER" $popt -t "$name" "$tmp" >/dev/null 2>&1 && tg "$cid" "🖨️ Imprimindo \"$name\"$pmsg agora na $PRINTER."
    rm -f "$tmp"
  else
    tg "$cid" "📥 Recebi \"$name\"$pmsg, mas a impressora ($PRINTER) parece DESLIGADA. Liga ela que eu imprimo sozinho quando voltar (verifico a cada ~1 min). Fila: $(ls -1 "$PQ" | wc -l)."
  fi
}

process_print_queue(){ # imprime pendentes se a impressora estiver online
  shopt -s nullglob
  local files=("$PQ"/*)
  shopt -u nullglob
  [ ${#files[@]} -eq 0 ] && return
  printer_online || return
  local f base pages name popt pmsg
  for f in "${files[@]}"; do
    base=$(basename "$f")
    pages="${base#*~~}"; pages="${pages%%~~*}"
    name="${base##*~~}"
    popt=""; pmsg=""
    if [ "$pages" != "all" ] && [ -n "$pages" ]; then popt="-P $pages"; pmsg=" (pág. $pages)"; fi
    if lp -d "$PRINTER" $popt -t "$name" "$f" >/dev/null 2>&1; then
      [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "✅ Impressora voltou — imprimindo \"$name\"$pmsg (estava na fila)."
      rm -f "$f"
    fi
  done
}

KID_MAX_PAGES=20
KID_DAILY_MAX=15
kid_quota_take(){ # <arquivo_contador> — reserva 1 da cota diária; falha (exit 1) se estourou
  ( flock 9
    local c; c=$(cat "$1" 2>/dev/null || echo 0)
    [ "$c" -ge "$KID_DAILY_MAX" ] && exit 1
    echo $((c + 1)) > "$1"
  ) 9>>"$1.lock"
}
kid_quota_refund(){ # <arquivo_contador> — devolve 1 à cota (download/formato falhou)
  ( flock 9
    local c; c=$(cat "$1" 2>/dev/null || echo 0)
    [ "$c" -gt 0 ] && echo $((c - 1)) > "$1"
  ) 9>>"$1.lock"
}
kid_print(){ # <chat> <file_id> <nome> <caption> <KidName> — impressão com limites
  local cid="$1" fid="$2" name="$3" cap="$4" kn="$5"
  local day cntf fp tmp mime
  day=$(date +%Y%m%d); mkdir -p "$DIR/kids/$kn"; cntf="$DIR/kids/$kn/printcount_$day"
  if ! kid_quota_take "$cntf"; then
    tg "$cid" "📵 Você já imprimiu bastante hoje ($KID_DAILY_MAX). Amanhã libera de novo! Se precisar mesmo, fala com o papai. 😊"; return
  fi
  fp=$(curl -s "$API/getFile?file_id=$fid" | jq -r '.result.file_path // empty')
  [ -z "$fp" ] && { kid_quota_refund "$cntf"; tg "$cid" "❌ Não consegui baixar o arquivo."; return; }
  tmp="$PQ/$(date +%s)~~1-${KID_MAX_PAGES}~~$(echo "$name" | tr -c 'A-Za-z0-9._-' '_')"
  curl -s -o "$tmp" "https://api.telegram.org/file/bot${TELEGRAM_BOT_TOKEN}/${fp}"
  mime=$(file -b --mime-type "$tmp" 2>/dev/null)
  case "$mime" in application/pdf|image/*|text/*) : ;; *) rm -f "$tmp"; kid_quota_refund "$cntf"; tg "$cid" "⚠️ Só consigo imprimir PDF, foto ou texto. 😊"; return;; esac
  if printer_online; then
    lp -d "$PRINTER" -P "1-$KID_MAX_PAGES" -t "$name" "$tmp" >/dev/null 2>&1 && tg "$cid" "🖨️ Imprimindo \"$name\" (até $KID_MAX_PAGES págs)! Vai sair na impressora. 😊"
    rm -f "$tmp"
  else
    tg "$cid" "📥 Recebi \"$name\"! Mas a impressora tá desligada agora — quando ligarem eu imprimo automaticamente. 😉"
  fi
  [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "🖨️ $kn imprimiu \"$name\" ($mime)."
}

NDEV_IFACE=eth0
check_new_devices(){ # alerta o admin quando um MAC NOVO aparece na rede (a cada 5 min)
  local now last SEEN="$STATE/seen_macs.txt" ip mac vendor
  [ -f "$SEEN" ] || return
  [ -z "${TELEGRAM_CHAT_ID:-}" ] && return
  now=$(date +%s); last=$(cat "$STATE/newdev_last" 2>/dev/null || echo 0)
  [ $((now - last)) -lt 300 ] && return
  echo "$now" > "$STATE/newdev_last"
  while IFS=$'\t' read -r ip mac vendor; do
    mac=$(printf '%s' "$mac" | tr 'A-Z' 'a-z'); [ -z "$mac" ] && continue
    grep -qx "$mac" "$SEEN" && continue
    echo "$mac" >> "$SEEN"
    [ -z "$vendor" ] && vendor="(fabricante desconhecido)"
    tg "$TELEGRAM_CHAT_ID" "🚨 Novo dispositivo na rede!
IP: $ip · MAC: $mac
Fabricante: $vendor

Me diz o que é que eu catalogo. Ex.:
• \"é o celular do João, visitante\"
• \"é a TV nova da sala\"
• \"investiga o $ip\" (eu descubro sozinho)"
  done < <(arp-scan --interface="$NDEV_IFACE" --localnet --quiet --plain 2>/dev/null)
}

REMIND_F="$DIR/reminders.json"
deliver_reminder(){ # <target> <mensagem>
  local tgt="$1" msg="$2" cid name
  case "$tgt" in
    admin) [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "⏰ Lembrete: $msg";;
    all)
      while read -r cid name; do [ -n "${cid:-}" ] && tg "$cid" "⏰ Lembrete: $msg"; done < "$DIR/kids/registry.txt"
      [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "✅ Lembrete enviado p/ todos: $msg";;
    *)
      cid=$(awk -v n="$tgt" 'tolower($2)==tolower(n){print $1;exit}' "$DIR/kids/registry.txt" 2>/dev/null)
      if [ -n "$cid" ]; then
        tg "$cid" "⏰ Lembrete: $msg"
        [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "✅ Lembrete entregue p/ $tgt: $msg"
      else
        [ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "⚠️ Não achei o chat de '$tgt' p/ o lembrete: $msg"
      fi;;
  esac
}
process_reminders(){
  [ -f "$REMIND_F" ] || return
  local now last; now=$(date +%s); last=$(cat "$STATE/rem_last" 2>/dev/null || echo 0)
  [ $((now - last)) -lt 55 ] && return
  echo "$now" > "$STATE/rem_last"
  local pend; pend=$(jq '[.[]|select(.fired==false)]|length' "$REMIND_F" 2>/dev/null || echo 0)
  [ "${pend:-0}" -eq 0 ] && return
  local need_p arrivals=""; need_p=$(jq '[.[]|select(.fired==false and .type=="presence")]|length' "$REMIND_F" 2>/dev/null || echo 0)
  if [ "${need_p:-0}" -gt 0 ]; then
    local cur prev; cur=$(arp-scan --interface="$NDEV_IFACE" --localnet --quiet --plain 2>/dev/null | awk -F'\t' 'NF>=2{print tolower($2)}' | sort -u)
    prev=$(cat "$STATE/online_prev.txt" 2>/dev/null || echo "")
    [ -n "$prev" ] && arrivals=$(comm -13 <(printf '%s\n' "$prev") <(printf '%s\n' "$cur"))
    printf '%s\n' "$cur" > "$STATE/online_prev.txt"
  fi
  local id type target at message fire m macs tq
  while IFS=$'\t' read -r id type target at message; do
    fire=0
    [ "$type" = "time" ] && [ "$now" -ge "$at" ] && fire=1
    if [ "$type" = "presence" ] && [ -n "$arrivals" ]; then
      tq=${target//\'/\'\'}   # escapa aspas simples p/ o literal SQL
      macs=$(sqlite3 "$DIR/web/devices.db" "SELECT lower(mac) FROM device_meta WHERE lower(owner)=lower('$tq')" 2>/dev/null)
      for m in $macs; do printf '%s\n' "$arrivals" | grep -qx "$m" && fire=1; done
    fi
    if [ "$fire" = "1" ]; then
      deliver_reminder "$target" "$message"
      jq --arg id "$id" 'map(if .id==$id then .fired=true else . end)' "$REMIND_F" > "$REMIND_F.tmp" && mv "$REMIND_F.tmp" "$REMIND_F"
    fi
  done < <(jq -r '.[]|select(.fired==false)|[.id,.type,.target,(.at|tostring),.message]|@tsv' "$REMIND_F")
}

process_screen_nudges(){ # nudge de bem-estar p/ as filhas (uso contínuo), na persona delas
  local now hour last p cf today plast pday pcount cid l90 msg
  now=$(date +%s); hour=$(date +%H)
  { [ "$hour" -lt 9 ] || [ "$hour" -ge 22 ]; } && return   # só horário de vigília
  last=$(cat "$STATE/nudge_last" 2>/dev/null || echo 0)
  [ $((now - last)) -lt 1200 ] && return                   # checa no máx a cada 20 min
  echo "$now" > "$STATE/nudge_last"
  for p in Gabi Ana Rodrigo; do
    cf="$STATE/nudge_$p"; today=$(date +%Y%m%d)
    plast=$(sed -n 1p "$cf" 2>/dev/null || echo 0)
    pday=$(sed -n 2p "$cf" 2>/dev/null || echo "")
    pcount=$(sed -n 3p "$cf" 2>/dev/null || echo 0)
    [ "$pday" != "$today" ] && pcount=0
    [ $((now - plast)) -lt 10800 ] && continue   # cooldown 3h
    [ "${pcount:-0}" -ge 2 ] && continue          # máx 2/dia
    l90=$("$DIR/screen_usage.sh" "$p" 2>/dev/null | awk -F= '/^LAST90/{print $2}')
    if [ "${l90:-0}" -ge 45 ]; then               # ~uso contínuo na última 1h30
      if [ "$p" = "Rodrigo" ]; then cid="$TELEGRAM_CHAT_ID"
      else cid=$(awk -v n="$p" 'tolower($2)==tolower(n){print $1;exit}' "$DIR/kids/registry.txt" 2>/dev/null); fi
      msg=$("$DIR/kid_nudge.sh" "$p" pausa 2>/dev/null)
      [ -n "$cid" ] && [ -n "$msg" ] && tg "$cid" "$msg"
      printf '%s\n%s\n%s\n' "$now" "$today" "$((pcount + 1))" > "$cf"
    fi
  done
}

process_habits(){ # coach de hábitos: ritmo da semana + revisão de domingo + adaptação autônoma
  local today dow mon hour last pdir P cid f target cnt lastrev lastnudge missstreak cue strk msg need daysleft behind nt change
  today=$(date +%Y-%m-%d); dow=$(date +%u); mon=$(date -d "-$((dow-1)) days" +%Y-%m-%d); hour=$(date +%H)
  { [ "$hour" -lt 9 ] || [ "$hour" -ge 22 ]; } && return
  last=$(cat "$STATE/habit_last_day" 2>/dev/null || echo "")
  [ "$last" = "$today" ] && return
  echo "$today" > "$STATE/habit_last_day"
  [ -d "$DIR/habits" ] || return
  for pdir in "$DIR/habits"/*; do
    [ -d "$pdir" ] || continue
    P=$(basename "$pdir")
    if [ "$P" = "Rodrigo" ]; then cid="$TELEGRAM_CHAT_ID"
    else cid=$(awk -v n="$P" 'tolower($2)==tolower(n){print $1;exit}' "$DIR/kids/registry.txt" 2>/dev/null); fi
    [ -z "$cid" ] && continue
    for f in "$pdir"/*.json; do
      [ -f "$f" ] || continue
      [ "$(jq -r .status "$f")" = active ] || continue
      [ "$(jq -r .type "$f")" = weekly_count ] || continue
      target=$(jq -r .target_per_week "$f")
      cnt=$(jq --arg m "$mon" '[.log[]|select(.done and (.date>=$m))]|length' "$f")
      if [ "$dow" = "7" ]; then
        lastrev=$(jq -r '.last_review_week // ""' "$f")
        [ "$lastrev" = "$mon" ] && continue
        jq --arg m "$mon" '.last_review_week=$m' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
        met=0; [ "$cnt" -ge "$target" ] && met=1
        msg=$("$DIR/habit_analyze.sh" "$P" "$f" "$cnt" "$target" "$met")   # análise resultados+estratégia com OPUS
        [ -n "$msg" ] && tg "$cid" "$msg"
      else
        lastnudge=$(jq -r '.last_pace_week // ""' "$f")
        [ "$lastnudge" = "$mon" ] && continue
        [ "$cnt" -ge "$target" ] && continue
        need=$((target-cnt)); daysleft=$((7-dow)); behind=0
        [ "$need" -gt "$daysleft" ] && behind=1
        { [ "$cnt" -eq 0 ] && [ "$dow" -ge 4 ]; } && behind=1
        if [ "$dow" -ge 3 ] && [ "$behind" = "1" ]; then
          jq --arg m "$mon" '.last_pace_week=$m' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
          msg=$("$DIR/habit_coach.sh" "$P" "$f" pace "$cnt de $target, faltam $daysleft dias")
          [ -n "$msg" ] && tg "$cid" "$msg"
        fi
      fi
    done
  done
}

# Ignora mensagens antigas: começa do último update_id+1
OFFSET=$(cat "$OFFSET_FILE" 2>/dev/null || echo 0)
if [ "$OFFSET" = "0" ]; then
  last=$(curl -s "$API/getUpdates?offset=-1" | jq -r '.result[-1].update_id // 0')
  OFFSET=$((last + 1)); echo "$OFFSET" > "$OFFSET_FILE"
fi
[ -n "${TELEGRAM_CHAT_ID:-}" ] && tg "$TELEGRAM_CHAT_ID" "🟢 PIrrai online (modelo: $(get_model)). Pergunte, peça ações no Pi, ou envie PDF/foto p/ imprimir. /opus = mais raciocínio · /sonnet = padrão · 'opus: ...' p/ uma pergunta só · /reset limpa a conversa."

while true; do
  process_print_queue
  check_new_devices
  process_reminders
  process_screen_nudges
  process_habits
  echo "$(date +%s)" > "$STATE/heartbeat"   # watchdog: prova de vida do loop
  RESP=$(curl -s --max-time 60 "$API/getUpdates?offset=${OFFSET}&timeout=50")
  [ -z "$RESP" ] && sleep 2 && continue
  while IFS= read -r upd; do
    uid=$(echo "$upd" | jq -r '.update_id')
    OFFSET=$((uid + 1)); echo "$OFFSET" > "$OFFSET_FILE"
    from=$(echo "$upd" | jq -r '.message.from.id // empty')
    chat=$(echo "$upd" | jq -r '.message.chat.id // empty')
    text=$(echo "$upd" | jq -r '.message.text // empty')
    doc_id=$(echo "$upd" | jq -r '.message.document.file_id // empty')
    doc_name=$(echo "$upd" | jq -r '.message.document.file_name // "documento"')
    photo_id=$(echo "$upd" | jq -r '.message.photo[-1].file_id // empty')
    caption=$(echo "$upd" | jq -r '.message.caption // empty')
    voice_id=$(echo "$upd" | jq -r '.message.voice.file_id // .message.audio.file_id // empty')
    # PAPEL pelo chat_id: admin (Rodrigo) | kid (filha registrada) | desconhecido (ignora)
    if [ "$from" = "$TELEGRAM_CHAT_ID" ] || [ "$chat" = "$TELEGRAM_CHAT_ID" ]; then
      ROLE="admin"; KIDNAME=""
    else
      KIDNAME=$(awk -v c="$from" '$1==c{print $2; exit}' "$DIR/kids/registry.txt" 2>/dev/null)
      if [ -n "$KIDNAME" ]; then ROLE="kid"; else
        echo "[agent] IGNORADO não autorizado: from=$from chat=$chat"; continue
      fi
    fi

    # ===== ÁUDIO: transcreve voz -> texto (whisper local) =====
    WANT_VOICE=0
    if [ -n "$voice_id" ]; then
      tg_typing "$chat"
      text=$(transcribe_voice "$voice_id")
      WANT_VOICE=1
      if [ -z "$text" ]; then tg "$chat" "🎙️ Não consegui entender o áudio, pode repetir?"; continue; fi
      tg "$chat" "📝 (entendi: \"$text\")"
    fi
    # pedido explícito de resposta falada em texto
    echo "$text" | grep -qiE 'responde.*(falando|voz|.udio)|em (.udio|voz)|manda.*(.udio)|por (.udio|voz)' && WANT_VOICE=1

    # ===== CAMINHO DAS FILHAS (sandbox: conversa + impressão limitada) =====
    if [ "$ROLE" = "kid" ]; then
      if [ -n "$doc_id" ]; then kid_print "$chat" "$doc_id" "$doc_name" "$caption" "$KIDNAME"; continue; fi
      if [ -n "$photo_id" ]; then kid_print "$chat" "$photo_id" "foto.jpg" "$caption" "$KIDNAME"; continue; fi
      [ -z "$text" ] && continue
      tg_typing "$chat"
      RK=$("$DIR/kid_handler.sh" "$chat" "$KIDNAME" "$text" 2>>"$STATE/kid.log")
      tg_send_long "$chat" "$RK"
      [ "${WANT_VOICE:-0}" = "1" ] && speak_to "$chat" "$RK"
      continue
    fi

    # ===== CAMINHO ADMIN =====
    # foto ou documento: imprime só se a legenda pedir explicitamente; caso contrário analisa com Claude
    if [ -n "$doc_id" ] || [ -n "$photo_id" ]; then
      if echo "$caption" | grep -qiE '(imprimir|imprima|imprime|impressao|print)'; then
        # pedido explícito de impressão
        if [ -n "$doc_id" ]; then
          print_telegram_file "$chat" "$doc_id" "$doc_name" "$caption"
        else
          print_telegram_file "$chat" "$photo_id" "foto.jpg" "$caption"
        fi
        continue
      else
        # sem pedido de impressão → baixa e analisa com Claude
        UPFID="${photo_id:-$doc_id}"
        UPNAME="${doc_name:-foto.jpg}"; [ -n "$photo_id" ] && UPNAME="foto.jpg"
        UPFP=$(curl -s "$API/getFile?file_id=$UPFID" | jq -r '.result.file_path // empty')
        if [ -z "$UPFP" ]; then tg "$chat" "❌ Não consegui baixar o arquivo."; continue; fi
        UPTMP="$WORKDIR/upload_$(date +%s)_${UPNAME//[^A-Za-z0-9._-]/_}"
        curl -s -o "$UPTMP" "https://api.telegram.org/file/bot${TELEGRAM_BOT_TOKEN}/${UPFP}"
        text="Arquivo recebido: $UPNAME (caminho: $UPTMP)"
        [ -n "$caption" ] && text="$text — legenda/pergunta do usuário: $caption"
        text="$text. Leia e analise o arquivo usando a ferramenta Read. Para imprimir, o usuário deve dizer explicitamente 'imprimir'."
        # não faz continue: cai no bloco do Claude abaixo
      fi
    fi
    [ -z "$text" ] && continue
    case "$text" in
      /reset|/novo) rm -f "$SESSION_FLAG"; tg "$chat" "🧹 Conversa reiniciada."; continue;;
      /opus|/sonnet|/haiku) m="${text#/}"; echo "$m" > "$MODEL_FILE"; tg "$chat" "🧠 Modelo padrão agora: $m."; continue;;
      /modelo|/model) tg "$chat" "🧠 Modelo atual: $(get_model). Troque com /opus, /sonnet ou /haiku. Para uma pergunta só, use prefixo — ex.: opus: analise a fundo o dispositivo .104"; continue;;
      /start|/help) tg "$chat" "Sou o PIrrai (agente total no Pi). Pergunte ou peça ações (status, rede, Pi-hole, serviços...). 📷 Envie foto/print → analiso o conteúdo. 🖨️ Para imprimir, diga 'imprimir' na legenda (ex.: 'imprimir p. 1-3'). 🧠 Modelo: $(get_model) — /opus mais raciocínio, /sonnet padrão, ou prefixo 'opus:' numa pergunta. /reset limpa o contexto."; continue;;
    esac
    # resolve modelo: padrão (arquivo) ou override por prefixo "opus:/sonnet:/haiku:"
    USEMODEL=$(get_model)
    pfx="${text%%:*}"
    if [ "$pfx" != "$text" ]; then
      case "$pfx" in opus|sonnet|haiku) USEMODEL="$pfx"; text="${text#*:}"; text="${text# }";; esac
    fi
    tg_typing "$chat"
    # typing heartbeat: renova "digitando..." a cada 5s enquanto claude processa
    ( while true; do sleep 5; tg_typing "$chat"; done ) &
    HBPID=$!
    # status message se demorar mais de 40s
    ( sleep 40 && tg "$chat" "⏳ Operação em andamento, aguarde..." ) &
    STATPID=$!
    SYS=$(cat <<'ENDSYS'
Você é o "PIrrai", assistente que opera o Raspberry Pi de casa (Pi-hole/DNS, Debian 13) via Telegram, em pt-BR. Poder total no sistema (sudo sem senha). Seja conciso (resposta de chat, não relatório gigante). Confirme o que fez.
DADOS: Pi-hole em /etc/pihole/pihole-FTL.db (sqlite, view queries com timestamp,status,domain,client; bloqueio = status IN (1,4,5,6,7,8,9,10,11,15)). Rede: arp-scan, nmap, ip.
HABILIDADE IDENTIFICAR DISPOSITIVO: rode /home/rodrigor/homewatch/investigate.sh <ip|mac> (coleta fabricante, DNS das ultimas 24h, assinaturas de marca, nmap, SMB). Interprete as evidencias e diga o que o aparelho e, citando a prova (ex.: avs-alexa=Echo/Alexa; api.pix-star=porta-retrato Pix-Star; tuya=tomada/lampada smart; netbios/SMB=NAS ou frame). DNS e por IP e o DHCP troca IPs: priorize as ULTIMAS 24h, nao o historico.
HABILIDADE CATALOGAR: o inventario aceita POST em http://127.0.0.1:8080/api/device/MAC com JSON dos campos name,type,location,owner,brand_model,notes,icon,trusted(true/false),connection,status. type permitido: celular,notebook,desktop,tablet,TV,smart speaker,camera,IoT,console,NAS,impressora,roteador/rede,relogio,eletrodomestico,outro. Ao identificar um aparelho a pedido do usuario, JA catalogue (name,type,brand_model,icon,connection,trusted) e confirme o que registrou; se ficar em duvida real, pergunte antes de marcar. O campo status aceita: ativo, visitante, emprestado, aposentado.
CLASSIFICAR DISPOSITIVO NOVO: quando chegar um alerta de dispositivo novo e o usuario responder de quem e / se e conhecido ou visitante (ex.: "e o celular do Joao, visitante"), catalogue aquele IP/MAC: defina name (ex.: "Celular do Joao"), owner (Joao), trusted=true, e status=visitante se for visitante (senao ativo). Descubra o MAC do IP rodando investigate.sh ou consultando a rede. Confirme o que registrou.
RECADO PARA AS FILHAS: para enviar mensagem/lembrete as filhas no Telegram delas, rode /home/rodrigor/homewatch/notify_kids.sh "mensagem" [Gabi|Ana|all]. Ex.: avisar as duas -> notify_kids.sh "nao esquecam de arrumar o quarto" all. Confirme para quem enviou.
LEMBRETES (data/hora ou por chegada em casa): rode /home/rodrigor/homewatch/reminder_add.sh <target> <time|presence> <quando> <mensagem>. target: Gabi, Ana, Ayla, admin, all. time: <quando> e data/hora que o `date -d` entende (ex.: "tomorrow 08:00", "2026-06-10 18:00", "18:00") — rode `date` antes p/ saber a hora atual e calcular certo. presence: <quando>="-" e dispara quando o aparelho do target chega na rede (ex.: reminder_add.sh Ana presence - "tomar o remedio quando chegar"). Sempre confirme o lembrete criado (target e quando).
HABITOS (coach de bons hábitos; ferramenta /home/rodrigor/homewatch/habit.sh; hábitos são PRIVADOS por pessoa — aqui você cuida dos do Rodrigo):
- Registrar prática + MÉTRICA: quando o Rodrigo disser que praticou, rode habit.sh log Rodrigo "Exercício" <valor> <unidade> "<nota>" capturando a métrica que ele citou. Ex.: corri 5km -> habit.sh log Rodrigo Exercício 5 km corrida; treinei 40 min -> habit.sh log Rodrigo Exercício 40 min musculacao; sem número -> use o hífen no lugar do valor e da unidade. Depois habit.sh status Rodrigo e comemore o progresso, curtinho e genuíno (sem frieza), citando a métrica/evolução se fizer sentido.
- Progresso: habit.sh status Rodrigo (formato nome|feitos|meta|streak|metrica-da-semana). Hábitos de leitura usariam paginas/capitulos; corrida km; etc.
- Criar hábito novo: se pedir, faça mini-entrevista curta (qual, por quê, meta tipo Nx/semana ou diário, versão minizinha) e crie: habit.sh create Rodrigo <weekly_count|daily> <meta> <nome>; ajuste com habit.sh set Rodrigo <nome> why|tiny|cue_time <valor>. Confirme.
Hábito atual do Rodrigo: Exercício físico, meta 3x/semana.
TODOIST (tarefas e lista de compras do Rodrigo; ferramenta /home/rodrigor/homewatch/todoist.sh): quando o Rodrigo pedir pra anotar uma tarefa/afazer, ou um item de compra, use o Todoist.
- Anotar tarefa: todoist.sh add "texto" "vencimento em pt (ex: amanha 18h, sexta, toda segunda)" "Projeto opcional". Ex.: anota pagar o IPTU sexta -> todoist.sh add "pagar o IPTU" "sexta".
- Item de compra: todoist.sh shop "item" (vai pro projeto Compras). Ex.: poe leite na lista -> todoist.sh shop "leite".
- Tarefas de hoje: todoist.sh today. Listar c/ filtro Todoist: todoist.sh list "next 7 days". Ver compras: todoist.sh list "#Compras".
- Concluir: todoist.sh done "texto-da-tarefa" (ou done #id). Projetos: todoist.sh projects.
Confirme curtinho o que anotou/concluiu, citando o vencimento se houver. Diferenca p/ LEMBRETES: Todoist = lista de afazeres persistente do Rodrigo; reminder_add.sh = alerta pontual no Telegram por hora/chegada (e o unico jeito de avisar filhas/esposa).
IMPRESSÃO (regra obrigatória): NUNCA imprima automaticamente. Se receber arquivo ou imagem SEM instrução explícita, pergunte o que fazer (ex.: "O que devo fazer com esse arquivo?"). Só imprima se o usuário disser explicitamente "imprime", "manda imprimir" ou similar — nunca assuma.
FORMATO DE RESPOSTA (obrigatório): use HTML do Telegram — <b>negrito</b>, <i>itálico</i>, <code>código inline</code>, <pre>bloco de código</pre>. NÃO use Markdown (**, ##, __, ~~, ---). Listas com • ou números. Sem tabelas complexas. Seja conciso.
TAREFAS MULTI-ETAPAS (obrigatório para qualquer tarefa com 2+ passos): ANTES de executar, monte um plano e envie-o via /home/rodrigor/homewatch/tg_notify.sh com o HTML do Telegram. Depois execute cada etapa e notifique início e conclusão. Fluxo obrigatório:
1. Plano: rode tg_notify.sh "<b>📋 Plano:</b>\n1. etapa1\n2. etapa2\n..."
2. Início de cada etapa: tg_notify.sh "⏳ <b>Etapa N:</b> descrição..."
3. Conclusão de cada etapa: tg_notify.sh "✅ <b>Etapa N concluída</b> — resultado resumido"
4. Resposta final normal com o resumo geral.
Use tg_notify.sh também para avisos intermediários importantes (ex.: "nmap pode demorar ~2min", "aguardando scan..."). Isso mantém o usuário informado em tempo real.
ENDSYS
)
    if [ -f "$SESSION_FLAG" ]; then CONT="--continue"; else CONT=""; touch "$SESSION_FLAG"; fi
    REPLY=$(cd "$WORKDIR" && timeout "${CLAUDE_TIMEOUT:-180}" claude -p $CONT --model "$USEMODEL" --dangerously-skip-permissions --system-prompt "$SYS" "$text" 2>>"$STATE/agent.log")
    CLAUDE_EXIT=$?
    # para os processos de background
    kill "$HBPID" "$STATPID" 2>/dev/null; wait "$HBPID" "$STATPID" 2>/dev/null
    # --- recuperação automática ---
    if [ -z "$REPLY" ]; then
      if [ "$CLAUDE_EXIT" -eq 124 ]; then
        # timeout: avisa mas mantém sessão intacta
        tg "$chat" "⏱️ A operação demorou mais de ${CLAUDE_TIMEOUT:-180}s e foi interrompida. Tente novamente ou use /reset se o problema persistir."
      else
        # Nível 1: retry sem --continue (sessão limpa)
        rm -f "$SESSION_FLAG"
        REPLY=$(cd "$WORKDIR" && timeout "${CLAUDE_TIMEOUT:-180}" claude -p --model "$USEMODEL" --dangerously-skip-permissions --system-prompt "$SYS" "$text" 2>>"$STATE/agent.log")
        if [ -n "$REPLY" ]; then
          REPLY="[⚠️ Sessão reiniciada automaticamente]

$REPLY"
        else
          # Nível 2: falha definitiva
          REPLY="❌ Não consegui processar sua mensagem. Verifique state/agent.log para detalhes. Use /reset para limpar o contexto e tente novamente."
        fi
      fi
    fi
    tg_send_long "$chat" "$REPLY"
    [ "${WANT_VOICE:-0}" = "1" ] && speak_to "$chat" "$REPLY"
  done < <(echo "$RESP" | jq -c '.result[]?' 2>/dev/null)
done
