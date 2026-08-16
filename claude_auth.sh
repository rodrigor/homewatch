#!/bin/bash
# claude_auth.sh — detecção e sinalização de falha de autenticação do Claude CLI.
#
# Problema que resolve: quando o login OAuth do `claude` expira (ou é revogado), o
# CLI imprime no STDOUT algo como
#   "Failed to authenticate. API Error: 401 OAuth access token has expired. Re-authenticate to continue."
# e sai com status 0. Para quem chama (telegram_agent.sh, finance_handler.sh...) isso
# é indistinguível de uma resposta válida do Claude: o erro cru era repassado ao
# Telegram e o retry automático repetia a mesma falha.
#
# Uso como biblioteca:
#   source "$DIR/claude_auth.sh"
#   if claude_auth_is_error "$REPLY"; then
#     claude_auth_mark_fail "agente"    # grava marcador p/ o service_health.sh alertar
#     REPLY=$(claude_auth_user_msg)     # mensagem clara em HTML do Telegram
#   else
#     claude_auth_mark_ok               # resposta válida => limpa o marcador
#   fi
#
# Uso como CLI:
#   ./claude_auth.sh status          mostra o marcador atual (se houver)
#   ./claude_auth.sh check [usuário] faz um probe real do CLI (gasta 1 request)
#   ./claude_auth.sh clear           apaga o marcador manualmente

CLAUDE_AUTH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_AUTH_STATE="$CLAUDE_AUTH_DIR/state"

# Há DOIS logins independentes na máquina (rodrigor e pirraikid), então o marcador
# é por escopo — senão um sucesso do agente apagaria a falha do chat das meninas.
CLAUDE_AUTH_SCOPES="rodrigor pirraikid"
claude_auth_mark_file(){ echo "$CLAUDE_AUTH_STATE/claude_auth_error_${1:-rodrigor}"; }

# Trechos que o CLI imprime quando a credencial não presta.
CLAUDE_AUTH_PATTERNS='Failed to authenticate|OAuth access token has expired|OAuth token has expired|Re-authenticate to continue|Invalid API key|API Error: 401|Please run /login|Please run `claude login`'

# Acima deste tamanho tratamos o texto como resposta legítima do Claude e não como
# erro do CLI — o erro real é sempre uma linha curta, e o próprio Rodrigo pode
# perguntar ao agente *sobre* esse erro (o texto apareceria na resposta).
CLAUDE_AUTH_MAX_LEN="${CLAUDE_AUTH_MAX_LEN:-400}"

# claude_auth_is_error <texto> -> 0 se o texto é o erro de autenticação do CLI
claude_auth_is_error(){
  local txt="${1:-}"
  [ -z "$txt" ] && return 1
  [ "${#txt}" -gt "$CLAUDE_AUTH_MAX_LEN" ] && return 1
  printf '%s' "$txt" | grep -qiE "$CLAUDE_AUTH_PATTERNS"
}

# claude_auth_mark_fail <origem> [escopo] — grava/atualiza o marcador (mantém o 1º horário)
claude_auth_mark_fail(){
  local origem="${1:-desconhecida}" mark first now
  mark=$(claude_auth_mark_file "${2:-rodrigor}")
  mkdir -p "$CLAUDE_AUTH_STATE"
  now=$(date +%s)
  first="$now"
  [ -f "$mark" ] && first=$(awk -F'|' 'NR==1{print $1}' "$mark" 2>/dev/null)
  [ -z "$first" ] && first="$now"
  printf '%s|%s|%s\n' "$first" "$now" "$origem" > "$mark"
}

# claude_auth_mark_ok [escopo] — chamado quando o Claude respondeu de verdade
claude_auth_mark_ok(){ rm -f "$(claude_auth_mark_file "${1:-rodrigor}")"; }

# claude_auth_failing [escopo] -> 0 se existe marcador ativo
claude_auth_failing(){ [ -f "$(claude_auth_mark_file "${1:-rodrigor}")" ]; }

# claude_auth_since [escopo] — segundos desde a 1ª falha registrada (0 se não há marcador)
claude_auth_since(){
  local mark first; mark=$(claude_auth_mark_file "${1:-rodrigor}")
  [ -f "$mark" ] || { echo 0; return; }
  first=$(awk -F'|' 'NR==1{print $1}' "$mark" 2>/dev/null)
  [ -z "$first" ] && { echo 0; return; }
  echo $(( $(date +%s) - first ))
}

# claude_auth_origin [escopo] — de onde veio a última falha
claude_auth_origin(){
  local mark; mark=$(claude_auth_mark_file "${1:-rodrigor}")
  [ -f "$mark" ] || return
  awk -F'|' 'NR==1{print $3}' "$mark" 2>/dev/null
}

# claude_auth_user_msg [escopo] — mensagem (HTML do Telegram) para o Rodrigo
claude_auth_user_msg(){
  if [ "${1:-rodrigor}" = "pirraikid" ]; then
    cat <<'MSG'
🔑 <b>O login do Claude do usuário <code>pirraikid</code> expirou.</b>

O chat das meninas, o coach de hábitos e os nudges estão fora do ar. No Pi:

<pre>sudo -H -u pirraikid claude    # dentro: /login</pre>
MSG
    return
  fi
  cat <<'MSG'
🔑 <b>O login do Claude no Pi expirou.</b>

Não consigo processar nada até renovar. No Pi, como <code>rodrigor</code>:

<pre>claude          # dentro: /login
sudo systemctl restart homewatch-agent.service</pre>

Ou, pra não expirar tão cedo: <code>claude setup-token</code>.
MSG
}

# claude_auth_check [usuário] — probe real do CLI. Ecoa "ok" / "auth" / "erro:<código>".
# Gasta 1 request; use sob demanda, não em loop de watchdog.
claude_auth_check(){
  local user="${1:-}" out rc bin="/usr/local/bin/claude"
  [ -x "$bin" ] || bin="claude"
  if [ -n "$user" ] && [ "$user" != "$(id -un)" ]; then
    out=$(printf 'responda apenas: ok' | timeout 60 sudo -n -H -u "$user" "$bin" -p --model sonnet 2>&1)
  else
    out=$(printf 'responda apenas: ok' | timeout 60 "$bin" -p --model sonnet 2>&1)
  fi
  rc=$?
  if claude_auth_is_error "$out"; then echo "auth"; return 2; fi
  [ "$rc" -ne 0 ] && { echo "erro:$rc"; return 1; }
  echo "ok"; return 0
}

# ── CLI ───────────────────────────────────────────────────────────────────────
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  case "${1:-status}" in
    status)
      rc=0
      for s in $CLAUDE_AUTH_SCOPES; do
        if claude_auth_failing "$s"; then
          printf '%-10s FALHANDO há %dmin — origem: %s\n' "$s" "$(( $(claude_auth_since "$s") / 60 ))" "$(claude_auth_origin "$s")"
          rc=2
        else
          printf '%-10s ok (sem falha registrada)\n' "$s"
        fi
      done
      exit "$rc"
      ;;
    check)
      shift
      for u in "${@:-$CLAUDE_AUTH_SCOPES}"; do
        printf '%-12s %s\n' "$u" "$(claude_auth_check "$u")"
      done
      ;;
    clear)
      shift
      for s in "${@:-$CLAUDE_AUTH_SCOPES}"; do claude_auth_mark_ok "$s"; done
      echo "marcador(es) limpo(s)"
      ;;
    *) echo "uso: $0 {status|check [usuário...]|clear}" >&2; exit 1;;
  esac
fi
