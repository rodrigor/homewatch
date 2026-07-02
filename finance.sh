#!/bin/bash
# finance.sh — núcleo do módulo de finanças do PIrrai (SQLite).
# Valores monetários SEMPRE em CENTAVOS (INTEGER). Nunca float.
# Comandos: init | accounts | add | list | categorize | autocat | summary
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
DB="${FINANCE_DB:-$DIR/finance.db}"
sq(){ sqlite3 "$DB" "$@"; }

# reais -> centavos (aceita "45", "45,90", "45.90", "1.234,56", "R$ 45,90", "-12,5")
to_cents(){
  local v="${1//R\$/}"; v="${v// /}"
  # só dígitos, sinal no início e separadores . ,  — senão ERR (nunca 0 silencioso)
  [[ "$v" =~ ^[+-]?[0-9.,]+$ && "$v" =~ [0-9] ]] || { echo "ERR"; return; }
  if [[ "$v" =~ ^([+-]?[0-9.,]*)\.([0-9]{1,2})$ ]]; then
    # último separador é '.' com 1-2 casas: decimal estilo US ("45.90" = R$ 45,90)
    local int="${BASH_REMATCH[1]//[.,]/}"
    v="${int}.${BASH_REMATCH[2]}"
  else
    # pt-BR: '.' é milhar, ',' é decimal
    v="${v//./}"; v="${v//,/.}"
  fi
  awk -v x="$v" 'BEGIN{ if(x==""){print "ERR"; exit} printf "%d\n", (x*100 + (x<0?-0.5:0.5)) }'
}
cents_fmt(){ awk -v c="$1" 'BEGIN{ printf "R$ %.2f", c/100 }' | sed 's/\./,/'; }
# validação de argumentos interpolados em SQL (ids numéricos e mês YYYY-MM)
req_int(){ [[ "${1:-}" =~ ^[0-9]+$ ]] || { echo "número inválido: ${1:-}"; exit 1; }; }
req_month(){ [[ "${1:-}" =~ ^[0-9]{4}-[0-9]{2}$ ]] || { echo "mês inválido: ${1:-} (use YYYY-MM)"; exit 1; }; }

init_db(){
  sq <<'SQL'
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, type TEXT DEFAULT 'credito',
  bank TEXT, numero TEXT, color TEXT DEFAULT '#888', created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, parent TEXT,
  icon TEXT, color TEXT, grupo TEXT, is_transfer INTEGER DEFAULT 0, rule_keywords TEXT DEFAULT '[]');
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL, time TEXT,
  amount INTEGER NOT NULL,                 -- centavos; negativo = despesa, positivo = receita
  description TEXT, merchant TEXT, favorecido TEXT,
  category TEXT, subcategory TEXT,
  account_id INTEGER REFERENCES accounts(id),
  source TEXT DEFAULT 'manual',            -- manual|telegram|email|ofx
  status TEXT DEFAULT 'confirmado',        -- pendente|confirmado|conciliado|importado|agendado
  notes TEXT,
  installment_id INTEGER,
  external_id TEXT,                         -- FITID do OFX
  excepcional INTEGER DEFAULT 0,            -- despesa fora do normal (one-off); separada do recorrente
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
CREATE TABLE IF NOT EXISTS budget_alerts(
  category TEXT, month TEXT, level INTEGER, sent_at TEXT DEFAULT (datetime('now','localtime')),
  UNIQUE(category,month,level));
CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY, field TEXT DEFAULT 'favorecido', pattern TEXT NOT NULL,
  category TEXT NOT NULL, amt_min INTEGER, amt_max INTEGER, dom INTEGER,
  created_at TEXT DEFAULT (datetime('now','localtime')));
CREATE TABLE IF NOT EXISTS classify_asked(tx_id INTEGER UNIQUE);
CREATE TABLE IF NOT EXISTS favorecidos(
  id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE, tipo TEXT, documento TEXT,
  categoria_padrao TEXT, nivel_padrao INTEGER, notas TEXT, aliases TEXT DEFAULT '[]',
  recorrente INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now','localtime')));
SQL
}

migrate_cols(){  # adiciona colunas novas em bancos já existentes
  sq "PRAGMA table_info(categories);"   | grep -q '|grupo|'      || sq "ALTER TABLE categories ADD COLUMN grupo TEXT;"
  sq "PRAGMA table_info(accounts);"     | grep -q '|numero|'     || sq "ALTER TABLE accounts ADD COLUMN numero TEXT;"
  sq "PRAGMA table_info(transactions);" | grep -q '|favorecido|' || sq "ALTER TABLE transactions ADD COLUMN favorecido TEXT;"
  sq "PRAGMA table_info(categories);"   | grep -q '|is_transfer|' || sq "ALTER TABLE categories ADD COLUMN is_transfer INTEGER DEFAULT 0;"
  sq "PRAGMA table_info(transactions);" | grep -q '|excepcional|' || sq "ALTER TABLE transactions ADD COLUMN excepcional INTEGER DEFAULT 0;"
  sq "PRAGMA table_info(rules);"         | grep -q '|amt_min|'    || sq "ALTER TABLE rules ADD COLUMN amt_min INTEGER;"
  sq "PRAGMA table_info(rules);"         | grep -q '|amt_max|'    || sq "ALTER TABLE rules ADD COLUMN amt_max INTEGER;"
  sq "PRAGMA table_info(rules);"         | grep -q '|dom|'        || sq "ALTER TABLE rules ADD COLUMN dom INTEGER;"
  sq "PRAGMA table_info(favorecidos);"   | grep -q '|recorrente|' || sq "ALTER TABLE favorecidos ADD COLUMN recorrente INTEGER DEFAULT 0;"
  sq "PRAGMA table_info(categories);"   | grep -q '|nivel|'           || sq "ALTER TABLE categories ADD COLUMN nivel INTEGER DEFAULT 0;"
  sq "PRAGMA table_info(transactions);" | grep -q '|transfer_pair_id|'|| sq "ALTER TABLE transactions ADD COLUMN transfer_pair_id INTEGER;"
  sq "PRAGMA table_info(transactions);" | grep -q '|tx_type|'         || sq "ALTER TABLE transactions ADD COLUMN tx_type TEXT DEFAULT 'normal';"
  sq "PRAGMA table_info(transactions);" | grep -q '|amount_original|' || sq "ALTER TABLE transactions ADD COLUMN amount_original INTEGER;"
  sq "PRAGMA table_info(transactions);" | grep -q '|fx_rate|'         || sq "ALTER TABLE transactions ADD COLUMN fx_rate REAL;"
  sq "PRAGMA table_info(transactions);" | grep -q '|currency|'        || sq "ALTER TABLE transactions ADD COLUMN currency TEXT DEFAULT 'BRL';"
  sq "PRAGMA table_info(accounts);"     | grep -q '|opening_balance|' || sq "ALTER TABLE accounts ADD COLUMN opening_balance INTEGER DEFAULT 0;"
  sq "PRAGMA table_info(accounts);"     | grep -q '|currency|'        || sq "ALTER TABLE accounts ADD COLUMN currency TEXT DEFAULT 'BRL';"
  sq "CREATE TABLE IF NOT EXISTS config(key TEXT PRIMARY KEY, value TEXT);"
  sq "CREATE TABLE IF NOT EXISTS account_valuations(
    id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, date TEXT NOT NULL,
    value INTEGER NOT NULL, currency TEXT DEFAULT 'BRL', notes TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')));"
  sq "INSERT OR IGNORE INTO categories(name,icon,color,grupo,nivel,rule_keywords)
      VALUES('Rendimento','📈','#1b5e20','Receitas',0,'[]');"
}
# cláusula SQL: exclui categorias marcadas como movimentação (não-gasto/não-receita)
NOTRANSFER="COALESCE(category,'') NOT IN (SELECT name FROM categories WHERE is_transfer=1)"

seed_categories(){
  # name|parent|icon|color|grupo|keywords(csv)  — grupo só é aplicado se a categoria ainda não tiver um (preserva customização)
  while IFS='|' read -r name parent icon color grupo kws; do
    [ -z "$name" ] && continue
    local jkw; jkw=$(printf '%s' "$kws" | jq -Rc 'split(",")|map(select(length>0))')
    sq "INSERT INTO categories(name,parent,icon,color,grupo,rule_keywords)
        VALUES('$name','$parent','$icon','$color','$(esc "$grupo")','$(printf '%s' "$jkw" | sed "s/'/''/g")')
        ON CONFLICT(name) DO UPDATE SET grupo=COALESCE(categories.grupo, excluded.grupo);"
  done <<'CATS'
Mercado||🛒|#2e7d32|Casa|mercado,supermercado,atacad,carrefour,pao de acucar,assai,big,extra,hortifruti
Alimentação||🍔|#ef6c00|Alimentação|ifood,rappi,uber eats,restaurante,padaria,lanche,delivery,bar,cafe
Transporte||🚗|#1565c0|Transporte|uber,99app,99 tecnologia,taxi,posto,gasolina,combustivel,estacionamento,pedagio,metro
Compras||🛍️|#6a1b9a|Pessoal|amazon,mercadolivre,mercado livre,magazine,americanas,shopee,aliexpress,shein
Assinaturas||📺|#c62828|Pessoal|netflix,spotify,youtube,prime,hbo,max,disney,apple.com,google,icloud,chatgpt,openai,claude
Saúde||💊|#00838f|Saúde|farmacia,drogaria,droga,hospital,clinica,laboratorio,unimed,medico,dentista
Casa||🏠|#5d4037|Casa|aluguel,condominio,luz,energia,enel,agua,gas,internet,vivo,claro,tim,net
Educação||📚|#283593|Pessoal|escola,curso,faculdade,livro,udemy,alura
Lazer||🎬|#ad1457|Lazer|cinema,ingresso,viagem,hotel,airbnb,booking,show
Serviços||🔧|#455a64|Casa|barbearia,salao,lavanderia,assinatura,mensalidade
Receitas||💰|#1b5e20|Receitas|salario,pagamento,deposito,pix recebido,rendimento,transferencia recebida
Outros||📌|#757575|Outros|
CATS
}

# escapa string p/ SQL
esc(){ printf '%s' "$1" | sed "s/'/''/g"; }

# autocat_match "texto" -> categoria (regras + palavras-chave) via motor Python; vazio se nenhuma
autocat_match(){ python3 "$DIR/finance_rules.py" classify "" "${1:-}" "" 2>/dev/null; }

cmd="${1:-help}"; shift 2>/dev/null || true
case "$cmd" in
  init)
    init_db; migrate_cols; seed_categories
    echo "OK — finance.db pronto ($(sq 'SELECT COUNT(*) FROM categories;') categorias). Caminho: $DB"
    ;;

  group)  # group "<categoria>" "<grupo>"
    cat="${1:?uso: group \"categoria\" \"grupo\"}"; grp="${2:?grupo}"
    sq "UPDATE categories SET grupo='$(esc "$grp")' WHERE name='$(esc "$cat")';"
    echo "OK — $cat → grupo $grp"
    ;;

  limit)  # limit "<categoria>" <reais|->   (limite mensal recorrente; '-' remove)
    cat="${1:?uso: limit \"categoria\" <valor|->}"; val="${2:?valor ou -}"
    if [ "$val" = "-" ]; then
      sq "DELETE FROM budgets WHERE category='$(esc "$cat")' AND month='*';
          DELETE FROM budget_alerts WHERE category='$(esc "$cat")';"
      echo "OK — limite removido de $cat"
    else
      cents=$(to_cents "$val"); [ "$cents" = "ERR" ] && { echo "valor inválido"; exit 1; }; cents=${cents#-}
      sq "INSERT INTO budgets(category,month,limit_amount) VALUES('$(esc "$cat")','*',$cents)
          ON CONFLICT(category,month) DO UPDATE SET limit_amount=excluded.limit_amount;
          DELETE FROM budget_alerts WHERE category='$(esc "$cat")' AND month='$(date +%Y-%m)';"
      echo "OK — limite de $cat: $(cents_fmt "$cents")/mês"
    fi
    ;;

  limits)  # limits [YYYY-MM] : categoria|limite|gasto|pct
    mon="${1:-$(date +%Y-%m)}"; req_month "$mon"
    sq -separator '|' "SELECT b.category, b.limit_amount,
        COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=b.category AND amount<0 AND substr(date,1,7)='$mon'),0) AS spent,
        CASE WHEN b.limit_amount>0 THEN CAST(COALESCE((SELECT -SUM(amount) FROM transactions WHERE category=b.category AND amount<0 AND substr(date,1,7)='$mon'),0)*100/b.limit_amount AS INT) ELSE 0 END AS pct
        FROM budgets b WHERE b.month='*' ORDER BY pct DESC;"
    ;;

  classify-all)  # preenche categoria das transações sem categoria (regras + palavras-chave)
    echo "classificadas: $(python3 "$DIR/finance_rules.py" classifyall)"
    ;;

  pending)  # lista transações sem categoria (id|data|valor|favorecido|descrição)
    lim="${1:-40}"; req_int "$lim"
    sq -separator '|' "SELECT id,date,printf('%.2f',amount/100.0),COALESCE(favorecido,''),COALESCE(description,'')
        FROM transactions WHERE category IS NULL OR category='' ORDER BY date DESC LIMIT $lim;"
    ;;

  transfer)  # transfer "<categoria>" <on|off>  — marca categoria como movimentação (não conta como gasto/receita)
    cat="${1:?uso: transfer categoria on|off}"; st="${2:-on}"
    v=1; [ "$st" = "off" ] && v=0
    sq "INSERT OR IGNORE INTO categories(name,icon) VALUES('$(esc "$cat")','🔁');
        UPDATE categories SET is_transfer=$v WHERE name='$(esc "$cat")';"
    echo "OK — $cat: movimentação=$v"
    ;;

  excepcional)  # excepcional <id> <on|off>  — marca lançamento como despesa fora do normal
    id="${1:?uso: excepcional <id> on|off}"; req_int "$id"; st="${2:-on}"; v=1; [ "$st" = "off" ] && v=0
    sq "UPDATE transactions SET excepcional=$v WHERE id=$id;"
    echo "OK — #$id excepcional=$v"
    ;;

  recurrence)  # recurrence <id|--cat categoria [--fav favorecido]> <mensal|anual|trimestral|semanal|unico|->
    # Uso 1: recurrence <id> <frequência>         → marca UM lançamento
    # Uso 2: recurrence --cat <cat> [--fav <fav>] <frequência> → marca todos do padrão
    # frequência "-" remove o valor
    if [ "${1:-}" = "--cat" ]; then
      shift
      cat_filter="${1:?categoria}"; shift
      fav_filter=""; freq=""
      while [[ $# -gt 0 ]]; do
        case "$1" in
          --fav) fav_filter="$2"; shift 2 ;;
          *) freq="$1"; shift ;;
        esac
      done
      freq="${freq:?frequência}"
      val="NULL"; [ "$freq" != "-" ] && val="'$(esc "$freq")'"
      where="category='$(esc "$cat_filter")'"
      [ -n "$fav_filter" ] && where+=" AND favorecido LIKE '%$(esc "$fav_filter")%'"
      cnt=$(sq "SELECT COUNT(*) FROM transactions WHERE $where;")
      sq "UPDATE transactions SET recurrence=$val WHERE $where;"
      echo "OK — $cnt lançamentos ($cat_filter${fav_filter:+ / $fav_filter}) → recurrence=${freq}"
    else
      id="${1:?uso: recurrence <id> <mensal|anual|trimestral|semanal|unico|->}"; req_int "$id"; freq="${2:?frequência}"
      val="NULL"; [ "$freq" != "-" ] && val="'$(esc "$freq")'"
      sq "UPDATE transactions SET recurrence=$val WHERE id=$id;"
      echo "OK — #$id → recurrence=${freq}"
    fi
    ;;

  setcat)  # setcat <id> "<categoria>"  — define categoria de UM lançamento
    id="${1:?uso: setcat <id> categoria}"; req_int "$id"; cat="${2:?categoria}"
    sq "INSERT OR IGNORE INTO categories(name,icon) VALUES('$(esc "$cat")','🏷️');
        UPDATE transactions SET category='$(esc "$cat")' WHERE id=$id;"
    echo "OK — #$id → $cat"
    ;;

  rule)  # rule add <campo> "<padrão>" "<categoria>"  — cria regra e aplica a tudo
    sub="${1:-}"; shift 2>/dev/null || true
    case "$sub" in
      add) field="${1:?campo (favorecido|description|merchant|qualquer)}"; pat="${2:?padrão}"; cat="${3:?categoria}"
        sq "INSERT OR IGNORE INTO categories(name,icon) VALUES('$(esc "$cat")','🏷️');
            INSERT INTO rules(field,pattern,category) VALUES('$(esc "$field")','$(esc "$pat")','$(esc "$cat")');"
        python3 "$DIR/finance_rules.py" apply >/dev/null
        echo "OK — regra: $field contém \"$pat\" → $cat (aplicada)"
        ;;
      list|*) sq -separator '|' "SELECT id,field,pattern,category FROM rules ORDER BY id;";;
    esac
    ;;

  ask-pending)  # pergunta ao admin no Telegram sobre lançamentos sem categoria ainda não perguntados
    rows=$(sq -separator '~' "SELECT id, printf('%.2f',amount/100.0), COALESCE(NULLIF(favorecido,''),description,'(sem descrição)')
        FROM transactions WHERE (category IS NULL OR category='') AND id NOT IN (SELECT tx_id FROM classify_asked)
        ORDER BY date DESC LIMIT 25;")
    [ -z "$rows" ] && { echo "nada a perguntar"; exit 0; }
    msg="🤔 <b>Preciso classificar estes lançamentos do extrato</b> (não reconheci):"
    ids=""
    while IFS='~' read -r id val who; do
      [ -z "$id" ] && continue
      msg="$msg
<code>#$id</code>  $val  ·  $who"
      ids="$ids $id"
    done <<EOF
$rows
EOF
    first=$(echo $ids | awk '{print $1}')
    msg="$msg

Me diga a categoria de cada um (ex.: <i>#$first é mercado</i>, ou <i>todos do Herbert são aluguel</i>). Se for um favorecido fixo eu já crio uma regra."
    "$DIR/tg_notify.sh" "$msg"
    for id in $ids; do sq "INSERT OR IGNORE INTO classify_asked(tx_id) VALUES($id);"; done
    echo "perguntei sobre:$ids"
    ;;

  groups)  # groups [YYYY-MM] : despesas agrupadas
    mon="${1:-$(date +%Y-%m)}"; req_month "$mon"
    echo "Despesas por grupo ($mon):"
    sq -separator '|' "SELECT COALESCE(c.grupo,'(sem grupo)'), printf('R\$ %.2f',-SUM(t.amount)/100.0)
        FROM transactions t LEFT JOIN categories c ON c.name=t.category
        WHERE t.amount<0 AND substr(t.date,1,7)='$mon' AND COALESCE(c.is_transfer,0)=0
        GROUP BY c.grupo ORDER BY SUM(t.amount) ASC;"
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
    mon="${1:-$(date +%Y-%m)}"; req_month "$mon"
    echo "id|data|valor|descrição|categoria|conta|status"
    sq -separator '|' "SELECT t.id,t.date, printf('R\$ %.2f',t.amount/100.0), COALESCE(t.description,''),
        COALESCE(t.category,'—'), COALESCE(a.name,'—'), t.status
        FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        WHERE substr(t.date,1,7)='$mon' ORDER BY t.date DESC, t.id DESC;"
    ;;

  categorize)  # categorize <id> <categoria>
    id="${1:?uso: categorize <id> <categoria>}"; req_int "$id"; cat="${2:?categoria}"
    sq "UPDATE transactions SET category='$(esc "$cat")' WHERE id=$id;"
    echo "OK — #$id → $cat"
    ;;

  autocat)  # autocat "texto"  -> imprime categoria sugerida (vazio se nenhuma)
    autocat_match "${1:-}"
    ;;

  summary)  # summary [YYYY-MM]
    mon="${1:-$(date +%Y-%m)}"; req_month "$mon"
    echo "Mês $mon (movimentações excluídas)"
    echo "Despesas: $(cents_fmt "$(sq "SELECT COALESCE(-SUM(amount),0) FROM transactions WHERE amount<0 AND substr(date,1,7)='$mon' AND $NOTRANSFER;")")"
    echo "Receitas: $(cents_fmt "$(sq "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE amount>0 AND substr(date,1,7)='$mon' AND $NOTRANSFER;")")"
    echo "Por categoria (despesas):"
    sq -separator '|' "SELECT COALESCE(category,'—'), printf('R\$ %.2f',-SUM(amount)/100.0)
        FROM transactions WHERE amount<0 AND substr(date,1,7)='$mon' AND $NOTRANSFER
        GROUP BY category ORDER BY SUM(amount) ASC;"
    ;;

  nivel)  # nivel "<categoria>" <1|2|3|0>  — define o nível da categoria (0=movimentação/neutro)
    cat="${1:?uso: nivel \"categoria\" <0|1|2|3>}"; n="${2:?nivel 0-3}"
    [[ "$n" =~ ^[0-3]$ ]] || { echo "nível inválido: $n (use 0-3)"; exit 1; }
    labels=("neutro/movimentação" "Comprometido" "Necessário variável" "Discricionário")
    sq "INSERT OR IGNORE INTO categories(name,icon) VALUES('$(esc "$cat")','🏷️');
        UPDATE categories SET nivel=$n WHERE name='$(esc "$cat")';"
    echo "OK — $cat → nível $n (${labels[$n]:-?})"
    ;;

  config)  # config [key] [valor]  — lê/escreve configurações globais (ex: salario_base em reais)
    key="${1:-}"; val="${2:-}"
    if [ -z "$key" ]; then
      sq -separator '|' "SELECT key,value FROM config ORDER BY key;"
    elif [ -z "$val" ]; then
      sq "SELECT value FROM config WHERE key='$(esc "$key")';"
    else
      sq "INSERT OR REPLACE INTO config(key,value) VALUES('$(esc "$key")','$(esc "$val")');"
      echo "OK — $key = $val"
    fi
    ;;

  transfer-add)  # transfer-add <de> <para> <valor_de> [valor_para] [data] [desc]
    # Cria par de lançamentos vinculados. Para moedas diferentes, informe valor_para.
    de_raw="${1:?uso: transfer-add <de> <para> <valor_de> [valor_para] [data] [desc]}"; para_raw="${2:?para}"; val_de="${3:?valor}"
    val_para="${4:-}"; dt="${5:-$(date +%F)}"; desc="${6:-Transferência}"
    # resolve contas por id ou nome (parcial)
    de_id=$(sq   "SELECT id FROM accounts WHERE CAST(id AS TEXT)='$(esc "$de_raw")'   OR lower(name) LIKE lower('%$(esc "$de_raw")%')   LIMIT 1;")
    para_id=$(sq "SELECT id FROM accounts WHERE CAST(id AS TEXT)='$(esc "$para_raw")' OR lower(name) LIKE lower('%$(esc "$para_raw")%') LIMIT 1;")
    [ -z "$de_id"   ] && { echo "Conta não encontrada: $de_raw";   exit 1; }
    [ -z "$para_id" ] && { echo "Conta não encontrada: $para_raw"; exit 1; }
    de_cur=$(sq   "SELECT COALESCE(currency,'BRL') FROM accounts WHERE id=$de_id;")
    para_cur=$(sq "SELECT COALESCE(currency,'BRL') FROM accounts WHERE id=$para_id;")
    de_name=$(sq   "SELECT name FROM accounts WHERE id=$de_id;")
    para_name=$(sq "SELECT name FROM accounts WHERE id=$para_id;")
    cents_de=$(to_cents "$val_de"); [ "$cents_de" = "ERR" ] && { echo "valor inválido"; exit 1; }; cents_de=${cents_de#-}
    if [ "$de_cur" = "$para_cur" ]; then
      cents_para=$cents_de; fx_de=1; fx_para=1; orig_de=$cents_de; orig_para=$cents_de
    else
      [ -z "$val_para" ] && { echo "Contas em moedas diferentes ($de_cur→$para_cur). Informe também o valor na conta destino."; exit 1; }
      cents_para=$(to_cents "$val_para"); [ "$cents_para" = "ERR" ] && { echo "valor_para inválido"; exit 1; }; cents_para=${cents_para#-}
      # fx_rate = unidades_de / unidades_para (e.g. BRL/USD)
      fx_rate=$(awk "BEGIN{printf \"%.6f\", $cents_de/$cents_para}")
      orig_de=$cents_de; orig_para=$cents_para
      # amount (BRL-equiv): se de=BRL usamos cents_de; se para=BRL usamos cents_para; senão cents_de
      if [ "$de_cur" = "BRL" ]; then cents_de_brl=$cents_de; cents_para_brl=$cents_de
      elif [ "$para_cur" = "BRL" ]; then cents_de_brl=$cents_para; cents_para_brl=$cents_para
      else cents_de_brl=$cents_de; cents_para_brl=$cents_de; fi
      cents_de=$cents_de_brl; cents_para=$cents_para_brl; fx_de=$fx_rate; fx_para=$fx_rate
    fi
    # insere débito
    id_d=$(sq "INSERT INTO transactions(date,amount,description,category,account_id,source,status,tx_type,currency,amount_original,fx_rate)
      VALUES('$(esc "$dt")',-$cents_de,'$(esc "$desc")','Transferência própria',$de_id,'manual','confirmado','transfer','$de_cur',-$orig_de,$fx_de);
      SELECT last_insert_rowid();")
    # insere crédito
    id_c=$(sq "INSERT INTO transactions(date,amount,description,category,account_id,source,status,tx_type,currency,amount_original,fx_rate,transfer_pair_id)
      VALUES('$(esc "$dt")',$cents_para,'$(esc "$desc")','Transferência própria',$para_id,'manual','confirmado','transfer','$para_cur',$orig_para,$fx_para,$id_d);
      SELECT last_insert_rowid();")
    # vincula débito ao crédito
    sq "UPDATE transactions SET transfer_pair_id=$id_c WHERE id=$id_d;"
    echo "OK — Transferência: $(cents_fmt $cents_de) $de_cur  $de_name → $para_name  (#$id_d ↔ #$id_c)"
    ;;

  rendimento)  # rendimento <conta> <valor> [data] [desc]
    # Valor positivo = rendimento; negativo = perda/depreciação
    conta_raw="${1:?uso: rendimento <conta> <valor> [data] [desc]}"; val="${2:?valor}"
    dt="${3:-$(date +%F)}"; desc="${4:-Rendimento}"
    conta_id=$(sq "SELECT id FROM accounts WHERE CAST(id AS TEXT)='$(esc "$conta_raw")' OR lower(name) LIKE lower('%$(esc "$conta_raw")%') LIMIT 1;")
    [ -z "$conta_id" ] && { echo "Conta não encontrada: $conta_raw"; exit 1; }
    conta_cur=$(sq "SELECT COALESCE(currency,'BRL') FROM accounts WHERE id=$conta_id;")
    conta_name=$(sq "SELECT name FROM accounts WHERE id=$conta_id;")
    cents=$(to_cents "$val"); [ "$cents" = "ERR" ] && { echo "valor inválido"; exit 1; }
    id=$(sq "INSERT INTO transactions(date,amount,description,category,account_id,source,status,tx_type,currency,amount_original,fx_rate)
      VALUES('$(esc "$dt")',$cents,'$(esc "$desc")','Rendimento',$conta_id,'manual','confirmado','rendimento','$conta_cur',$cents,1);
      SELECT last_insert_rowid();")
    tipo=$( [ "${cents:0:1}" = "-" ] && echo "perda" || echo "rendimento" )
    echo "OK #$id — $tipo: $(cents_fmt ${cents#-}) $conta_cur em $conta_name · $dt"
    ;;

  valuation)  # valuation <conta> <valor> [data] [notas]
    # Snapshot do valor de mercado atual da conta (para acompanhamento)
    conta_raw="${1:?uso: valuation <conta> <valor> [data] [notas]}"; val="${2:?valor}"
    dt="${3:-$(date +%F)}"; notas="${4:-}"
    conta_id=$(sq "SELECT id FROM accounts WHERE CAST(id AS TEXT)='$(esc "$conta_raw")' OR lower(name) LIKE lower('%$(esc "$conta_raw")%') LIMIT 1;")
    [ -z "$conta_id" ] && { echo "Conta não encontrada: $conta_raw"; exit 1; }
    conta_cur=$(sq "SELECT COALESCE(currency,'BRL') FROM accounts WHERE id=$conta_id;")
    cents=$(to_cents "$val"); [ "$cents" = "ERR" ] && { echo "valor inválido"; exit 1; }; cents=${cents#-}
    sq "INSERT INTO account_valuations(account_id,date,value,currency,notes) VALUES($conta_id,'$(esc "$dt")',$cents,'$conta_cur','$(esc "$notas")');"
    echo "OK — snapshot: $(cents_fmt $cents) $conta_cur · $dt"
    ;;

  balance)  # balance [conta_id|nome]  — saldo atual de uma ou todas as contas
    conta_raw="${1:-}"
    if [ -n "$conta_raw" ]; then
      where="WHERE CAST(a.id AS TEXT)='$(esc "$conta_raw")' OR lower(a.name) LIKE lower('%$(esc "$conta_raw")%')"
    else
      where=""
    fi
    sq -separator '|' "SELECT a.name, COALESCE(a.currency,'BRL'),
      printf('%.2f',(COALESCE(a.opening_balance,0)+COALESCE(SUM(CASE WHEN t.currency=COALESCE(a.currency,'BRL') THEN t.amount_original ELSE t.amount END),0))/100.0)
      FROM accounts a LEFT JOIN transactions t ON t.account_id=a.id
      $where
      GROUP BY a.id ORDER BY a.name;"
    ;;

  *) echo "uso: finance.sh {init|accounts|add|list|categorize|autocat|summary|nivel|config|transfer-add|rendimento|valuation|balance}";;
esac
