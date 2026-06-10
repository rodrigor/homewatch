#!/usr/bin/env python3
# PIrrai — inventário de dispositivos da casa (Flask)
# Cruza a tabela network do Pi-hole (auto) com metadados editáveis (SQLite local).
import os, sqlite3, subprocess, threading, time, re
from flask import Flask, jsonify, request, Response

DIR = os.path.dirname(os.path.abspath(__file__))
META_DB = os.path.join(DIR, "devices.db")
PIHOLE_DB = "/etc/pihole/pihole-FTL.db"
IFACE = "eth0"

app = Flask(__name__)
TOKEN_FILE = os.path.join(DIR, "admin_token.txt")
try:
    ADMIN_TOKEN = open(TOKEN_FILE).read().strip()
except Exception:
    ADMIN_TOKEN = ""
_online = {}          # mac -> ip (visto na última varredura)
_online_ts = 0
_lock = threading.Lock()

# ---------- metadados (editáveis) ----------
FIELDS = ["name","type","location","owner","brand_model","notes","icon",
          "trusted","connection","status","archived"]

def meta_db():
    c = sqlite3.connect(META_DB)
    c.execute("""CREATE TABLE IF NOT EXISTS device_meta(
        mac TEXT PRIMARY KEY, name TEXT, type TEXT, location TEXT, owner TEXT,
        brand_model TEXT, notes TEXT, icon TEXT, trusted INTEGER DEFAULT 0,
        connection TEXT, status TEXT DEFAULT 'ativo', archived INTEGER DEFAULT 0)""")
    try:
        c.execute("ALTER TABLE device_meta ADD COLUMN archived INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    return c

def get_meta():
    c = meta_db()
    cur = c.execute("SELECT * FROM device_meta")
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    c.close()
    return {r[0]: dict(zip(cols, r)) for r in rows}

# ---------- Pi-hole (somente leitura) ----------
def pihole_devices():
    try:
        c = sqlite3.connect(f"file:{PIHOLE_DB}?mode=ro", uri=True, timeout=5)
    except Exception as e:
        return []
    q = """SELECT n.id, n.hwaddr, n.macVendor, n.firstSeen, n.lastQuery, n.numQueries,
        (SELECT ip FROM network_addresses na WHERE na.network_id=n.id ORDER BY lastSeen DESC LIMIT 1),
        (SELECT name FROM network_addresses na WHERE na.network_id=n.id AND name IS NOT NULL ORDER BY lastSeen DESC LIMIT 1),
        (SELECT MAX(lastSeen) FROM network_addresses na WHERE na.network_id=n.id)
        FROM network n"""
    out = []
    for r in c.execute(q):
        nid, mac, vendor, first, lastq, nq, ip, host, lastseen = r
        mac = (mac or "").lower()
        out.append(dict(mac=mac, vendor=vendor or "", first_seen=first or 0,
                        num_queries=nq or 0, ip=ip or "", hostname=host or "",
                        last_seen=lastseen or lastq or 0))
    c.close()
    return out

def is_random_mac(mac):
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except Exception:
        return False

# ---------- varredura online (arp-scan, sem sudo via cap_net_raw) ----------
def scan_online():
    global _online, _online_ts
    try:
        p = subprocess.run(["arp-scan","--interface="+IFACE,"--localnet","--quiet","--plain"],
                           capture_output=True, text=True, timeout=30)
        found = {}
        for line in p.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                found[parts[1].lower()] = parts[0]
        with _lock:
            _online = found
            _online_ts = int(time.time())
    except Exception:
        pass

def scan_loop():
    while True:
        scan_online()
        time.sleep(90)

# ---------- API ----------
@app.route("/api/devices")
def api_devices():
    meta = get_meta()
    show_arch = request.args.get("archived") == "1"
    with _lock:
        online = dict(_online); ots = _online_ts
    now = int(time.time())
    devs = []
    for d in pihole_devices():
        # ignora pseudo-dispositivos (docker, loopback, placeholders do Pi-hole)
        if (d["mac"] in ("00:00:00:00:00:00", "") or "virtual" in (d["vendor"] or "").lower()
                or d["ip"].startswith("172.17.") or d["ip"] in ("127.0.0.1", "0.0.0.0")):
            continue
        m = meta.get(d["mac"], {})
        if bool(m.get("archived")) != show_arch:
            continue   # mostra arquivados só quando pedido; e oculta-os da lista normal
        d["random_mac"] = is_random_mac(d["mac"])
        d["online"] = d["mac"] in online
        if d["online"] and online.get(d["mac"]):
            d["ip"] = online[d["mac"]]   # IP ao vivo é mais confiável
        d["days_idle"] = round((now - d["last_seen"]) / 86400, 1) if d["last_seen"] else 999
        for f in FIELDS:
            d[f] = m.get(f) if m.get(f) is not None else (0 if f in ("trusted", "archived") else "")
        devs.append(d)
    devs.sort(key=lambda x: (not x["online"], -x["num_queries"]))
    return jsonify(dict(devices=devs, online_scan_age=now-ots if ots else None,
                        online_count=len(online)))

@app.route("/api/authcheck")
def api_authcheck():
    return jsonify(ok=(ADMIN_TOKEN != "" and request.args.get("token", "") == ADMIN_TOKEN))

@app.route("/api/device/<mac>", methods=["POST"])
def api_save(mac):
    if ADMIN_TOKEN != "" and request.headers.get("X-Auth-Token", "") != ADMIN_TOKEN:
        return jsonify(ok=False, error="auth"), 401
    mac = mac.lower()
    data = request.get_json(force=True) or {}
    c = meta_db()
    c.execute("INSERT OR IGNORE INTO device_meta(mac) VALUES(?)", (mac,))
    for f in FIELDS:
        if f in data:
            v = data[f]
            if f == "trusted": v = 1 if v else 0
            c.execute(f"UPDATE device_meta SET {f}=? WHERE mac=?", (v, mac))
    c.commit(); c.close()
    return jsonify(ok=True)

@app.route("/api/rescan", methods=["POST"])
def api_rescan():
    scan_online()
    with _lock:
        return jsonify(ok=True, online_count=len(_online))

@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")

PAGE = r"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PIrrai — Dispositivos da casa</title>
<style>
:root{--bg:#0f1419;--card:#1a212b;--line:#2a3441;--fg:#e6edf3;--mut:#8b98a5;--ac:#4aa8ff;--ok:#3fb950;--warn:#d29922}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,Segoe UI,Roboto,sans-serif}
header{padding:14px 18px;background:var(--card);border-bottom:1px solid var(--line);display:flex;gap:14px;align-items:center;flex-wrap:wrap;position:sticky;top:0;z-index:5}
h1{font-size:18px;margin:0}.sub{color:var(--mut);font-size:12px}
.filters{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-left:auto}
.filters label{color:var(--mut);font-size:12px;display:flex;gap:5px;align-items:center;cursor:pointer}
input[type=search]{background:#0b0f14;border:1px solid var(--line);color:var(--fg);padding:6px 10px;border-radius:7px;width:200px}
button{background:#243140;color:var(--fg);border:1px solid var(--line);padding:6px 12px;border-radius:7px;cursor:pointer}
button:hover{border-color:var(--ac)}
table{width:100%;border-collapse:collapse}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{position:sticky;top:56px;background:var(--bg);color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.04em;cursor:pointer;user-select:none}
tr:hover td{background:#161d26}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.on{background:var(--ok);box-shadow:0 0 6px var(--ok)}.off{background:#3a444f}
.mac{font-family:ui-monospace,monospace;font-size:11px;color:var(--mut)}
.vendor{font-size:11px;color:var(--mut)}
.tag{font-size:10px;padding:1px 6px;border-radius:9px;border:1px solid var(--line);color:var(--mut)}
.rnd{color:var(--warn);border-color:var(--warn)}
[contenteditable]{outline:none;min-width:40px;display:inline-block;border-bottom:1px dashed transparent;padding:1px 2px}
[contenteditable]:hover{border-bottom-color:var(--line)}[contenteditable]:focus{border-bottom-color:var(--ac);background:#0b0f14}
select,td input{background:#0b0f14;border:1px solid var(--line);color:var(--fg);border-radius:5px;padding:3px 5px;font-size:12px}
.trust{cursor:pointer;font-size:16px}
.idle{color:var(--mut);font-size:11px}
.muted td{opacity:.5}
.saved{animation:fl .8s}@keyframes fl{from{background:#1d3a1d}to{background:transparent}}
.cnt{font-size:12px;color:var(--mut)}
.act{padding:2px 7px;background:transparent;border:1px solid var(--line);border-radius:6px;font-size:13px;cursor:pointer}
.act:hover{border-color:var(--ac)}
</style></head><body>
<header>
  <div><h1>🏠 Dispositivos da casa <span class="sub" id="meta"></span></h1></div>
  <div class="filters">
    <input type="search" id="q" placeholder="buscar nome, IP, MAC, fabricante...">
    <label><input type="checkbox" id="fOnline"> só online</label>
    <label><input type="checkbox" id="fUntrusted"> só não-confiáveis</label>
    <label><input type="checkbox" id="fRandom"> ocultar MAC aleatório</label>
    <label><input type="checkbox" id="fArchived"> ver arquivados</label>
    <label>visto nos últimos
      <select id="fWindow">
        <option value="1">24 horas</option>
        <option value="7">7 dias</option>
        <option value="30" selected>30 dias</option>
        <option value="365">12 meses</option>
        <option value="0">sempre</option>
      </select>
    </label>
    <span class="cnt" id="shown"></span>
    <button id="lockbtn" onclick="toggleLock()">🔒 só leitura</button>
    <button onclick="rescan()">🔄 varrer rede</button>
  </div>
</header>
<table id="t"><thead><tr>
  <th data-k="online">●</th><th data-k="icon"></th><th data-k="name">Nome</th>
  <th data-k="type">Tipo</th><th data-k="location">Local</th><th data-k="owner">Dono</th>
  <th data-k="ip">IP</th><th data-k="vendor">Fabricante</th><th data-k="brand_model">Marca/Modelo</th>
  <th data-k="trusted">Conf.</th><th data-k="connection">Conex.</th><th data-k="status">Status</th>
  <th data-k="num_queries" title="Total acumulado de consultas DNS desde que o dispositivo foi visto pela 1ª vez. Mede o quão ativo/tagarela ele é na rede.">Consultas&nbsp;DNS</th><th data-k="days_idle" title="Há quantos dias o dispositivo não é visto na rede">Inativo</th>
  <th data-k="mac">MAC</th><th data-k="notes">Notas</th><th></th>
</tr></thead><tbody id="tb"></tbody></table>
<script>
const TYPES=["","celular","notebook","desktop","tablet","TV","smart speaker","câmera","IoT","console","NAS","impressora","roteador/rede","relógio","eletrodoméstico","outro"];
const CONN=["","Wi-Fi","Ethernet"];
const STATUS=["","ativo","visitante","emprestado","aposentado"];
const ICON={celular:"📱",notebook:"💻",desktop:"🖥️",tablet:"📲",TV:"📺","smart speaker":"🔊","câmera":"📷",IoT:"💡",console:"🎮",NAS:"🗄️","impressora":"🖨️","roteador/rede":"📶","relógio":"⌚","eletrodoméstico":"🔌"};
let DATA=[], sortK="online", sortAsc=false;
let unlocked=false, token=localStorage.getItem('hw_token')||'';
const $=s=>document.querySelector(s);
function esc(s){return (s||"").toString().replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]))}
async function load(){const arch=$('#fArchived').checked?'?archived=1':'';const r=await fetch('/api/devices'+arch);const j=await r.json();DATA=j.devices;
  $('#meta').textContent=`· ${DATA.length} dispositivos · ${j.online_count} online`+(j.online_scan_age!=null?` · varredura há ${j.online_scan_age}s`:'');
  render()}
function save(mac,field,val){return fetch('/api/device/'+mac,{method:'POST',headers:{'Content-Type':'application/json','X-Auth-Token':token},body:JSON.stringify({[field]:val})}).then(r=>{if(r.status===401){alert('🔒 Senha necessária para editar.');setUnlocked(false)}return r})}
function filt(d){
  const q=$('#q').value.toLowerCase();
  if(q && !([d.name,d.ip,d.mac,d.vendor,d.owner,d.location,d.brand_model].join(' ').toLowerCase().includes(q)))return false;
  if($('#fOnline').checked && !d.online)return false;
  if($('#fUntrusted').checked && d.trusted)return false;
  if($('#fRandom').checked && d.random_mac)return false;
  const w=+$('#fWindow').value;
  if(w>0 && d.days_idle>w)return false;
  return true}
function render(){
  let rows=DATA.filter(filt);
  $('#shown').textContent='▸ '+rows.length+' exibidos';
  rows.sort((a,b)=>{let x=a[sortK],y=b[sortK];if(typeof x==='string'){x=(x||'').toLowerCase();y=(y||'').toLowerCase()}return (x>y?1:x<y?-1:0)*(sortAsc?1:-1)});
  const tb=$('#tb');tb.innerHTML='';
  for(const d of rows){
    const tr=document.createElement('tr');if(d.days_idle>30)tr.className='muted';
    const ic=d.icon||ICON[d.type]||'';
    const tlist=(d.type&&!TYPES.includes(d.type))?[d.type,...TYPES]:TYPES;
    const topt=tlist.map(t=>`<option ${t===d.type?'selected':''}>${esc(t)}</option>`).join('');
    const clist=(d.connection&&!CONN.includes(d.connection))?[d.connection,...CONN]:CONN;
    const copt=clist.map(t=>`<option ${t===d.connection?'selected':''}>${esc(t)}</option>`).join('');
    const slist=(d.status&&!STATUS.includes(d.status))?[d.status,...STATUS]:STATUS;
    const sopt=slist.map(t=>`<option ${t===d.status?'selected':''}>${esc(t)}</option>`).join('');
    const CE=unlocked?'contenteditable':'', DIS=unlocked?'':'disabled';
    tr.innerHTML=`
      <td><span class="dot ${d.online?'on':'off'}"></span></td>
      <td><span class="trust" data-f="icon">${ic||'·'}</span></td>
      <td><span ${CE} data-f="name">${esc(d.name)}</span></td>
      <td><select data-f="type" ${DIS}>${topt}</select></td>
      <td><span ${CE} data-f="location">${esc(d.location)}</span></td>
      <td><span ${CE} data-f="owner">${esc(d.owner)}</span></td>
      <td>${esc(d.ip)}</td>
      <td class="vendor">${esc(d.vendor)} ${d.random_mac?'<span class="tag rnd">rnd</span>':''} ${d.hostname?'<br><span class=vendor>'+esc(d.hostname)+'</span>':''}</td>
      <td><span ${CE} data-f="brand_model">${esc(d.brand_model)}</span></td>
      <td><span class="trust" data-f="trusted">${d.trusted?'✅':'❓'}</span></td>
      <td><select data-f="connection" ${DIS}>${copt}</select></td>
      <td><select data-f="status" ${DIS}>${sopt}</select></td>
      <td>${d.num_queries.toLocaleString('pt-BR')}</td>
      <td class="idle">${d.days_idle>=999?'—':d.days_idle+'d'}</td>
      <td class="mac">${esc(d.mac)}</td>
      <td><span ${CE} data-f="notes">${esc(d.notes)}</span></td>
      <td>${unlocked?`<button class="act" data-act="${d.archived?'restore':'arch'}" title="${d.archived?'Restaurar':'Arquivar (some da lista)'}">${d.archived?'↩':'🗑'}</button>`:''}</td>`;
    const ab=tr.querySelector('button.act');
    if(ab) ab.onclick=()=>{const arch=ab.dataset.act==='arch';save(d.mac,'archived',arch);tr.remove()};
    tr.querySelectorAll('[contenteditable]').forEach(el=>{
      el.onblur=()=>{save(d.mac,el.dataset.f,el.textContent.trim());d[el.dataset.f]=el.textContent.trim();flash(el)}});
    tr.querySelectorAll('select').forEach(el=>{
      el.onchange=()=>{save(d.mac,el.dataset.f,el.value);d[el.dataset.f]=el.value;flash(el);if(el.dataset.f==='type')render()}});
    tr.querySelector('[data-f="trusted"]').onclick=function(){if(!unlocked)return;d.trusted=d.trusted?0:1;this.textContent=d.trusted?'✅':'❓';save(d.mac,'trusted',d.trusted)};
    tb.appendChild(tr);
  }
}
function flash(el){const td=el.closest('td');td.classList.remove('saved');void td.offsetWidth;td.classList.add('saved')}
async function rescan(){$('#meta').textContent=' · varrendo...';await fetch('/api/rescan',{method:'POST'});load()}
document.querySelectorAll('th[data-k]').forEach(th=>th.onclick=()=>{const k=th.dataset.k;if(sortK===k)sortAsc=!sortAsc;else{sortK=k;sortAsc=true}render()});
['q','fOnline','fUntrusted','fRandom','fWindow'].forEach(id=>{$('#'+id).addEventListener('input',render);$('#'+id).addEventListener('change',render)});
$('#fArchived').addEventListener('change',load);
function updateLockBtn(){const b=$('#lockbtn');if(b){b.textContent=unlocked?'🔓 edição liberada':'🔒 só leitura';b.style.borderColor=unlocked?'var(--ok)':''}}
function setUnlocked(v){unlocked=v;if(!v){token='';localStorage.removeItem('hw_token')}updateLockBtn();render()}
async function toggleLock(){
  if(unlocked){setUnlocked(false);return}
  const t=prompt('Cole a senha para liberar a edição:');if(!t)return;
  const j=await(await fetch('/api/authcheck?token='+encodeURIComponent(t.trim()))).json();
  if(j.ok){token=t.trim();localStorage.setItem('hw_token',token);unlocked=true;updateLockBtn();render()}else alert('Senha incorreta.');
}
(async()=>{
  if(token){try{const j=await(await fetch('/api/authcheck?token='+encodeURIComponent(token))).json();unlocked=!!j.ok}catch(e){}}
  updateLockBtn(); await load(); setInterval(load,30000);
})();
</script></body></html>"""

if __name__ == "__main__":
    threading.Thread(target=scan_loop, daemon=True).start()  # 1ª varredura roda em fundo; servidor sobe já
    app.run(host="0.0.0.0", port=8080, threaded=True)
