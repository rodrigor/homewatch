# Revisão — telegram_agent.sh e finance.sh (2026-07-02)

Achados de revisão automatizada (multi-agente), em ordem de gravidade por arquivo.
Nenhum foi corrigido ainda — priorizar os marcados 🔴.

## finance.sh

- 🔴 **finance.sh:12-13 — bug de 100×**: `to_cents` remove TODOS os pontos antes de converter, então `add 45.90` lança **R$ 4.590,00** (o comentário promete aceitar "45.90"). Corrigir: tratar `.` como decimal quando for o último separador seguido de 1-2 dígitos.
- 🔴 **finance.sh:13**: `to_cents` devolve `0` (não ERR) para entrada não numérica — `add abc "x"` insere transação de R$ 0,00 em silêncio. Validar com regex antes do awk.
- 🔴 **finance.sh:168, 181, 209, 217, 254, 304, 309, 320-325, 332**: `$id`, `$lim`, `$mon`, `$n` interpolados no SQL sem `esc()` nem validação — injeção SQL via CLI. Validar `[[ $id =~ ^[0-9]+$ ]]` etc. no topo de cada comando.
- 🔴 **finance.sh:333**: `${labels[$n]}` com `$n` não validado — índice de array passa por avaliação aritmética do bash (execução de comando via `nivel cat 'a[$(cmd)]'`). Coberto pela validação numérica acima.
- 🟡 **finance.sh:419-427**: comando `balance <conta>` — `where` é montada mas nunca usada (sempre lista todas) e o SQL dela é inválido (`a.CAST(id AS TEXT)`).
- 🟡 **finance.sh:204, 209**: `recurrence` faz UPDATE numa coluna que nenhuma migração cria — falha com "no such column" a menos que o web app a tenha criado.
- 🟡 **finance.sh:8**: `sq()` sem busy timeout; com o Flask no mesmo `finance.db`, escrita concorrente falha com "database is locked" e o erro é engolido. Usar `sqlite3 -cmd '.timeout 5000'`.
- 🟡 **finance.sh:292-295, 217, 309, 413**: retorno do `sq` ignorado — imprime "OK #..." mesmo quando o INSERT falhou (Claude confirma lançamento que não existe).
- ⚪ **finance.sh:368**: divisão por zero no awk se `valor_para`=0 → `fx_rate` vira "inf" no banco.
- ⚪ **finance.sh:353-354, 393, 409**: resolução de conta por id/nome copiada 4×. Extrair `resolve_account`.
- ⚪ **finance.sh:100-101**: `seed_categories` interpola name/parent/icon sem `esc()` (dados constantes hoje).

## telegram_agent.sh

- 🔴 **telegram_agent.sh:214**: injeção de código — `$ip` (saída do arp-scan) interpolado dentro de `python3 -c`. Passar via `sys.argv`.
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
