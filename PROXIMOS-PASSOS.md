# Próximos passos — homewatch / PIrrai

> Atualizado em 2026-07-02 após a sessão de implementação (curto prazo + refatoração + backlog).

## 🔴 Urgente — segurança
- [x] **Revogar** o PAT `ghp_…` antigo no GitHub *(revogado em 2026-07-02)*
- [x] **Reconfigurar o remote** sem token embutido → SSH (`git@github.com:rodrigor/homewatch.git`)
- [x] Chave SSH do Pi gerada e cadastrada no GitHub (`ssh -T git@github.com` autentica como `rodrigor`)
- [x] **Push** dos commits (`main` sincronizado com `origin/main`)
- [x] Conferir PAT em outros repos do Pi — varredura limpa (sem tokens, sem `.git-credentials`, sem credential.helper)

## 🟡 Curto prazo — higiene do repo
- [x] Auditar `*.env` / `*.json` de credenciais no Pi — todos 600, nenhum solto fora do repo
- [x] Symlinks em `/etc/systemd/system/` conferidos — 23 units, nenhum quebrado
- [x] `finance_alerts.sh` está versionado (git ls-files confirma)

## 🟢 Médio prazo — refatoração `web/finance` (CONCLUÍDA em 2026-07-02)
- [x] Monolito de 1.906 linhas quebrado em **blueprints**: `bp_auth`, `bp_dashboard`, `bp_transacoes`, `bp_favorecidos`, `bp_contas`, `bp_regras` + `core.py` (factory/helpers) + `migrations.py`
- [x] Templates extraídos para `templates/*.html` (base + 15 páginas + macros `_tx.html`); CSS/JS para `static/` (`app.css`, `app.js`, `smart.js`, `tx.js`)
- [x] CSS do `.modal` deduplicado (definição única no `app.css`; páginas só sobrescrevem tamanho)
- [x] `except: pass` do schema substituído por **migrações versionadas** (`schema_migrations`) com log de falha
- [x] `subprocess` dentro de request agora roda **em background** (`run_bg` com thread): alertas do `/api/tx/new` e pós-processamento do import OFX
- [x] **CSRF** em todos os POSTs (token na sessão + meta tag; JS injeta header `X-CSRF` em todo fetch e input escondido em todo form)
- [x] Chart.js 4.4.1 **vendorizado** em `static/chart.umd.js` (era CDN sem SRI)
- [x] Código morto removido (`LANDING_HTML`, ~92 linhas nunca usadas)

## 🔵 Backlog — qualidade geral (CONCLUÍDO em 2026-07-02)
- [x] **Testes**: 45 testes (`tests/`) — `ofx_parser` (parse/conta/conciliação), `finance_rules` (regras/keywords/score), helpers do core (`parse_cents`, `brl`, `money`) e smoke web (todas as rotas GET 200 + CSRF), rodando contra cópia do banco. Rodar com: `python3 -m unittest discover -s tests`
- [x] Migrações versionadas (tabela `schema_migrations`) no lugar do `_ensure_schema` ad-hoc
- [x] `telegram_agent.sh` e `finance.sh` revisados → **26 achados em `REVISAO-SCRIPTS.md`**

## ⏭️ Próxima fronteira (novo backlog)
- [ ] **Corrigir os achados 🔴 do `REVISAO-SCRIPTS.md`** — em especial o bug de 100× no `to_cents` do finance.sh e a injeção SQL via CLI
- [ ] Trocar o dev server do Flask por um WSGI de produção (gunicorn/waitress) nos 3 apps web
- [ ] Rodar os testes num hook de pre-commit ou timer (hoje é manual)
- [ ] Considerar extrair o CSS inline restante das páginas para o `app.css` (ficou só o page-specific)
