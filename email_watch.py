#!/usr/bin/env python3
# email_watch.py — verifica o inbox do PIrrai (1 ciclo), valida remetente,
# notifica no Telegram e processa comandos com SEGURANÇA.
# Execução: como rodrigor (pode sudo -u pirraikid, ler email.env, chamar reminder_add.sh).
import imaplib, email, os, re, json, subprocess, time
from email.header import decode_header

DIR = "/home/rodrigor/homewatch"
INBOX_DIR = os.path.join(DIR, "email_inbox")
os.makedirs(INBOX_DIR, exist_ok=True)

def load_env(path):
    e = {}
    for l in open(path):
        l = l.strip()
        if l and not l.startswith("#") and "=" in l:
            k, v = l.split("=", 1); e[k] = v.strip().strip('"')
    return e

ENV = load_env(os.path.join(DIR, "email.env"))
CFG = load_env(os.path.join(DIR, "config.env"))
BOT = CFG.get("TELEGRAM_BOT_TOKEN", "")
ADMIN_CHAT = CFG.get("TELEGRAM_CHAT_ID", "")

# remetentes permitidos -> pessoa
ALLOWED = {
    "rodrigor@rodrigor.com": "Rodrigo",
    "rodrigor@dcx.ufpb.br": "Rodrigo",
    "rodrigor@uana.tech": "Rodrigo",
    "ayla@dcx.ufpb.br": "Ayla",
    "ayladebora@gmail.com": "Ayla",
}

def kid_chat(name):
    try:
        for l in open(os.path.join(DIR, "kids/registry.txt")):
            p = l.split()
            if len(p) >= 2 and p[1].lower() == name.lower():
                return p[0]
    except Exception:
        pass
    return ""

def person_chat(person):
    return ADMIN_CHAT if person == "Rodrigo" else kid_chat(person)

# reminder target: Rodrigo -> admin
def reminder_target(person):
    return "admin" if person == "Rodrigo" else person

def tg(chat, text):
    if not chat:
        return
    subprocess.run(["curl", "-s", "-X", "POST",
        f"https://api.telegram.org/bot{BOT}/sendMessage",
        "--data-urlencode", f"chat_id={chat}",
        "--data-urlencode", f"text={text}",
        "--data-urlencode", "disable_web_page_preview=true"],
        capture_output=True)

def dec(s):
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        out.append(part.decode(enc or "utf-8", "ignore") if isinstance(part, bytes) else part)
    return "".join(out)

def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore")
                except Exception:
                    pass
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return ""

def save_attachments(msg):
    saved = []
    for part in msg.walk():
        disp = str(part.get("Content-Disposition"))
        if "attachment" in disp:
            fn = dec(part.get_filename()) or "anexo"
            fn = re.sub(r"[^A-Za-z0-9._-]", "_", fn)
            payload = part.get_payload(decode=True)
            if payload and len(payload) <= 25 * 1024 * 1024:
                path = os.path.join(INBOX_DIR, f"{int(time.time())}_{fn}")
                open(path, "wb").write(payload)
                saved.append(path)
    return saved

def classify(person, frm, subject, body, attachments):
    att = ", ".join(os.path.basename(a) for a in attachments) or "nenhum"
    prompt = f"""Você classifica a INTENÇÃO de um email para o sistema PIrrai. NÃO execute nada — só classifique e resuma, retornando APENAS um JSON.
Email de: {person} ({frm})
Assunto: {subject}
Anexos: {att}
Corpo:
{body[:4000]}

Retorne SÓ este JSON (sem texto fora dele):
{{"action":"summarize|reminder|save|none","summary":"<resumo curto em pt-BR, sempre preencha>","reminder_when":"<data/hora que o date -d entende, ou ->","reminder_msg":"<texto do lembrete, ou ->"}}
Regras: "reminder" se pedir pra ser lembrado de algo em data/hora; "save" se pedir pra guardar o anexo; "summarize" se pedir resumo ou se nao houver comando claro; "none" so se for spam/vazio."""
    try:
        r = subprocess.run(["sudo", "-H", "-u", "pirraikid", "/usr/local/bin/claude",
                            "-p", "--model", "sonnet", prompt],
                           capture_output=True, text=True, timeout=150)
        out = r.stdout.strip()
        m = re.search(r"\{.*\}", out, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        print("classify erro:", e)
    return {"action": "summarize", "summary": (subject or "(sem assunto)"), "reminder_when": "-", "reminder_msg": "-"}

def add_reminder(person, when, msg):
    try:
        subprocess.run([os.path.join(DIR, "reminder_add.sh"), reminder_target(person), "time", when, msg],
                       capture_output=True, text=True, timeout=20)
        return True
    except Exception:
        return False

def process(msg, person):
    frm = dec(msg.get("From"))
    subject = dec(msg.get("Subject")) or "(sem assunto)"
    body = get_body(msg)
    atts = save_attachments(msg)
    chat = person_chat(person)
    # 1) notifica que chegou
    head = f"📧 Email de {frm}\nAssunto: {subject}"
    if atts:
        head += f"\n📎 {len(atts)} anexo(s) salvo(s) em email_inbox/"
    tg(chat, head)
    # 2) interpreta o comando (Claude isolado) e executa ação SEGURA
    c = classify(person, frm, subject, body, atts)
    action = c.get("action", "summarize")
    summary = c.get("summary", "").strip()
    if action == "reminder" and c.get("reminder_when", "-") not in ("-", ""):
        rmsg = c.get("reminder_msg", "-")
        rmsg = subject if rmsg in ("-", "") else rmsg
        if add_reminder(person, c["reminder_when"], rmsg):
            tg(chat, f"⏰ Lembrete criado a partir do email: \"{rmsg}\" ({c['reminder_when']}).")
        if summary:
            tg(chat, f"📝 Resumo: {summary}")
    elif action == "save":
        tg(chat, f"💾 Pronto: {len(atts)} anexo(s) guardado(s). " + (f"Resumo: {summary}" if summary else ""))
    elif action == "summarize" and summary:
        tg(chat, f"📝 Resumo do email: {summary}")
    # 'none' -> só a notificação inicial

def main():
    try:
        M = imaplib.IMAP4_SSL(ENV["IMAP_HOST"], int(ENV["IMAP_PORT"]))
        M.login(ENV["EMAIL_USER"], ENV["EMAIL_PASS"])
        M.select("INBOX")
    except Exception as e:
        print("IMAP erro:", e); return
    typ, data = M.search(None, "UNSEEN")
    for num in data[0].split():
        typ, d = M.fetch(num, "(BODY.PEEK[])")
        msg = email.message_from_bytes(d[0][1])
        frm_raw = dec(msg.get("From"))
        addr = re.search(r"[\w.+-]+@[\w.-]+", frm_raw)
        addr = addr.group(0).lower() if addr else ""
        person = ALLOWED.get(addr)
        # marca como lido SEMPRE (evita reprocessar), mesmo de remetente não permitido
        M.store(num, "+FLAGS", "\\Seen")
        if not person:
            print("ignorado (remetente não permitido):", addr)
            continue
        try:
            process(msg, person)
        except Exception as e:
            print("process erro:", e)
            tg(person_chat(person), f"⚠️ Recebi um email de {addr} mas tive um erro ao processar.")
    M.logout()

if __name__ == "__main__":
    main()
