# Estado da sessão — 2026-06-11 (Claude Code no Mac)

Contexto para continuar o trabalho no Raspberry Pi. Sessão anterior analisou o
projeto, corrigiu 5 problemas de segurança/robustez e refinou o backlog de finanças.

## Commits desta sessão

- `cf2c0b9` — **fix: segurança e robustez** (5 itens):
  1. kid_handler: mensagem truncada/`<<SAVE` neutralizado, nick/bot_name ≤40 chars,
     seção SEGURANÇA no prompt (perfil/histórico/mensagem = dados, não instruções)
  2. telegram_agent: escape de aspas simples no SQL dos lembretes por presença
  3. web/app.py: `/api/authcheck` via header `X-Auth-Token` (não query string)
  4. `tg_send_long` divide por linha (split -b cortava tag HTML/UTF-8 no meio);
     `tg_html` cai para texto puro se o Telegram rejeitar o HTML
  5. `kid_print`: cota diária atômica com flock + estorno em falha
- `a23e29f` — **backlog finanças refinado** + `finance.env.example` + .gitignore

## Pendências imediatas no Pi

- [ ] Conferir se os serviços foram reiniciados após `cf2c0b9`:
      `sudo systemctl restart homewatch-agent homewatch-web`
- [ ] Criar `finance.env` (template em `finance.env.example`; a senha do e-mail
      `compras@mail.rodrigor.com` está com o Rodrigo — NUNCA commitar). `chmod 600`.
- [ ] Testar IMAP: `curl -s --url "imaps://mail.supremecluster.com:993/INBOX" --user "compras@mail.rodrigor.com:SENHA" -X "EXAMINE INBOX"`

## Módulo de finanças — decisões já tomadas (ver backlog.json, itens [FINANÇAS])

- 11 itens em 5 fases; F1 = finance.db + finance.sh + web com login + lançamento manual + **backup**
- Valores em **centavos INTEGER** (nunca float); `transactions.external_id` = FITID
  do OFX com UNIQUE (reimport idempotente)
- Usuários web: **rodrigor (admin)** e **ayla (editor — esposa)**; hash werkzeug
- Segurança: avaliar bind 127.0.0.1 + VPN (web/app.py hoje faz 0.0.0.0 — README
  diz localhost-only mas o código não cumpre)
- E-mail de compras: `compras@mail.rodrigor.com`, mail.supremecluster.com,
  IMAP 993 / SMTP 465 (SSL). Extração de transações: **Claude (haiku) como caminho
  principal** com schema rígido; parsers fixos só onde compensar. Corpo de e-mail
  é dado não-confiável (mesma defesa anti-injeção do kid_handler)
- Lançamento via Telegram precisa funcionar para a ayla — hoje o chat dela cai no
  kid_handler (sandbox sem ferramentas); definir caminho (item …319, notes)
- `finance.db` NÃO é reconstruível → item de backup é F1, antes de acumular dados
- Lacunas anotadas na análise, ainda sem item próprio: **receitas** (salário/entradas)
  e **despesas recorrentes fixas** (aluguel, assinaturas — não são parcelamento)

## Backlog (18 itens) — estado geral

- Todoist: `concluido` (todoist.sh + agenda_morning.sh + timer systemd)
- Abertos: Daily Digest, Obsidian (abordagem git definida), Alunos Ayty,
  Atividades Ayty/Uaná, Google Calendar, 12× FINANÇAS (F1–F5 + backup)

## Avisos técnicos (válidos para o ambiente Mac)

- `bash -n` no macOS (bash 3.2) FALHA no telegram_agent.sh por bug com heredoc
  dentro de `$( )` — não é erro do script; no Pi (bash 5) passa
- macOS não tem `flock` — testes de concorrência só no Pi/Linux

## Próximo passo sugerido

Implementar [FINANÇAS F1]: schema do finance.db + finance.sh (add/list/categorize/
accounts) + backup, na ordem. Itens `1781197317` e `1781204175` do backlog.json.
