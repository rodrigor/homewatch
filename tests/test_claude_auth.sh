#!/bin/bash
# tests/test_claude_auth.sh — testes da detecção de falha de auth do Claude CLI.
# Roda isolado: aponta o state/ para um diretório temporário.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
source "$ROOT/claude_auth.sh"
CLAUDE_AUTH_STATE="$TMP/state"; mkdir -p "$CLAUDE_AUTH_STATE"

fails=0; total=0
ok(){   total=$((total+1)); printf '  ✓ %s\n' "$1"; }
bad(){  total=$((total+1)); fails=$((fails+1)); printf '  ✗ %s\n' "$1"; }
assert(){   if "${@:2}"; then ok "$1"; else bad "$1"; fi; }
refute(){   if "${@:2}"; then bad "$1"; else ok "$1"; fi; }

echo "detecção do erro:"
assert "erro real do CLI (mensagem do print do Rodrigo)" \
  claude_auth_is_error "Failed to authenticate. API Error: 401 OAuth access token has expired. Re-authenticate to continue."
assert "variante 'Invalid API key'" claude_auth_is_error "Invalid API key · Please run /login"
assert "case-insensitive" claude_auth_is_error "failed to authenticate"

echo "não confunde com resposta legítima:"
refute "resposta vazia" claude_auth_is_error ""
refute "resposta normal" claude_auth_is_error "Hoje você tem 3 tarefas na agenda."
LONGA="Sobre o erro que você viu: Failed to authenticate. API Error: 401 OAuth access token has expired. \
Isso acontece quando o login do CLI expira. $(printf 'x%.0s' {1..400})"
refute "texto longo falando SOBRE o erro (>${CLAUDE_AUTH_MAX_LEN} chars)" claude_auth_is_error "$LONGA"

echo "marcador por escopo:"
claude_auth_mark_ok rodrigor; claude_auth_mark_ok pirraikid
refute "começa limpo" claude_auth_failing rodrigor
claude_auth_mark_fail "agente" rodrigor
assert "marca rodrigor" claude_auth_failing rodrigor
refute "não vaza pra pirraikid" claude_auth_failing pirraikid
[ "$(claude_auth_origin rodrigor)" = "agente" ] && ok "guarda a origem" || bad "guarda a origem"

# o horário da 1ª falha é preservado entre marcações sucessivas
printf '%s|%s|%s\n' "$(( $(date +%s) - 600 ))" "$(date +%s)" "antiga" > "$(claude_auth_mark_file rodrigor)"
claude_auth_mark_fail "nova" rodrigor
[ "$(claude_auth_since rodrigor)" -ge 600 ] && ok "preserva o horário da 1ª falha" || bad "preserva o horário da 1ª falha"

claude_auth_mark_ok rodrigor
refute "sucesso limpa o marcador" claude_auth_failing rodrigor
[ "$(claude_auth_since rodrigor)" = "0" ] && ok "since=0 sem marcador" || bad "since=0 sem marcador"

echo
if [ "$fails" -eq 0 ]; then echo "✅ $total testes passaram"; else echo "❌ $fails de $total falharam"; fi
exit $(( fails > 0 ))
