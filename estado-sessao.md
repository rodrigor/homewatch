# Estado da sessão — 2026-08-16 (Claude Code na web)

Contexto para continuar no Raspberry Pi. Sessão investigou o 401 do agente do
Telegram, criou a detecção de falha de auth (PR #1) e descobriu que o coach de
hábitos do Rodrigo está morto em silêncio desde 07/08.

Branch: `claude/authentication-issue-sc8xvw` · PR (draft): https://github.com/rodrigor/homewatch/pull/1

---

## 1. O incidente do 401 — diagnóstico

Em 15/08 22:55 e 22:57 o agente respondeu no Telegram:

```
Failed to authenticate. API Error: 401 OAuth access token has expired. Re-authenticate to continue.
```

O `claude -p` imprime isso no **stdout** e sai com **status 0** — para quem chama é
indistinguível de resposta válida. Por isso o erro cru foi repassado ao Telegram e o
retry automático (que só dispara com `REPLY` vazio) repetiu a mesma falha.

**Mas notificações voltaram depois** (05:13 compra, 08:00 relatório). Isso NÃO é
contradição: há duas credenciais independentes na máquina.

| Credencial | Onde | Quem usa |
|---|---|---|
| Login OAuth interativo | `~/.claude/.credentials.json` | `homewatch-agent.service` — **o que expirou** |
| Token de longa duração | drop-in `claude-token.conf` (só no Pi, fora do git) | `email-watch.service` (ver commit `c9b82b8`) |

Detalhe: a mensagem das **06:00 ("Bom dia")** não usa Claude nenhum — `agenda_morning.sh`
só chama `todoist.sh`. Não serve como evidência. As de 05:13 (`finance_email.py:103`)
e 08:00 (`report.sh:29`) usam.

### Pendente: descobrir qual hipótese é a certa

- **(A)** `finance-email` e o cron do `report.sh` também têm drop-in de token longo →
  nunca dependeram da credencial quebrada, e **o agente segue quebrado**.
- **(B)** Só o agente usa o OAuth; o refresh falhou de forma transitória às 22:55 e se
  recuperou sozinho. (O agente respondia normal às 15:51 e quebrou ~7h depois, batendo
  com a vida útil típica do access token.)

Teste decisivo: **mandar qualquer mensagem pro bot.** Respondeu → (B). Deu 401 → (A).

```bash
ls -l /etc/systemd/system/*.service.d/           # quem tem drop-in
systemctl cat homewatch-agent finance-email      # e qual token cada um recebe
stat -c '%y' ~/.claude/.credentials.json         # mtime = último refresh bem-sucedido
grep -i "authenticate\|401" ~/homewatch/state/agent.log | tail
```

Se for (A), religar:

```bash
claude          # dentro: /login   (ou claude setup-token, que não expira tão cedo)
sudo systemctl restart homewatch-agent.service
```

---

## 2. O que já foi implementado (commitado e pushado)

`claude_auth.sh` (novo) — biblioteca sourceável + CLI:

- `claude_auth_is_error <texto>` detecta o padrão do CLI (401 / `Failed to authenticate`
  / `Invalid API key` / `Please run /login`). Ignora textos > 400 chars de propósito,
  senão uma conversa *sobre* o erro seria confundida com o erro.
- Marcador em `state/claude_auth_error_<escopo>`, por escopo, preservando o horário da
  1ª falha.
- CLI: `./claude_auth.sh status` · `check [usuário]` (probe real, gasta 1 request) · `clear`.

Ligado em:

- `telegram_agent.sh:661` — responde com instruções de `/login` e pula o retry inútil,
  preservando a sessão. Resposta válida limpa o marcador.
- `finance_handler.sh` / `kid_handler.sh` — mensagem compreensível para quem não
  administra o Pi, em vez do erro em inglês.
- `service_health.sh:156` — alerta no Telegram enquanto houver marcador. Sem probe
  periódico (não gasta request por rodada). **Só escopo `rodrigor`** — ver seção 3.

Testes: `bash tests/test_claude_auth.sh` (13 casos, passando). Não há CI no repo
(`.github/workflows/` não existe), então é execução manual.

---

## 3. Achado grave: o coach de hábitos do Rodrigo está morto desde 07/08

O commit `c9b82b8` (07/08) desativou o login do `pirraikid` — "as meninas não estão
usando". Mas o `pirraikid` nunca foi só das meninas: é **sandbox** do coach de hábitos,
que atende o próprio Rodrigo.

`telegram_agent.sh:349` `process_habits()` varre `habits/*/`; na linha 360,
`if [ "$P" = "Rodrigo" ]` manda pro chat dele. E daí saem:

- **:374** revisão de domingo → `habit_analyze.sh:37` → `sudo -H -u pirraikid claude --model opus`
- **:385** nudge de ritmo → `habit_coach.sh:34` → `sudo -H -u pirraikid claude --model sonnet`

Com o login desativado, ambos retornam vazio e `[ -n "$msg" ] && tg ...` engole:
sem mensagem, sem log, sem alerta.

**Pior — o flag é gravado ANTES da chamada:** `:372` marca `last_review_week` e `:384`
marca `last_pace_week`, e só depois chama o Claude. Cada domingo queima a revisão da
semana e cada nudge queima o da semana, sem retry. Como `habit_analyze.sh` é também
quem aplica `level_up` / `shrink_target` no JSON do hábito, **nenhuma adaptação foi
aplicada em ~9 dias**.

Continuou funcionando (e por isso não ficou óbvio): `habit_remind.sh` e
`habit_weekly.sh` não usam Claude — mandam texto template via `tg_notify.sh`.

### Decisão pendente

Como os hábitos são do Rodrigo, "desativar o pirraikid" tem duas leituras:

1. **Migrar `habit_coach.sh` e `habit_analyze.sh` para rodrigor** (tirar o
   `sudo -H -u pirraikid`), como já foi feito com as newsletters em `c9b82b8`. Mantém a
   funcionalidade, perde o sandbox — mas o conteúdo do prompt são os dados de hábito do
   próprio Rodrigo, risco baixo.
2. **Desativar junto** — perde nudges e revisão semanal até religar.

Independente da escolha, considerar mover a gravação de `last_review_week` /
`last_pace_week` para **depois** da chamada bem-sucedida, senão a falha silenciosa
continua queimando a semana.

### Já decidido nesta sessão

- Watchdog: **tirar o escopo `pirraikid`** — feito (`service_health.sh`, via
  `CLAUDE_AUTH_WATCH_SCOPES`, default `rodrigor`).
- Meninas (`kid_handler.sh:63`, `kid_nudge.sh:26`, `email_watch.py:237`):
  **remover as chamadas** que rodam claude como pirraikid. **AINDA NÃO FEITO.**

---

## 4. Fila de trabalho no Pi

- [ ] Rodar o teste decisivo do 401 (mandar mensagem pro bot) e resolver (A) ou (B)
- [ ] Decidir o destino do coach de hábitos (migrar × desativar)
- [ ] Remover as chamadas pirraikid das meninas (kid_handler, kid_nudge, email_watch:237)
- [ ] Mover os flags `last_review_week` / `last_pace_week` para depois da chamada
- [ ] Estender a detecção de auth aos scripts não-interativos, que hoje engolem o erro
      em silêncio: `vivo_watch.sh`, `apple_keynote_watch.sh`, `renewal_watch.sh`,
      `parent_summary.sh`, `report.sh`, `copa_digest.sh`, `digest.py`, `finance_email.py`
      (duas linhas cada, sourcing `claude_auth.sh`)
- [ ] Tirar o PR #1 de draft quando estiver validado no Pi
