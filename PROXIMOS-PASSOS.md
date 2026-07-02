# Próximos passos — homewatch / PIrrai

> Handoff da sessão de 2026-07-02 (análise do repo). Prioridade de cima p/ baixo.

## 🔴 Urgente — segurança
- [x] **Revogar** o PAT `ghp_…` antigo no GitHub *(revogado em 2026-07-02)*
- [x] **Reconfigurar o remote** sem token embutido → SSH (`git@github.com:rodrigor/homewatch.git`)
- [x] Chave SSH do Pi gerada e cadastrada no GitHub (`ssh -T git@github.com` autentica como `rodrigor`)
- [x] **Push** dos 8 commits novos (`main` sincronizado com `origin/main`)
- [x] Conferir se há PAT em outros repos do Pi — varredura limpa: nenhum token embutido, sem `.git-credentials`, sem credential.helper global

## 🟡 Curto prazo — higiene do repo
- [ ] Auditar demais `*.env` / `*.json` de credenciais no Pi que ainda não são versionados nem ignorados
- [ ] Confirmar que os units em `/etc/systemd/system/` (symlinks) batem com os arquivos recém-commitados
- [ ] Verificar se `finance_alerts.sh` (chamado em `app.py:1036`) está no repo — não apareceu como pendente; confirmar que não é arquivo faltante

## 🟢 Médio prazo — refatoração `web/finance/app.py` (maior alavancagem)
- [ ] Quebrar o monolito de ~1.900 linhas em **blueprints**: `financas`, `transacoes`, `contas`, `regras`, `api`
- [ ] Extrair templates inline (`BASE`, `SMART`, `TX_*`) para arquivos `.html` (`templates/`) e o CSS/JS para `static/`
- [ ] Remover CSS duplicado (`.modal` está em `BASE` e repetido em `financas`)
- [ ] Trocar `except: pass` do `_ensure_schema()` (app.py:127) por log de erro
- [ ] Tornar assíncronos os `subprocess` rodados dentro do request (`/api/tx/new`, import OFX)
- [ ] Adicionar CSRF (Flask-WTF) nos endpoints POST
- [ ] Vendorizar o Chart.js (hoje via CDN sem SRI, app.py:523)

## 🔵 Backlog — qualidade geral
- [ ] Introduzir testes (ao menos `ofx_parser`, `finance_rules`, `parse_cents`)
- [ ] Migrar o `_ensure_schema` ad-hoc para migrações versionadas
- [ ] Revisar os outros módulos grandes: `telegram_agent.sh` (~36 KB) e `finance.sh` (~26 KB)

---

### Contexto da sessão (o que já foi feito)
- Corrigidos 2 vazamentos no `.gitignore`: `routerwatch.env` e `web/habitos/.secret`
- README reescrito para o escopo atual da plataforma
- 8 commits temáticos criados (finance, agenda, routerwatch, web, habits, extras, docs, chore) — **ainda não enviados** (push pendente)
- Análise de segurança do `web/finance/app.py`: sem SQLi/command-injection, todos os endpoints com `@login_required`
