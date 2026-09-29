"""linktree_lector.py — lee los Linktree registrados y separa sus inscripciones de eventos (reglas, sin IA).

Linktree prohíbe robots programados (robots.txt: `User-agent: *` → `Disallow: /`). Este lector corre SOLO cuando
una persona lo pide: el botón de la página /linktree/ (dispara el workflow "Actualizar Linktree", que NO tiene
horario), el botón local de JARVIS o el comando /linktree. Una petición por Linktree, identificándose como tal.

Uso (lo llama el workflow; también sirve a mano):
  python linktree_lector.py actualizar            abre cada Linktree registrado y agrega lo nuevo
  python linktree_lector.py agregar <url>         registra un Linktree y lo procesa
  python linktree_lector.py decidir <url> si|no   resuelve un enlace "por decidir"
  (añade --probar para ver qué haría sin guardar)
Modifica inscripciones.json (incluido "ultimo": el resumen que muestra la página).
"""
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

RAIZ = Path(__file__).resolve().parent
JSON = RAIZ / "inscripciones.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; RadarLima-a-pedido/1.0; consulta iniciada por una persona; "
                    "+https://juanpradomts-dev.github.io/radar-eventos-lima/)",
      # cabeceras normales de cualquier navegador (sin ellas Linktree a veces responde 406); el User-Agent sigue
      # diciendo quiénes somos
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "es-PE,es;q=0.9,en;q=0.6"}


def get_con_reintento(u, pausa=6):
    """Una consulta; si Linktree responde 406/429/503 (bloqueo pasajero), espera y reintenta UNA vez."""
    import requests
    import time
    r = requests.get(u, headers=UA, timeout=25)
    if r.status_code in (406, 429, 503):
        time.sleep(pausa)
        r = requests.get(u, headers=UA, timeout=25)
    return r

# ---------------------------------------------------------------- clasificación
FUERA_DOMINIO = re.compile(r"(whatsapp\.com|wa\.me|instagram\.com|tiktok\.com|youtube\.com|youtu\.be|facebook\.com|"
                           r"fb\.me|twitter\.com|(^|\.)x\.com|t\.me|spotify\.com|linkedin\.com/(company|in)/|"
                           r"linktr\.ee|threads\.net|pinterest\.)", re.I)
FUERA_TITULO = re.compile(r"(admisi[oó]n|nuestras carreras|carreras (universitarias|para)|pregrado|posgrado|postgrado|"
                          r"maestr[ií]a|diplomado|escr[ií]benos|cont[aá]ct|whatsapp|\bnoticias\b|tesis|sitio web|"
                          r"p[aá]gina web|tienda|s[ií]guenos|nuestra web|conoce nuestr|\bclub\b.*[úu]nete|[úu]nete al club)",
                          re.I)
EVENTO_DOMINIO = re.compile(r"(forms\.gle|docs\.google\.com/forms|forms\.office\.com|forms\.cloud\.microsoft|lu\.ma|"
                            r"luma\.com|eventbrite\.|sympla\.|zoom\.us/(webinar|meeting)/register|typeform\.com|"
                            r"jotform\.|tally\.so|teams\.microsoft\.com/registration)", re.I)
EVENTO_TITULO = re.compile(r"(inscr[ií]b|inscripci|reg[ií]str|charla|taller|congreso|conferencia|webinar|seminario|"
                           r"concurso|hackat|voluntari|\bbeca|intercambio|semana|feria|\bcurso|evento|sprint|summit|"
                           r"\bforo\b|convocatoria|postula|programa|ciclo de|masterclass|workshop|bootcamp|\bmun\b|"
                           r"comit[eé]|simposio|jornada|encuentro|olimpiada|reto|desaf[ií]o)", re.I)


def limpiar_url(u):
    """Quita parámetros de seguimiento (utm_*, fbclid, igsh…) sin tocar los que sí importan (id de formulario)."""
    p = urlsplit(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
         if not re.match(r"(utm_|fbclid|igsh|gclid|mc_|si$|ref$)", k, re.I)]
    return urlunsplit((p.scheme or "https", p.netloc, p.path, urlencode(q), ""))


def normalizar_linktree(u):
    """'linktr.ee/usuario?utm…' → 'https://linktr.ee/usuario'. None si no es un Linktree."""
    m = re.search(r"linktr\.ee/([A-Za-z0-9._-]+)", u or "")
    return f"https://linktr.ee/{m.group(1)}" if m else None


def clasificar(titulo, url):
    """'evento' (entra solo), 'fuera' (no es un evento) o 'dudoso' (decide JP)."""
    if FUERA_DOMINIO.search(url) or FUERA_TITULO.search(titulo):
        return "fuera"
    if EVENTO_DOMINIO.search(url) or EVENTO_TITULO.search(titulo):
        return "evento"
    return "dudoso"


def tipo_org(nombre):
    n = nombre.lower()
    if re.search(r"universidad|university|facultad|escuela|instituto|pucp|uni\b|unmsm|upc|utec|usil|esan", n):
        return "universidad"
    if re.search(r"voluntari|\bong\b|fundaci", n):
        return "ong"
    if re.search(r"c[aá]mara|sociedad nacional|asociaci[oó]n|gremio", n):
        return "gremio"
    if re.search(r"colegio de", n):
        return "colegio profesional"
    return ""


def leer_linktree(url, get):
    """(perfil, [{titulo, url}]) desde el __NEXT_DATA__ de la página: los enlaces exactos, sin adivinar."""
    r = get(url)
    if r.status_code != 200:
        raise RuntimeError(f"Linktree respondió {r.status_code}")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', r.text, re.S)
    if not m:
        raise RuntimeError("no encontré la lista de enlaces (¿cambió Linktree su página?)")
    pp = json.loads(m.group(1))["props"]["pageProps"]
    enlaces, vistos = [], set()
    for l in (pp.get("links") or []) + (pp.get("pinnedLinks") or []):
        u = (l.get("url") or "").strip()
        if not u or l.get("locked") or u in vistos:
            continue
        vistos.add(u)
        enlaces.append({"titulo": (l.get("title") or "").strip(), "url": u})
    return {"nombre": (pp.get("pageTitle") or pp.get("username") or "").strip()}, enlaces


# ---------------------------------------------------------------- acciones sobre inscripciones.json (puras)
def revisar(conf, get, hoy):
    """Abre cada Linktree registrado y agrega lo nuevo a conf. Devuelve (resumen por Linktree, total nuevos)."""
    conocidos = {limpiar_url(e["url"]) for e in conf.get("enlaces", [])}
    conocidos |= {limpiar_url(u) for u in conf.get("ignorados", [])}
    conocidos |= {limpiar_url(d["url"]) for d in conf.get("dudosos", [])}
    resumen, total = [], 0
    for lt, info in conf.get("linktrees", {}).items():
        fila = {"linktree": lt, "organizador": info.get("organizador", ""), "nuevos": [], "dudosos": [], "fuera": 0, "total": 0}
        try:
            perfil, enlaces = leer_linktree(lt, get)
            org = info.get("organizador") or perfil["nombre"]
            info["organizador"] = fila["organizador"] = org
            fila["total"] = len(enlaces)
            for l in enlaces:
                u = limpiar_url(l["url"])
                clase = clasificar(l["titulo"], u)
                if clase == "fuera":
                    fila["fuera"] += 1
                    continue
                if u in conocidos:
                    continue
                conocidos.add(u)
                item = {"url": u, "titulo": l["titulo"], "organizador": org,
                        "tipo_org": info.get("tipo_org") or tipo_org(org), "origen": lt, "agregado": hoy}
                (conf.setdefault("enlaces", []) if clase == "evento" else conf.setdefault("dudosos", [])).append(item)
                fila["nuevos" if clase == "evento" else "dudosos"].append(item)
            info["revisado"] = hoy
        except Exception as e:  # un Linktree que falla no frena a los demás
            fila["error"] = str(e)[:200]
        total += len(fila["nuevos"])
        resumen.append(fila)
    return resumen, total


def registrar_linktree(conf, url):
    lt = normalizar_linktree(url)
    if not lt:
        return False, "Eso no parece un Linktree (debe ser linktr.ee/...)."
    if lt in conf.setdefault("linktrees", {}):
        return False, "Ese Linktree ya estaba registrado."
    conf["linktrees"][lt] = {"organizador": "", "revisado": ""}
    return True, lt


def decidir(conf, url, agregar):
    item = next((d for d in conf.get("dudosos", []) if d["url"] == url), None)
    if not item:
        return False, "Ya no está en la lista de pendientes."
    conf["dudosos"] = [d for d in conf["dudosos"] if d["url"] != url]
    if agregar:
        conf.setdefault("enlaces", []).append(item)
    else:
        conf.setdefault("ignorados", []).append(url)
    return True, ("agregado: " if agregar else "no es evento: ") + item["titulo"][:80]


def cargar():
    return json.loads(JSON.read_text(encoding="utf-8"))


def guardar(conf):
    JSON.write_text(json.dumps(conf, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- línea de comandos (workflow / a mano)
def main(argv):
    import requests
    probar = "--probar" in argv
    argv = [a for a in argv if a != "--probar"]
    accion = argv[0] if argv else "actualizar"
    get = get_con_reintento
    ahora = datetime.now(timezone(timedelta(hours=-5)))
    conf = cargar()
    resumen, ok, mensaje = [], True, ""
    if accion == "agregar":
        ok, mensaje = registrar_linktree(conf, argv[1] if len(argv) > 1 else "")
        if ok:
            resumen, n = revisar(conf, get, ahora.date().isoformat())
            mensaje = f"Linktree agregado: {n} inscripciones nuevas"
    elif accion == "decidir":
        ok, mensaje = decidir(conf, argv[1], (argv[2] if len(argv) > 2 else "no").lower() in ("si", "sí", "true", "1"))
    else:
        resumen, n = revisar(conf, get, ahora.date().isoformat())
        mensaje = f"{n} inscripciones nuevas" if n else "sin inscripciones nuevas"
    # si ningún Linktree respondió, decirlo claro (antes decía "sin inscripciones nuevas" y era engañoso)
    if resumen and all(f.get("error") for f in resumen):
        ok = False
        mensaje = ("Linktree no respondió a los servidores de GitHub (bloqueo pasajero). Intenta en un rato, "
                   "o usa el botón «Radar Lima - Linktree» de tu PC, que sí puede abrirlo.")
    elif any(f.get("error") for f in resumen):
        mensaje += " · algunos Linktree no respondieron: " + ", ".join(f["organizador"] or f["linktree"] for f in resumen if f.get("error"))
    conf["ultimo"] = {"fecha": ahora.isoformat(timespec="minutes"), "accion": accion, "ok": ok,
                      "mensaje": mensaje, "linktrees": resumen}
    for f in resumen:
        print(f"{f['organizador'] or f['linktree']}: {f['total']} botones · {len(f['nuevos'])} nuevos · "
              f"{len(f['dudosos'])} por decidir · {f['fuera']} no son eventos" + (f" · ERROR {f['error']}" if f.get("error") else ""))
        for x in f["nuevos"]:
            print("   + " + x["titulo"])
        for x in f["dudosos"]:
            print("   ? " + x["titulo"] + " → " + x["url"])
    print(mensaje)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as s:
            s.write(f"## 🔗 Linktree ({accion})\n\n**{mensaje}**\n\n" + "".join(
                f"- **{f['organizador']}**: {f['total']} botones, {len(f['nuevos'])} nuevos, {len(f['dudosos'])} por decidir, "
                f"{f['fuera']} no son eventos\n" for f in resumen))
    if not probar:
        guardar(conf)  # siempre: "ultimo" le cuenta a la página qué pasó, también si algo no se pudo
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
