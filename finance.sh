#!/bin/bash
# finance.sh — núcleo do módulo de finanças do PIrrai (SQLite).
# Valores monetários SEMPRE em CENTAVOS (INTEGER). Nunca float.
# Comandos: init | accounts | add | list | categorize | autocat | summary
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DB="${FINANCE_DB:-$DIR/finance.db}"
sq(){ sqlite3 "$DB" "$@"; }

# reais -> centavos (aceita "45", "45,90", "45.90", "R$ 45,90", "-12,5")
to_cents(){
  local v="${1//R\$/}"; v="${v// /}"; v="${v//./}"; v="${v//,/.}"
  awk -v x="$v" 'BEGIN{ if(x=="" ){print "ERR"; exit} printf "%d\n", (x*100 + (x<0?-0.5:0.5)) }'
}
cents_fmt(){ awk -v c="$1" 'BEGIN{ printf "R$ %.2f", c/100 }' | sed 's/\./,/'; }

init_db(){
  sq <<'SQL'
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, type TEXT DEFAULT 'credito',
  bank TEXT, color TEXT DEFAULT '#888', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, parent TEXT,
  icon TEXT, color TEXT, rule_keywords TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL, time TEXT,
  amount INTEGER NOT NULL,                 -- centavos; negativo = despesa, positivo = receita
  description TEXT, merchant TEXT,
  category TEXT, subcategory TEXT,
  account_id INTEGER REFERENCES accounts(id),
  source TEXT DEFAULT 'manual',            -- manual|telegram|email|ofx
  status TEXT DEFAULT 'confirmado',        -- pendente|confirmado|conciliado|importado|agendado
  notes TEXT,
  installment_id INTEGER,
  external_id TEXT,                         -- FITID do OFX
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_external ON transactions(external_id) WHERE external_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE TABLE IF NOT EXISTS budgets(
  id INTEGER PRIMARY KEY, category TEXT, month TEXT, limit_amount INTEGER,
  UNIQUE(category,month));
CREATE TABLE IF NOT EXISTS installments(
  id INTEGER PRIMARY KEY, total INTEGER, amount INTEGER, n_total INTEGER, n_current INTEGER,
  start_date TEXT, description TEXT, account_id INTEGER);
CREATE TABLE IF NOT EXISTS ofx_imports(
  id INTEGER PRIMARY KEY, filename TEXT, imported_at TEXT DEFAULT (datetime('now','localtime')),
  matched INTEGER DEFAULT 0, unmatched INTEGER DEFAULT 0);
SQL
}

seed_categories(){
  # name|parent|icon|color|keywords(csv)
  while IFS='|' read -r name parent icon color kws; do
    [ -z "$name" ] && continue
    local jkw; jkw=$(printf '%s' "$kws" | jq -Rc 'split(",")|map(select(length>0))')
    sq "INSERT OR IGNORE INTO categories(name,parent,icon,color,rule_keywords)
        VALUES('$name','$parent','$icon','$color','$(printf '%s' "$jkw" | sed "s/'/''/g")');"
  done <<'CATS'
Mercado||🛒|#2e7d32|mercado,supermercado,atacad,carrefour,pao de acucar,assai,big,extra,hortifruti
Alimentação||🍔|#ef6c00|ifood,rappi,uber eats,restaurante,padaria,lanche,delivery,bar,cafe
Transporte||🚗|#1565c0|uber,99app,99 tecnologia,taxi,posto,gasolina,combustivel,estacionamento,pedagio,metro
Compras||🛍️|#6a1b9a|amazon,mercadolivre,mercado livre,magazine,americanas,shopee,aliexpress,shein
Assinaturas||📺|#c62828|netflix,spotify,youtube,prime,hbo,max,disney,apple.com,google,icloud,chatgpt,openai,claude
Saúde||💊|#00838f|farmacia,drogaria,droga,hospital,clinica,laboratorio,unimed,medico,dentista
Casa||🏠|#5d4037|aluguel,condominio,luz,energia,enel,agua,gas,internet,vivo,claro,tim,net
Educação||📚|#283593|escola,curso,faculdade,livro,udemy,alura
Lazer||🎬|#ad1457|cinema,ingresso,viagem,hotel,airbnb,booking,show
Serviços||🔧|#455a64|barbearia,salao,lavanderia,assinatura,mensalidade
Receitas||💰|#1b5e20|salario,pagamento,deposito,pix recebido,rendimento,transferencia recebida
Outros||📌|#757575|
CATS
}

# escapa string p/ SQL
esc(){ printf '%s' "$1" | sed "s/'/''/g"; }

# autocat_match "texto" -> categoria cujo rule_keywords casa (substring, case-insensitive); vazio se nenhuma
deburr(){ printf '%s' "$1" | iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null | tr '[:upper:]' '[:lower:]'; }
autocat_match(){
  local txt; txt=$(deburr "$1")
  [ -z "$txt" ] && return
  sq -separator $'\t' "SELECT name,rule_keywords FROM categories WHERE rule_keywords<>'[]';" | \
  while IFS=$'\t' read -r name kws; do
    while IFS= read -r kw; do
      kw=$(deburr "$kw")
      [ -n "$kw" ] && case "$txt" in *"$kw"*) echo "$name"; return;; esac
    done < <(printf '%s' "$kws" | jq -r '.[]')
  done | head -1
}

cmd="${1:-help}"; shift 2>/dev/null || true
case "$cmd" in
  init)
    init_db; seed_categories
    echo "OK — finance.db pronto ($(sq 'SELECT COUNT(*) FROM categories;') categorias). Caminho: $DB"
    ;;

  accounts)
    sub="${1:-list}"; shift 2>/dev/null || true
    case "$sub" in
      add)  # accounts add "Nome" [tipo] [banco] [cor]
        name="${1:?uso: accounts add \"Nome\" [tipo] [banco] [cor]}"; type="${2:-credito}"; bank="${3:-}"; color="${4:-#888}"
        sq "INSERT OR IGNORE INTO accounts(name,type,bank,color) VALUES('$(esc "$name")','$(esc "$type")','$(esc "$bank")','$(esc "$color")');"
        echo "OK — conta: $name ($type${bank:+/$bank})"
        ;;
      list|*)
        echo "id|nome|tipo|banco|cor"
        sq -separator '|' "SELECT id,name,type,COALESCE(bank,''),color FROM accounts ORDER BY id;"
        ;;
    esac
    ;;

  add)  # add <valor> "descrição" [categoria] [conta_id] [data] [--receita]
    val="${1:?uso: add <valor> \"descrição\" [categoria] [conta] [data]}"; desc="${2:-}"; cat="${3:-}"; acc="${4:-}"; dt="${5:-}"
    receita=0; for a in "$@"; do [ "$a" = "--receita" ] && receita=1; done
    cents=$(to_cents "$val"); [ "$cents" = "ERR" ] && { echo "valor inválido: $val"; exit 1; }
    # despesa por padrão (negativo); receita fica positiva
    if [ "$receita" = "1" ]; then cents=${cents#-}; else [ "${cents:0:1}" != "-" ] && cents="-$cents"; fi
    [ -z "$dt" ] && dt=$(date +%F)
    # auto-categoriza se não veio categoria
    if [ -z "$cat" ]; then cat=$(autocat_match "$desc"); fi
    accsql="NULL"; [ -n "$acc" ] && accsql="$acc"
    id=$(sq "INSERT INTO transactions(date,amount,description,category,account_id,source,status)
        VALUES('$(esc "$dt")',$cents,'$(esc "$desc")',$([ -n "$cat" ] && echo "'$(esc "$cat")'" || echo NULL),$accsql,'${SOURCE:-manual}','confirmado');
        SELECT last_insert_rowid();")
    echo "OK #$id — $(cents_fmt "$cents") · ${desc:-(sem descrição)}${cat:+ · $cat} · $dt"
    ;;

  list)  # list [YYYY-MM]   (default: mês atual)
    mon="${1:-$(date +%Y-%m)}"
    echo "id|data|valor|descrição|categoria|conta|status"
    sq -separator '|' "SELECT t.id,t.date, printf('R\$ %.2f',t.amount/100.0), COALESCE(t.description,''),
        COALESCE(t.category,'—'), COALESCE(a.name,'—'), t.status
        FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        WHERE substr(t.date,1,7)='$mon' ORDER BY t.date DESC, t.id DESC;"
    ;;

  categorize)  # categorize <id> <categoria>
    id="${1:?uso: categorize <id> <categoria>}"; cat="${2:?categoria}"
    sq "UPDATE transactions SET category='$(esc "$cat")' WHERE id=$id;"
    echo "OK — #$id → $cat"
    ;;

  autocat)  # autocat "texto"  -> imprime categoria sugerida (vazio se nenhuma)
    autocat_match "${1:-}"
    ;;

  summary)  # summary [YYYY-MM]
    mon="${1:-$(date +%Y-%m)}"
    echo "Mês $mon"
    echo "Despesas: $(cents_fmt "$(sq "SELECT COALESCE(-SUM(amount),0) FROM transactions WHERE amount<0 AND substr(date,1,7)='$mon';")")"
    echo "Receitas: $(cents_fmt "$(sq "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE amount>0 AND substr(date,1,7)='$mon';")")"
    echo "Por categoria (despesas):"
    sq -separator '|' "SELECT COALESCE(category,'—'), printf('R\$ %.2f',-SUM(amount)/100.0)
        FROM transactions WHERE amount<0 AND substr(date,1,7)='$mon'
        GROUP BY category ORDER BY SUM(amount) ASC;"
    ;;

  *) echo "uso: finance.sh {init|accounts|add|list|categorize|autocat|summary}";;
esac
