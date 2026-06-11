#!/bin/bash
# finance_backup.sh — backup do finance.db (não-reconstruível).
# Snapshot consistente (sqlite .backup) -> gzip -> AES-256 -> rotação (30 diários + 12 mensais) -> e-mail off-Pi.
# A senha de backup fica em backups/finance/.passphrase E é enviada 1x ao Telegram (guarde no gerenciador!).
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DB="${FINANCE_DB:-$DIR/finance.db}"
BK="$DIR/backups/finance"; DAILY="$BK/daily"; MONTHLY="$BK/monthly"
PASSFILE="$BK/.passphrase"
mkdir -p "$DAILY" "$MONTHLY"
[ -f "$DIR/email.env" ] && source "$DIR/email.env"
BACKUP_TO="${BACKUP_TO:-rodrigor@rodrigor.com}"

ensure_pass(){
  [ -f "$PASSFILE" ] && return
  openssl rand -base64 24 > "$PASSFILE"; chmod 600 "$PASSFILE"
  local p; p=$(cat "$PASSFILE")
  echo "!!! SENHA DE BACKUP GERADA — guarde no gerenciador de senhas: $p"
  [ -x "$DIR/tg_notify.sh" ] && "$DIR/tg_notify.sh" "🔐 <b>Senha de backup das finanças</b> (guarde no gerenciador — é o que descriptografa os backups enviados por e-mail):
<code>$p</code>"
}

send_mail(){
  local file="$1"
  [ -z "${EMAIL_USER:-}" ] && { echo "   (sem email.env — pulei envio off-Pi)"; return; }
  EMAIL_USER="$EMAIL_USER" EMAIL_PASS="$EMAIL_PASS" SMTP_HOST="$SMTP_HOST" SMTP_PORT="$SMTP_PORT" BACKUP_TO="$BACKUP_TO" \
  python3 - "$file" <<'PY'
import sys,os,smtplib,ssl
from email.message import EmailMessage
f=sys.argv[1]
m=EmailMessage()
m['From']=os.environ['EMAIL_USER']; m['To']=os.environ['BACKUP_TO']
m['Subject']='[PIrrai] Backup finance.db '+os.path.basename(f)
m.set_content('Backup criptografado (AES-256) em anexo. Restaure com finance_backup.sh restore e a senha de backup.')
with open(f,'rb') as fh:
    m.add_attachment(fh.read(),maintype='application',subtype='octet-stream',filename=os.path.basename(f))
with smtplib.SMTP_SSL(os.environ['SMTP_HOST'],int(os.environ['SMTP_PORT']),context=ssl.create_default_context()) as s:
    s.login(os.environ['EMAIL_USER'],os.environ['EMAIL_PASS']); s.send_message(m)
print('   e-mail off-Pi enviado para',os.environ['BACKUP_TO'])
PY
}

case "${1:-run}" in
  run)
    [ -f "$DB" ] || { echo "sem finance.db ainda — nada a fazer"; exit 0; }
    ensure_pass; pass=$(cat "$PASSFILE")
    day=$(date +%Y%m%d); snap="/tmp/finance_$day.$$.db"
    sqlite3 "$DB" ".backup '$snap'"
    out="$DAILY/finance-$day.db.gz.enc"
    gzip -c "$snap" | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "pass:$pass" -out "$out"
    rm -f "$snap"
    [ "$(date +%d)" = "01" ] && cp "$out" "$MONTHLY/finance-$(date +%Y%m).db.gz.enc"
    ls -1t "$DAILY"/*.enc 2>/dev/null | tail -n +31 | xargs -r rm -f      # mantém 30 diários
    ls -1t "$MONTHLY"/*.enc 2>/dev/null | tail -n +13 | xargs -r rm -f    # mantém 12 mensais
    send_mail "$out"
    echo "OK — backup: $out ($(du -h "$out"|cut -f1))"
    ;;
  restore)  # restore <arquivo.enc> [destino]
    f="${2:?uso: restore <arquivo.enc> [destino.db]}"; dest="${3:-$DIR/finance.restored.db}"
    [ -f "$PASSFILE" ] || { echo "sem .passphrase — informe a senha em FINANCE_BK_PASS"; }
    pass="${FINANCE_BK_PASS:-$(cat "$PASSFILE" 2>/dev/null)}"
    openssl enc -d -aes-256-cbc -pbkdf2 -pass "pass:$pass" -in "$f" | gunzip > "$dest"
    echo "OK — restaurado em $dest ($(sqlite3 "$dest" 'SELECT COUNT(*) FROM transactions;') transações, $(sqlite3 "$dest" 'SELECT COUNT(*) FROM accounts;') contas)"
    ;;
  *) echo "uso: finance_backup.sh {run|restore <arquivo.enc> [destino]}";;
esac
