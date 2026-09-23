#!/home/rodrigor/turing-screen/.venv/bin/python
"""netpanel — painel dos links de internet no display USB (Turing Smart Screen 3.5").

Lê o ER605 por SNMPv3 (credenciais do routerwatch.env) e mostra, por operadora:
status do link, se é a rota padrão, taxa de download/upload e histórico curto.

O agente net-snmp do ER605 só atualiza os contadores de interface a cada ~15 s
(cache interno). Por isso consultamos a cada 1 s só pra detectar o instante exato
da atualização: a taxa é Δbytes / Δt entre duas atualizações (média de ~15 s).

As interfaces são localizadas pelo NOME (ifDescr), não pelo ifIndex, que muda
quando a configuração de WAN do roteador muda.

Uso:
  netpanel.py            # roda no display
  netpanel.py --preview  # gera netpanel-preview.png (sem display) e sai
"""
import os
import signal
import sqlite3
import subprocess
import sys
import time
from collections import deque
from datetime import datetime

LIB = "/home/rodrigor/turing-screen"
sys.path.insert(0, LIB)
from PIL import Image, ImageChops, ImageDraw, ImageFont  # noqa: E402

DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("ROUTERWATCH_DB", "/var/lib/routerwatch/routerwatch.db")
PORT = os.environ.get("PANEL_PORT", "/dev/serial/by-id/usb-2017-2-25_UsbMonitor_USB35INCHIPSV2-if00")
BRIGHTNESS = int(os.environ.get("PANEL_BRIGHTNESS", "30"))
W, H = 480, 320
HIST = 40  # amostras no gráfico (~15 s cada → ~10 min)

# traffic = interface cujos contadores medem o link (in = download)
# l3      = interface que recebe o IP da operadora (sem IP → link sem internet)
LINKS = [
    dict(key="claro", name="CLARO", color=(226, 38, 46), text=(255, 110, 110),
         traffic="inf.4094", l3="inf.4094"),
    dict(key="vivo", name="VIVO", color=(130, 50, 200), text=(190, 140, 255),
         traffic="inf.4093", l3="pe-wan2_poe"),
]

OID_DESCR = "1.3.6.1.2.1.2.2.1.2"
OID_OPER = "1.3.6.1.2.1.2.2.1.8"
OID_HCIN = "1.3.6.1.2.1.31.1.1.1.6"
OID_HCOUT = "1.3.6.1.2.1.31.1.1.1.10"
OID_ADDR_IF = "1.3.6.1.2.1.4.20.1.2"
OID_DEFROUTE_IF = "1.3.6.1.2.1.4.21.1.2.0.0.0.0"
OID_LOAD5 = "1.3.6.1.4.1.2021.10.1.3.2"

BG = (10, 13, 18)
CARD = (20, 25, 33)
LINE = (38, 46, 58)
FG = (230, 234, 240)
MUTED = (128, 138, 152)
GREEN = (60, 200, 110)
RED = (235, 70, 70)
AMBER = (240, 170, 50)


def load_env(path):
    env = {}
    try:
        for ln in open(path):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return env


class Router:
    def __init__(self, env):
        self.host = env.get("ROUTER_HOST", "192.168.54.1")
        self.auth = ["-v3", "-l", env.get("SNMP_SEC_LEVEL", "authNoPriv"), "-u", env["SNMP_USER"],
                     "-a", env.get("SNMP_AUTH_PROTO", "MD5"), "-A", env["SNMP_AUTH_PASS"],
                     "-t", "1", "-r", "1"]
        self.idx = {}  # nome -> ifIndex

    def _run(self, cmd, oids):
        out = subprocess.run([cmd, *self.auth, "-On", "-Oq", self.host, *oids],
                             capture_output=True, text=True, timeout=5)
        res = {}
        for ln in out.stdout.splitlines():
            oid, _, val = ln.partition(" ")
            if "No Such" in val or not val:
                continue
            res[oid.lstrip(".")] = val.strip().strip('"')
        return res

    def resolve(self):
        # ER605 prefixa com o VRF: "default/inf.4094"
        self.idx = {v.rsplit("/", 1)[-1]: int(k.rsplit(".", 1)[1])
                    for k, v in self._run("snmpwalk", [OID_DESCR]).items()}

    def addrs(self):
        """ifIndex -> [IPs]"""
        res = {}
        for k, v in self._run("snmpwalk", [OID_ADDR_IF]).items():
            ip = k[len(OID_ADDR_IF) + 1:]
            res.setdefault(int(v), []).append(ip)
        return res

    def poll(self):
        oids = [OID_DEFROUTE_IF, OID_LOAD5]
        for ln in LINKS:
            i = self.idx.get(ln["traffic"])
            if i:
                oids += [f"{OID_HCIN}.{i}", f"{OID_HCOUT}.{i}", f"{OID_OPER}.{i}"]
        return self._run("snmpget", oids)


def speedtests():
    """Último speedtest OK de cada operadora (até 2 dias)."""
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2)
        rows = con.execute(
            "SELECT wan, down_bps, up_bps, ping_ms FROM speedtest s WHERE ok=1 "
            "AND ts > strftime('%s','now') - 172800 "
            "AND ts = (SELECT MAX(ts) FROM speedtest WHERE wan=s.wan AND ok=1)").fetchall()
        con.close()
        return {r[0]: r[1:] for r in rows}
    except sqlite3.Error:
        return {}


def fmt_rate(bps):
    """-> (número, unidade)"""
    if bps is None:
        return "—", ""
    if bps >= 1e9:
        return f"{bps / 1e9:.2f}", "Gbps"
    if bps >= 1e6:
        m = bps / 1e6
        return (f"{m:.1f}" if m < 100 else f"{m:.0f}"), "Mbps"
    return f"{bps / 1e3:.0f}", "kbps"


class State:
    def __init__(self):
        self.links = {ln["key"]: dict(status="?", active=False, ip="", down=None, up=None,
                                      hist=deque(maxlen=HIST), last=None) for ln in LINKS}
        self.load5 = None
        self.last_ok = 0.0     # último poll SNMP bem-sucedido
        self.speed = {}


class Panel:
    def __init__(self):
        f = f"{LIB}/res/fonts"
        self.f_big = ImageFont.truetype(f"{f}/jetbrains-mono/JetBrainsMono-Bold.ttf", 34)
        self.f_mid = ImageFont.truetype(f"{f}/jetbrains-mono/JetBrainsMono-SemiBold.ttf", 22)
        self.f_name = ImageFont.truetype(f"{f}/roboto/Roboto-Black.ttf", 20)
        self.f_lbl = ImageFont.truetype(f"{f}/roboto/Roboto-Medium.ttf", 13)
        self.f_sm = ImageFont.truetype(f"{f}/roboto/Roboto-Regular.ttf", 12)
        self.f_smono = ImageFont.truetype(f"{f}/jetbrains-mono/JetBrainsMono-Regular.ttf", 11)
        self.f_clock = ImageFont.truetype(f"{f}/jetbrains-mono/JetBrainsMono-Bold.ttf", 22)

    def render(self, st: State):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        now = datetime.now()

        # Cabeçalho
        d.text((12, 8), "INTERNET", font=self.f_name, fill=FG)
        active = [ln for ln in LINKS if st.links[ln["key"]]["active"]]
        if active:
            ln = active[0]
            d.text((122, 13), "saindo pela", font=self.f_lbl, fill=MUTED)
            d.text((122 + d.textlength("saindo pela ", font=self.f_lbl), 13), ln["name"],
                   font=self.f_lbl, fill=ln["text"])
        dias = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
        d.text((W - 12, 7), now.strftime("%H:%M"), font=self.f_clock, fill=FG, anchor="ra")
        d.text((W - 88, 13), f"{dias[now.weekday()]} {now:%d/%m}", font=self.f_lbl, fill=MUTED, anchor="ra")

        for i, ln in enumerate(LINKS):
            self.card(d, st, ln, 8 + i * 236, 42, 228, 240)

        # Rodapé
        age = time.time() - st.last_ok
        if age > 30:
            d.text((12, 297), f"sem resposta do roteador há {int(age)} s", font=self.f_lbl, fill=AMBER)
        else:
            parts = []
            if st.load5 is not None:
                parts.append(f"ER605 load {st.load5:.2f}")
            t = pi_temp()
            if t:
                parts.append(f"Pi {t:.0f}°C")
            parts.append("taxas: média de 15 s")
            d.text((12, 297), "   ·   ".join(parts), font=self.f_sm, fill=MUTED)
        return img

    def card(self, d, st, ln, x, y, w, h):
        s = st.links[ln["key"]]
        d.rounded_rectangle((x, y, x + w, y + h), 8, fill=CARD)
        d.rounded_rectangle((x, y, x + w, y + 4), 2, fill=ln["color"])
        d.text((x + 12, y + 12), ln["name"], font=self.f_name, fill=ln["text"])

        status = s["status"]
        col, lbl = {"up": (GREEN, "ONLINE"), "down": (RED, "OFFLINE"),
                    "noip": (AMBER, "SEM IP")}.get(status, (MUTED, "…"))
        tw = d.textlength(lbl, font=self.f_lbl)
        px = x + w - 12 - tw - 22
        d.rounded_rectangle((px, y + 13, x + w - 10, y + 33), 10, outline=col, width=1)
        d.ellipse((px + 7, y + 19, px + 15, y + 27), fill=col)
        d.text((px + 19, y + 15), lbl, font=self.f_lbl, fill=col)

        role = "em uso" if s["active"] else ("reserva" if status == "up" else "fora do ar")
        sub = role + (f"  ·  {s['ip']}" if s["ip"] else "")
        d.text((x + 12, y + 40), sub, font=self.f_sm, fill=FG if s["active"] else MUTED)

        live = status == "up"
        for row, (arrow, val, font, yy) in enumerate(
                (("↓", s["down"], self.f_big, y + 60), ("↑", s["up"], self.f_mid, y + 104))):
            num, unit = fmt_rate(val if live else None)
            c = FG if live else MUTED
            d.text((x + 12, yy + (6 if row == 0 else 2)), arrow, font=self.f_mid, fill=ln["text"] if live else MUTED)
            d.text((x + 36, yy), num, font=font, fill=c)
            d.text((x + 40 + d.textlength(num, font=font), yy + (18 if row == 0 else 9)), unit,
                   font=self.f_lbl, fill=MUTED)

        # Gráfico: barras = download, linha = upload
        gx, gy, gw, gh = x + 12, y + 140, w - 24, 64
        d.line((gx, gy + gh, gx + gw, gy + gh), fill=LINE)
        hist = list(s["hist"])
        if hist:
            top = max(1e6, max(max(a, b) for a, b in hist))
            bw = gw / HIST
            off = HIST - len(hist)
            dim = tuple(int(c * 0.55 + b * 0.45) for c, b in zip(ln["color"], CARD))
            pts = []
            for k, (dn, upv) in enumerate(hist):
                bx = gx + (off + k) * bw
                bh = dn / top * gh
                if bh >= 1:
                    d.rectangle((bx + 0.5, gy + gh - bh, bx + bw - 1, gy + gh - 1), fill=dim)
                pts.append((bx + bw / 2, gy + gh - upv / top * gh))
            if len(pts) > 1:
                d.line(pts, fill=ln["text"], width=2)
            d.text((gx + gw, gy - 2), fmt_rate(top)[0] + " " + fmt_rate(top)[1], font=self.f_sm,
                   fill=MUTED, anchor="ra")

        sp = st.speed.get(ln["key"])
        if sp:
            dn, upv, ping = sp
            txt = f"speedtest ↓{dn / 1e6:.0f} ↑{upv / 1e6:.0f} Mbps · {ping:.0f}ms"
        else:
            txt = "speedtest  sem dados recentes"
        d.text((x + 12, y + h - 24), txt, font=self.f_smono, fill=MUTED)


def pi_temp():
    try:
        return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except (OSError, ValueError):
        return None


def update(router: Router, st: State, addrs):
    now = time.monotonic()
    res = router.poll()
    if not res:
        return False
    st.last_ok = time.time()
    try:
        st.load5 = float(res.get(OID_LOAD5, "x"))
    except ValueError:
        st.load5 = None
    def_if = int(res.get(OID_DEFROUTE_IF, "0") or 0)
    for ln in LINKS:
        s = st.links[ln["key"]]
        ti, li = router.idx.get(ln["traffic"]), router.idx.get(ln["l3"])
        if ti is None:
            s.update(status="down", active=False, ip="")
            continue
        oper = res.get(f"{OID_OPER}.{ti}", "")
        ips = addrs.get(li, [])
        s["ip"] = ips[0] if ips else ""
        s["status"] = "down" if oper not in ("1", "up") else ("up" if ips else "noip")
        s["active"] = def_if in (ti, li) and s["status"] == "up"
        try:
            cin, cout = int(res[f"{OID_HCIN}.{ti}"]), int(res[f"{OID_HCOUT}.{ti}"])
        except (KeyError, ValueError):
            continue
        last = s["last"]
        if last is None or cin < last[1] or cout < last[2]:  # início ou contador zerou
            s["last"] = (now, cin, cout)
        elif (cin, cout) != last[1:]:  # agente atualizou o cache
            dt = now - last[0]
            if dt > 0.5:
                s["down"] = (cin - last[1]) * 8 / dt
                s["up"] = (cout - last[2]) * 8 / dt
                s["hist"].append((s["down"], s["up"]))
            s["last"] = (now, cin, cout)
    return True


def main():
    env = load_env(os.path.join(DIR, "routerwatch.env"))
    router = Router(env)
    st = State()
    panel = Panel()

    if "--preview" in sys.argv:
        router.resolve()
        addrs = router.addrs()
        st.speed = speedtests()
        for _ in range(35):  # espera ~2 atualizações do cache do agente
            update(router, st, addrs)
            time.sleep(1)
        out = os.path.join(DIR, "netpanel-preview.png")
        panel.render(st).save(out)
        print(out)
        return

    from library.lcd.lcd_comm_rev_a import LcdCommRevA, Orientation
    lcd = LcdCommRevA(com_port=PORT, display_width=320, display_height=480)
    lcd.Reset()
    lcd.InitializeComm()
    lcd.SetBrightness(level=BRIGHTNESS)
    lcd.SetOrientation(orientation=Orientation.LANDSCAPE)

    stop = False

    def bye(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    prev = None
    addrs, t_addrs, t_resolve, t_speed = {}, 0.0, 0.0, 0.0
    while not stop:
        t0 = time.monotonic()
        try:
            if t0 - t_resolve > 300 or not router.idx:
                router.resolve()
                t_resolve = t0
            if t0 - t_addrs > 10:
                addrs = router.addrs()
                t_addrs = t0
            if not update(router, st, addrs):
                router.idx = {}  # força re-resolver na próxima volta
        except (subprocess.SubprocessError, OSError) as e:
            print(f"netpanel: erro SNMP: {e}", file=sys.stderr)
        if t0 - t_speed > 600:
            st.speed = speedtests()
            t_speed = t0

        img = panel.render(st)
        box = (0, 0, W, H) if prev is None else ImageChops.difference(img, prev).getbbox()
        if box:
            lcd.DisplayPILImage(img.crop(box), box[0], box[1])
        prev = img
        time.sleep(max(0.1, 1.0 - (time.monotonic() - t0)))

    lcd.Clear()


if __name__ == "__main__":
    main()
