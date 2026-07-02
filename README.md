# homewatch 🏠🤖

Plataforma de automação pessoal rodando num **Raspberry Pi 4** — integra rede
(Pi-hole/roteador), finanças, agenda, hábitos e mais, tudo controlável pelo
Telegram com o **Claude CLI** como cérebro.

---

## Propósito

O **PIrrai** (apelido do bot) transforma o Raspberry Pi num assistente
doméstico 24/7. O que começou como monitor de rede virou uma plataforma pessoal
com vários módulos independentes, todos acessíveis por chat no Telegram e/ou por
dashboards web (expostos via Tailscale).

- 🔍 **Rede** — detecta dispositivos novos, identifica fabricantes, cataloga o inventário
- 🛡️ **Pi-hole** — consulta DNS, bloqueios e estatísticas
- 📡 **Roteador** — coletor SNMPv3 do ER605 dual-WAN (Claro/Vivo) + speedtest por operadora → Grafana
- 💰 **Finanças** — importa OFX/e-mails de compra, classifica por regras, split composto, dashboard web
- 📅 **Agenda** — unifica Google Calendar (iCal) + Todoist, acha horários livres
- 💪 **Hábitos** — metas semanais, nudges, revisão automática + dashboard (VO2, peso, exercício)
- 🖨️ **Impressão remota** — envie PDF/foto pelo Telegram e a impressora imprime
- ⏰ **Lembretes** — por horário ou por presença (quando um familiar chega na rede)
- 💬 **Filhas** — recados e nudges de bem-estar no Telegram de cada uma
- 📺 **Extras** — acompanhamento de séries, digest da Copa 2026, voz bidirecional (Whisper + TTS)

---

## Infraestrutura

- **Hardware:** Raspberry Pi 4 (ARM64), servidor doméstico permanente
- **SO:** Debian 13 (Trixie)
- **Rede:** exposição dos dashboards via **Tailscale** (`pirrai.tail*.ts.net`)

### Componentes de Software

| Componente | Função |
|---|---|
| **Claude CLI** (Anthropic) | Cérebro do assistente — modo `--print` com `--system-prompt` |
| **Telegram Bot API** | Interface de chat (long polling) |
| **Flask / Python 3** | APIs e dashboards (finanças, hábitos, inventário, landing) |
| **SQLite** | Bancos: `finance.db`, `web/devices.db`, `routerwatch.db`, `bgstats.db` |
| **Pi-hole** | DNS + bloqueio de anúncios; `pihole-FTL.db` para histórico DNS |
| **SNMP / speedtest-ookla** | Telemetria do roteador ER605 dual-WAN |
| **Grafana** | Painéis de rede/Pi (lê `routerwatch.db`) |
| **Whisper / TTS (Piper)** | Transcrição e síntese de voz |
| **arp-scan / nmap** | Varredura de rede para detecção de dispositivos |
| **systemd** | Serviços e timers (sempre online, auto-restart) |

---

## Arquitetura

```
Telegram ──→ telegram_agent.sh ──→ claude CLI (--system-prompt PIrrai)
                  │                        │
                  │                  Bash tools (arp-scan, sqlite3, curl,
                  │                  systemctl, nmap, lp, finance.sh, agenda.sh...)
                  │
     ┌────────────┼───────────────┬─────────────┬──────────────┐
  investigate  finance.sh       agenda.sh    habit.sh      notify_kids
  (dispos.)   (OFX/regras)   (gcal+todoist)  (metas)        (filhas)
                  │                                              │
        Flask dashboards (Tailscale) ──── landing.py (índice de serviços)
        ├─ web/finance/app.py  :8443  (finance.db)
        ├─ web/habitos/app.py  :8444
        └─ web/app.py          :8080  (inventário → Pi-hole + devices.db)

Coletores (systemd timers) → routerwatch.db → Grafana
  routerwatch.sh (SNMP)  routerspeed.sh (speedtest)  piwatch.sh (saúde do Pi)
```

---

## Módulos

| Módulo | Scripts principais | Descrição |
|---|---|---|
| **Telegram/Agente** | `telegram_agent.sh` | Loop principal Telegram → Claude (admin + filhas) |
| **Rede** | `investigate.sh`, `collect.sh`, `web/app.py` | Inventário de dispositivos, OUI/DNS/nmap |
| **Finanças** | `finance.sh`, `ofx_parser.py`, `finance_rules.py`, `finance_email.py`, `web/finance/app.py` | Importação OFX/e-mail, engine de regras, split composto, dashboard |
| **Agenda** | `agenda.py`/`agenda.sh`, `gcal.py`, `todoist.sh` | Google Calendar (iCal, leitura) + Todoist; horários livres |
| **Hábitos** | `habit*.sh`, `web/habitos/app.py` | CRUD de metas, nudges, revisão semanal, dashboard |
| **Roteador** | `routerwatch.sh`, `routerspeed.sh`, `routerwatch_alerts.sh`, `piwatch.sh` | Telemetria SNMP dual-WAN + speedtest + saúde do Pi → Grafana |
| **Filhas** | `kid_handler.sh`, `kid_nudge.sh`, `notify_kids.sh`, `screen_usage.sh` | Chat/nudges/tempo de tela das crianças |
| **Extras** | `series.sh`, `check_new_episodes.sh`, `copa_digest.sh`, `transcribe.sh`, `tts.sh`, `landing.py` | Séries, Copa 2026, voz, página inicial |
| **Infra** | `service_health.sh`, `homewatch-watchdog.sh`, `finance_backup.sh` | Watchdog, auto-restart e backups |

---

## Serviços & timers systemd

| Unit | Tipo | Função |
|---|---|---|
| `homewatch-agent` | serviço | Agente Telegram (sempre on) |
| `homewatch-web` / `finance-web` / `pirrai-landing` | serviço | Dashboards Flask (:8080 / :8443 / :8087) |
| `homewatch-watchdog`, `service_health` | serviço/timer | Watchdog dos serviços |
| `agenda-morning` | timer | Resumo matinal da agenda |
| `email-watch`, `finance-email`, `finance-alerts`, `finance-backup` | timers | Ingestão de e-mail, alertas e backup de finanças |
| `routerwatch`, `routerspeed`, `routerwatch-alerts`, `piwatch` | timers | Coleta de telemetria de rede/Pi |

> Dashboards ficam em `127.0.0.1` e são publicados na rede privada via `tailscale serve`.

---

## Configuração e Setup

### 1. Pré-requisitos

```bash
npm install -g @anthropic-ai/claude-code   # Claude CLI (Anthropic)
pip3 install flask python-dateutil         # deps Python
sudo apt install arp-scan nmap snmp        # ferramentas de rede
```

### 2. Configurar segredos

Cada módulo tem seu `*.env` (nunca commitado — ver `.gitignore`). Copie do
`.example` correspondente e preencha:

```bash
cp config.env.example config.env       # Telegram/Claude (núcleo)
cp finance.env.example finance.env     # IMAP de finanças
cp agenda.env.example agenda.env       # iCal do Google Calendar
cp gcal.env.example gcal.env           # OAuth do Google Calendar
# routerwatch.env, todoist.env, gcal_client.json: credenciais específicas
chmod 600 *.env
```

### 3. Ativar serviços

```bash
sudo cp *.service *.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now homewatch-agent homewatch-web finance-web
# timers de coleta/alertas:
sudo systemctl enable --now routerwatch.timer routerspeed.timer piwatch.timer \
     finance-email.timer finance-alerts.timer agenda-morning.timer
```

> No Pi, os units em `/etc/systemd/system/` são **symlinks** para este repositório.

---

## API do Inventário

`POST http://localhost:8080/api/device/{MAC}` (autenticado por token)

```json
{
  "name": "Celular do Rodrigo",
  "type": "celular",
  "owner": "Rodrigo",
  "brand_model": "iPhone 15",
  "trusted": true,
  "connection": "wifi",
  "status": "ativo"
}
```

Tipos aceitos: `celular`, `notebook`, `desktop`, `tablet`, `TV`, `smart speaker`,
`camera`, `IoT`, `console`, `NAS`, `impressora`, `roteador/rede`, `relogio`,
`eletrodomestico`, `outro`.

---

## Comandos do Bot (Telegram)

| Comando | Ação |
|---|---|
| `/reset` ou `/novo` | Reinicia o contexto da conversa |
| `/opus` `/sonnet` `/haiku` | Troca o modelo Claude |
| `opus: pergunta` | Usa Opus só para esta mensagem |
| Enviar PDF/foto | Imprime na impressora local |
| Enviar áudio | Transcreve (Whisper) e responde |

---

## Segurança

- Acesso restrito por `chat_id` do Telegram — só o admin (Rodrigo) e filhas registradas
- Segredos (`*.env`, `*.json`, `.secret`, `finance.db`) **nunca** commitados (ver `.gitignore`)
- Dashboards em `127.0.0.1`, publicados só na rede privada Tailscale
- Autenticação por token/sessão nos endpoints web

---

## Licença

Projeto pessoal / uso doméstico. Sem licença formal.
