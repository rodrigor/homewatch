# homewatch 🏠🤖

Assistente doméstico inteligente rodando em Raspberry Pi — integra Pi-hole/DNS, Telegram e Claude AI para controle total da rede e da casa via chat.

---

## Propósito

O **PIrrai** (apelido do bot) é um agente de automação residencial que transforma o Raspberry Pi em um assistente acessível 24/7 pelo Telegram. Com ele é possível:

- 🔍 **Monitorar a rede** — detecta dispositivos novos, identifica fabricantes e catalogar o inventário
- 🛡️ **Controlar o Pi-hole** — consultar DNS, bloqueios e estatísticas
- 🖨️ **Imprimir remotamente** — envie PDF ou foto pelo Telegram e a impressora imprime
- ⏰ **Lembretes inteligentes** — por horário ou quando um familiar chega em casa (presença na rede)
- 💬 **Mensagens para as filhas** — recados direto no Telegram de cada uma
- 💪 **Coach de hábitos** — acompanha metas semanais com nudges e revisão automática
- 🎙️ **Voz bidirecional** — transcreve áudio (Whisper) e responde em voz (TTS)

---

## Infraestrutura

### Hardware
- **Raspberry Pi** (ARM64) — servidor doméstico permanente na rede local

### Sistema Operacional
- **Debian 13 (Trixie)**

### Componentes de Software

| Componente | Função |
|---|---|
| **Pi-hole** | DNS + bloqueio de anúncios; banco `pihole-FTL.db` para histórico DNS |
| **Claude AI** (Anthropic) | Cérebro do assistente — `claude` CLI em modo `--print` com `--system-prompt` |
| **Telegram Bot API** | Interface de chat (long polling) |
| **Flask / Python 3** | API REST para inventário de dispositivos (`localhost:8080`) |
| **SQLite** | Banco de dados do inventário (`web/devices.db`) |
| **Whisper** | Transcrição local de mensagens de voz |
| **arp-scan / nmap** | Varredura de rede para detecção de dispositivos |
| **systemd** | Gerenciamento dos serviços (sempre online, auto-restart) |

---

## Arquitetura

```
Telegram ──→ telegram_agent.sh ──→ claude CLI (--system-prompt PIrrai)
                  │                        │
                  │                  Bash tools (arp-scan, sqlite3,
                  │                  curl, systemctl, nmap, lp...)
                  │
                  ├──→ investigate.sh    (identifica dispositivos)
                  ├──→ notify_kids.sh    (mensagens para as filhas)
                  ├──→ reminder_add.sh   (cria lembretes)
                  ├──→ habit.sh          (registra e consulta hábitos)
                  └──→ web/app.py ←──── API REST (inventário)
                            │
                        Pi-hole DB + devices.db (SQLite)
```

---

## Estrutura do Projeto

```
homewatch/
├── telegram_agent.sh       # Loop principal: Telegram → Claude (admin + filhas)
├── investigate.sh          # Identifica dispositivos: OUI, DNS, nmap, SMB
├── habit.sh                # CRUD de hábitos pessoais (metas, log, status)
├── habit_coach.sh          # Gera nudge de ritmo via Claude
├── habit_analyze.sh        # Revisão semanal de hábitos via Claude
├── notify_kids.sh          # Envia mensagem para filha(s) via Telegram
├── reminder_add.sh         # Cria lembretes (time ou presence)
├── kid_handler.sh          # Responde filhas (Claude em modo criança)
├── kid_nudge.sh            # Nudge de bem-estar para filhas
├── screen_usage.sh         # Monitora tempo de tela
├── collect.sh              # Coleta métricas de rede
├── report.sh               # Gera relatório de atividade
├── parent_summary.sh       # Resumo parental
├── email_watch.py          # Monitora e-mail via IMAP
├── transcribe.sh           # Transcrição de áudio (Whisper)
├── tts.sh                  # Text-to-speech (resposta em voz)
├── get_chat_id.sh          # Descobre o chat_id do Telegram
├── homewatch-agent.service # Serviço systemd do agente Telegram
├── config.env.example      # Template de configuração (sem segredos)
└── web/
    ├── app.py              # API Flask — inventário de dispositivos
    └── homewatch-web.service  # Serviço systemd da API web
```

---

## Serviços systemd

| Serviço | Porta | Restart |
|---|---|---|
| `homewatch-agent` | — | Sempre (delay 5s) |
| `homewatch-web` | `8080` (local) | Sempre (delay 5s) |

Ambos iniciam automaticamente com a rede e o Pi-hole.

---

## Configuração e Setup

### 1. Pré-requisitos

```bash
# Claude CLI (Anthropic)
npm install -g @anthropic-ai/claude-code   # ou conforme documentação oficial

# Dependências Python
pip3 install flask

# Ferramentas de rede
sudo apt install arp-scan nmap
```

### 2. Configurar variáveis

```bash
cp config.env.example config.env
nano config.env   # preencha TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CLAUDE_MODEL
```

### 3. Registrar filhas (opcional)

```bash
# kids/registry.txt — uma linha por filha: chat_id NomeDaFilha
echo "987654321 Gabi" >> kids/registry.txt
echo "123456789 Ana"  >> kids/registry.txt
```

### 4. Ativar serviços

```bash
sudo cp homewatch-agent.service /etc/systemd/system/
sudo cp web/homewatch-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now homewatch-agent homewatch-web
```

---

## API do Inventário

`POST http://localhost:8080/api/device/{MAC}`

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

Tipos aceitos: `celular`, `notebook`, `desktop`, `tablet`, `TV`, `smart speaker`, `camera`, `IoT`, `console`, `NAS`, `impressora`, `roteador/rede`, `relogio`, `eletrodomestico`, `outro`.

---

## Comandos do Bot (Telegram)

| Comando | Ação |
|---|---|
| `/reset` ou `/novo` | Reinicia o contexto da conversa |
| `/opus` | Muda para modelo Claude Opus (mais raciocínio) |
| `/sonnet` | Volta ao modelo padrão (Sonnet) |
| `/haiku` | Modo rápido (Haiku) |
| `opus: pergunta` | Usa Opus só para esta mensagem |
| Enviar PDF/foto | Imprime na impressora local |

---

## Segurança

- Acesso restrito por `chat_id` do Telegram — apenas o admin (Rodrigo) e filhas registradas
- `config.env` e credenciais **nunca** commitados (ver `.gitignore`)
- API web acessível apenas localmente (`127.0.0.1:8080`)
- Autenticação por token no endpoint da API

---

## Licença

Projeto pessoal / uso doméstico. Sem licença formal.
