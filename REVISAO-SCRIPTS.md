# Revisão — telegram_agent.sh e finance.sh (2026-07-02)

Achados de revisão automatizada (multi-agente), em ordem de gravidade por arquivo.
**TODOS os achados foram corrigidos em 2026-07-02** (🔴 de manhã; 🟡/⚪ à tarde), exceto os dois marcados como risco aceito/documentado.

## finance.sh

- ✅ ~~🔴 **finance.sh:12-13 — bug de 100×**~~ CORRIGIDO: `to_cents` agora trata `.` como decimal quando é o último separador com 1-2 casas (`45.90` → R$ 45,90); pt-BR (`1.234,56`) segue ok. 15 casos testados.
- ✅ ~~🔴 **finance.sh:13**: `to_cents` devolvia 0 para não numérico~~ CORRIGIDO: valida com regex e devolve `ERR` (todos os callers já tratavam ERR).
- ✅ ~~🔴 injeção SQL via `$id`/`$lim`/`$mon`/`$n`~~ CORRIGIDO: `req_int`/`req_month` em pending, excepcional, recurrence, setcat, categorize, limits, groups, list, summary; `nivel` valida `^[0-3]$`.
- ✅ ~~🔴 **finance.sh:333**: `${labels[$n]}` avaliação aritmética~~ CORRIGIDO pela validação `^[0-3]$` de `$n`.
- ✅ ~~🟡 **finance.sh:419-427**: `balance <conta>` quebrado~~ CORRIGIDO: `CAST(a.id AS TEXT)` e `$where` interpolado na query — o filtro por conta funciona.
- ✅ ~~🟡 coluna `recurrence` sem migração~~ CORRIGIDO: adicionada em `migrate_cols` (finance.sh) e em `migrations.py` (web, roda na subida do serviço).
- ✅ ~~🟡 `sq()` sem busy timeout~~ CORRIGIDO: `sqlite3 -cmd '.timeout 5000'` — escrita concorrente com o Flask espera em vez de falhar.
- ✅ ~~🟡 "OK" impresso mesmo com escrita falha~~ CORRIGIDO: inserts checam o id retornado (add/transfer-add/rendimento; transfer-add remove débito órfão se o crédito falhar) e UPDATEs abortam com ERRO em falha.
- ✅ ~~⚪ divisão por zero no fx_rate~~ CORRIGIDO: rejeita `valor_para` = 0.
- ✅ ~~⚪ resolução de conta copiada 4×~~ CORRIGIDO: função `resolve_account` usada em transfer-add/rendimento/valuation.
- ✅ ~~⚪ `seed_categories` sem esc()~~ CORRIGIDO: todos os campos escapados.

## telegram_agent.sh

- ✅ ~~🔴 **telegram_agent.sh:214**: injeção de código via `$ip` em `python3 -c`~~ CORRIGIDO: `$ip` agora passa por `sys.argv[1]`.
- ✅ ~~🟡 busy-loop em `ok:false` da API~~ CORRIGIDO: backoff exponencial 5s→60s com log do motivo.
- ✅ ~~🟡 `rm` mesmo com `lp` falho~~ CORRIGIDO: em falha do lp o arquivo FICA na fila (retry automático) e o usuário é avisado — admin e kids.
- ✅ ~~🟡 `curl` sem timeout~~ CORRIGIDO: `--max-time` em todos (envio sem `--retry` p/ não duplicar mensagem; GET/downloads com `--retry 2`).
- ✅ ~~🟡 downloads sem checar exit code~~ CORRIGIDO: `curl -fsS ... || { limpa; avisa; return; }` nos 4 fluxos (voz, impressão admin, impressão kids c/ refund de cota, upload p/ análise).
- ✅ ~~🟡 subshells órfãos de heartbeat/status~~ CORRIGIDO: `trap cleanup EXIT` mata HBPID/STATPID em qualquer saída.
- ✅ ~~🟡 `reminders.json` sem lock~~ CORRIGIDO: `flock` compartilhado (`.lock`) entre process_reminders e reminder_add.sh.
- ✅ ~~🟡 `$TELEGRAM_CHAT_ID` sem guarda sob `set -u`~~ CORRIGIDO: `${TELEGRAM_CHAT_ID:-}` nos 2 pontos.
- ⚪ token do bot em argv do curl — **risco aceito e documentado em comentário** (host single-user).
- ✅ ~~⚪ tmpfiles previsíveis~~ CORRIGIDO: `mktemp --suffix` em voz/TTS.
- ✅ ~~⚪ regex de páginas pegava qualquer número~~ CORRIGIDO: exige contexto ("p. 1-3", "página 2") ou faixa/lista; número solto não conta. 7 casos testados.
- ✅ ~~⚪ colisão de nome na fila (mesmo segundo)~~ CORRIGIDO: `$(date +%s)_$$_$RANDOM`.
- ✅ ~~⚪ /api/devices refeito por MAC~~ CORRIGIDO: JSON baixado 1× por rodada e reutilizado.
- ✅ ~~⚪ lookup do registry copiado~~ CORRIGIDO: função `kid_chat_id` nos 3 lookups por nome (o lookup por chat_id é outro caso e ficou).

## Cruzado

- ⚪ escape de SQL duplicado entre os scripts — **mantido**: extrair lib compartilhada não compensa p/ 1 uso; consultas do agente seguem com escape inline comentado.
