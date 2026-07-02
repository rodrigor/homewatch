# Revisão — telegram_agent.sh e finance.sh (2026-07-02)

Achados de revisão automatizada (multi-agente), em ordem de gravidade por arquivo.
**Os 🔴 (e o `balance`) foram corrigidos em 2026-07-02** — restam os 🟡/⚪.

## finance.sh

- ✅ ~~🔴 **finance.sh:12-13 — bug de 100×**~~ CORRIGIDO: `to_cents` agora trata `.` como decimal quando é o último separador com 1-2 casas (`45.90` → R$ 45,90); pt-BR (`1.234,56`) segue ok. 15 casos testados.
- ✅ ~~🔴 **finance.sh:13**: `to_cents` devolvia 0 para não numérico~~ CORRIGIDO: valida com regex e devolve `ERR` (todos os callers já tratavam ERR).
- ✅ ~~🔴 injeção SQL via `$id`/`$lim`/`$mon`/`$n`~~ CORRIGIDO: `req_int`/`req_month` em pending, excepcional, recurrence, setcat, categorize, limits, groups, list, summary; `nivel` valida `^[0-3]$`.
- ✅ ~~🔴 **finance.sh:333**: `${labels[$n]}` avaliação aritmética~~ CORRIGIDO pela validação `^[0-3]$` de `$n`.
- ✅ ~~🟡 **finance.sh:419-427**: `balance <conta>` quebrado~~ CORRIGIDO: `CAST(a.id AS TEXT)` e `$where` interpolado na query — o filtro por conta funciona.
- 🟡 **finance.sh:204, 209**: `recurrence` faz UPDATE numa coluna que nenhuma migração cria — falha com "no such column" a menos que o web app a tenha criado.
- 🟡 **finance.sh:8**: `sq()` sem busy timeout; com o Flask no mesmo `finance.db`, escrita concorrente falha com "database is locked" e o erro é engolido. Usar `sqlite3 -cmd '.timeout 5000'`.
- 🟡 **finance.sh:292-295, 217, 309, 413**: retorno do `sq` ignorado — imprime "OK #..." mesmo quando o INSERT falhou (Claude confirma lançamento que não existe).
- ⚪ **finance.sh:368**: divisão por zero no awk se `valor_para`=0 → `fx_rate` vira "inf" no banco.
- ⚪ **finance.sh:353-354, 393, 409**: resolução de conta por id/nome copiada 4×. Extrair `resolve_account`.
- ⚪ **finance.sh:100-101**: `seed_categories` interpola name/parent/icon sem `esc()` (dados constantes hoje).

## telegram_agent.sh

- ✅ ~~🔴 **telegram_agent.sh:214**: injeção de código via `$ip` em `python3 -c`~~ CORRIGIDO: `$ip` agora passa por `sys.argv[1]`.
- 🟡 **telegram_agent.sh:376-377, 559**: loop principal não trata `ok:false` da API (ex.: HTTP 409 de instância duplicada) → busy-loop sem backoff.
- 🟡 **telegram_agent.sh:100-101, 156-157**: retorno do `lp` ignorado e `rm -f "$tmp"` incondicional — se a impressão falha, o arquivo é apagado em silêncio (process_print_queue:120 já faz certo).
- 🟡 **telegram_agent.sh:20-35, 60, 83, 149, 183, 209, 364, 453**: `curl` sem `--max-time`/`--retry` (exceto getUpdates) — um hang em `tg()` congela o agente inteiro.
- 🟡 **telegram_agent.sh:63, 89, 152, 456**: exit code do `curl -o` (download de arquivos) ignorado — em falha de rede continua com arquivo vazio/parcial.
- 🟡 **telegram_agent.sh:418, 482-486**: subshells de heartbeat/status só são mortos no caminho feliz — kill do systemd deixa loops órfãos mandando "typing" para sempre. Usar `trap ... EXIT`.
- 🟡 **telegram_agent.sh:286**: `reminders.json` reescrito sem lock enquanto `reminder_add.sh` pode escrever — lost update. Usar `flock`.
- 🟡 **telegram_agent.sh:308, 328**: `cid="$TELEGRAM_CHAT_ID"` sem `${:-}` sob `set -u` — se faltar no config.env, o agente morre.
- ⚪ **telegram_agent.sh:10, 63, 89, 152, 456**: token do bot na URL em argv do curl — visível em `ps` (host single-user, risco aceito/documentar).
- ⚪ **telegram_agent.sh:62, 68**: tmpfiles previsíveis (`voice_$$_$RANDOM.oga`) — usar `mktemp` como check_new_devices:177 já faz.
- ⚪ **telegram_agent.sh:86**: regex de páginas captura qualquer número da legenda ("imprimir contrato 2024" → `lp -P 2024`).
- ⚪ **telegram_agent.sh:88, 151**: nome de arquivo na fila só com `date +%s` — álbum de fotos no mesmo segundo sobrescreve.
- ⚪ **telegram_agent.sh:209-217**: `curl .../api/devices` refeito dentro do loop por MAC (a lista já foi baixada na 183).
- ⚪ **telegram_agent.sh:252, 309, 329, 394-395**: lookup em `kids/registry.txt` copiado 4×. Extrair `kid_chat_id`.

## Cruzado

- ⚪ Escape de SQL reimplementado inline no agente (`tq=${target//\'/\'\'}`) vs `esc()` do finance.sh — extrair helper comum ou padronizar consultas parametrizadas via stdin.
