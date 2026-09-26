"""fuentes_extra.py — fuentes traídas del Radar de Crecimiento (convocatorias y oportunidades, no solo Lima).

  Devpost              hackathons abiertos y próximos (API JSON pública)
  WikiCFP              calls for papers de ingeniería industrial, IO, supply chain (RSS)
  Opportunity Desk     becas, fellowships y programas internacionales (RSS)
  Opportunities for Youth  voluntariados (RSS)
  TEDx                 eventos TEDx en el Perú (datos embebidos en ted.com, permitido por robots.txt)

Cada función recibe `limite` (horizonte) y `get` (el requests.get de eventos.py que respeta robots.txt)
y devuelve eventos con el mismo formato que las fuentes de eventos.py, más:
  tipo     "evento" | "hackathon" | "convocatoria" | "voluntariado" | "call for papers"
  cierre   fecha límite para postular (ISO) si se conoce
  _motivo  si trae un motivo, el evento va al Archivo en vez de a la lista (nunca se descarta)
Solo biblioteca estándar: la GitHub Action no necesita dependencias nuevas.
"""
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

LIMA = timezone(timedelta(hours=-5))
MESES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10,
         "nov": 11, "dec": 12, "ene": 1, "abr": 4, "ago": 8, "set": 9, "dic": 12}
_MES = (r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|ene|abr|ago|set|dic)[a-z]*\.?")
_FECHA = re.compile(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:de\s+)?({_MES})(?:,?\s+(?:de\s+)?(\d{{4}}))?"
                    rf"|({_MES})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", re.I)
DISPARADORES = re.compile(r"(deadline|fecha l[ií]mite|applications? close|closing date|apply by|"
                          r"(inscripci[oó]n(es)?|postulaci[oó]n(es)?|registro)\s+hasta|postula\s+hasta|"
                          r"cierre de (inscripciones|postulaciones|la convocatoria|convocatoria)|plazo)", re.I)


def iso(dt):
    return dt.astimezone(LIMA).isoformat(timespec="minutes") if dt else ""


def _fecha(dia, mes, anio, referencia):
    """Arma la fecha; si falta el año, toma la próxima ocurrencia desde `referencia`."""
    m = MESES.get(mes.lower().rstrip(".")[:3])
    if not m:
        return None
    try:
        d = datetime(int(anio) if anio else referencia.year, m, int(dia), 23, 59, tzinfo=LIMA)
    except ValueError:
        return None
    if not anio and d < referencia:
        d = d.replace(year=d.year + 1)
    return d


def fecha_texto(s, referencia=None):
    """'30 September 2026' / 'September 30, 2026' / '15 de octubre' → datetime (fin del día, Lima)."""
    referencia = referencia or datetime.now(LIMA)
    m = _FECHA.search(s or "")
    if not m:
        return None
    if m.group(1):
        return _fecha(m.group(1), m.group(2), m.group(3), referencia)
    return _fecha(m.group(5), m.group(4), m.group(6), referencia)


def extraer_cierre(texto, referencia):
    """Busca 'Deadline: 30 September 2026' / 'fecha límite: 15 de octubre' en texto libre."""
    for m in DISPARADORES.finditer(texto or ""):
        d = fecha_texto(texto[m.end(): m.end() + 90], referencia)
        if d:
            return d
    return None


def rango(texto):
    """'Jul 31 - Oct 01, 2026' / 'Oct 03 - 05, 2026' / 'Apr 28, 2027 - Apr 30, 2027' → (inicio, fin)."""
    partes = [p.strip() for p in (texto or "").split(" - ")]
    if not partes or not partes[0]:
        return None, None
    fin_txt = partes[-1]
    anio = re.search(r"\d{4}", fin_txt)
    if len(partes) > 1 and not re.search(r"[A-Za-z]", fin_txt):  # 'Oct 03 - 05, 2026'
        fin_txt = partes[0].split()[0] + " " + fin_txt
    fin = fecha_texto(fin_txt)
    ini_txt = partes[0] if re.search(r"\d{4}", partes[0]) or not anio else f"{partes[0]}, {anio.group(0)}"
    ini = fecha_texto(ini_txt)
    if ini and fin and ini > fin:  # cruza de año: 'Dec 20 - Jan 10, 2027'
        ini = ini.replace(year=fin.year - 1)
    if ini:
        ini = ini.replace(hour=0, minute=0)
    return ini, fin


def limpiar(h, largo=700):
    t = re.sub(r"</(p|li|h\d)>|<br\s*/?>", "\n", h or "")
    t = html.unescape(re.sub(r"<[^>]+>", "", t))
    t = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", t)).strip()
    return t[:largo]


def _primera_imagen(h):
    m = re.search(r'<img[^>]+src="(https?://[^"]+)"', h or "")
    return m.group(1) if m else ""


# ---------------------------------------------------------------- Devpost
def devpost(limite, get):
    out = {}
    for pagina in range(1, 7):
        r = get("https://devpost.com/api/hackathons",
                params={"status[]": ["upcoming", "open"], "page": pagina}, timeout=25)
        r.raise_for_status()
        hacks = r.json().get("hackathons") or []
        for h in hacks:
            ini, fin = rango(h.get("submission_period_dates", ""))
            loc = h.get("displayed_location") or {}
            lugar = loc.get("location") or ""
            online = lugar.lower() in ("online", "") or loc.get("icon") == "globe"
            premio = re.sub(r"<[^>]+>", "", h.get("prize_amount") or "").strip()
            temas = [t.get("name", "") for t in h.get("themes") or []]
            img = h.get("thumbnail_url") or ""
            motivo = None
            if h.get("invite_only"):
                motivo = "solo por invitación"
            elif not online and "peru" not in lugar.lower():
                motivo = "presencial fuera del Perú"
            out[h["id"]] = {
                "id": f"devpost:{h['id']}",
                "titulo": (h.get("title") or "").strip(),
                "tipo": "hackathon",
                "inicio": iso(ini), "fin": iso(fin), "cierre": iso(fin),
                "lugar": "" if online else lugar, "distrito": "" if online else lugar.split(",")[0],
                "modalidad": "Virtual" if online else "Presencial",
                "url": h.get("url", ""), "inscripcion": h.get("url", ""),
                "fuente": "Devpost", "fuente_url": "https://devpost.com/hackathons",
                "organizador": h.get("organization_name") or "",
                "descripcion": f"Hackathon {'online' if online else 'presencial en ' + lugar}. "
                               f"Temas: {', '.join(temas) or 'abiertos'}. Premios: {premio or 'no indicados'}.",
                "etiquetas": temas,
                "gratis": True,
                "imagen": ("https:" + img) if img.startswith("//") else img,
                "cats_fuente": ["Competencias y hackathons"],
                "_motivo": motivo,
            }
        if not hacks:
            break
    return list(out.values())


# ---------------------------------------------------------------- RSS (WordPress, WikiCFP)
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
MEDIA = "{http://search.yahoo.com/mrss/}content"


def _rss(url, get):
    r = get(url, timeout=25)
    r.raise_for_status()
    raiz = ET.fromstring(r.content)
    for it in raiz.iter("item"):
        media = it.find(MEDIA)
        encl = it.find("enclosure")
        yield {
            "titulo": html.unescape((it.findtext("title") or "").strip()),
            "link": (it.findtext("link") or "").strip(),
            "resumen": it.findtext("description") or "",
            "cuerpo": it.findtext(CONTENT) or "",
            "fecha": it.findtext("pubDate") or "",
            "categorias": [c.text or "" for c in it.findall("category")],
            "imagen": (media.get("url") if media is not None else "")
                      or (encl.get("url") if encl is not None and "image" in (encl.get("type") or "") else ""),
        }


def _publicado(s):
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).astimezone(LIMA)
    except (TypeError, ValueError):
        return datetime.now(LIMA)


def _convocatorias(feed, fuente, fuente_url, tipo, cats, get):
    ahora = datetime.now(LIMA)
    out = []
    for p in _rss(feed, get):
        if not p["titulo"]:
            continue
        pub = _publicado(p["fecha"])
        texto = limpiar(p["cuerpo"] or p["resumen"], 6000)
        cierre = extraer_cierre(texto, pub)
        # Muchos feeds solo traen un resumen sin el plazo: si la publicación es reciente se muestra igual
        # ("plazo: ver en la fuente"); si es antigua y sin plazo, lo más probable es que ya cerró.
        motivo = None
        if cierre and cierre < ahora:
            motivo = "plazo vencido"
        elif not cierre and ahora - pub > timedelta(days=45):
            motivo = "publicación antigua sin fecha límite"
        out.append({
            "id": f"{fuente.lower().replace(' ', '')}:{re.sub(r'[^a-z0-9]+', '-', p['link'].lower())[-70:]}",
            "titulo": p["titulo"], "tipo": tipo,
            # En la lista, una convocatoria se ubica por su fecha de cierre (sin cierre: al final, "ver plazo").
            "inicio": iso(cierre or pub), "fin": iso(cierre or pub), "cierre": iso(cierre),
            "publicado": iso(pub),
            "lugar": "", "distrito": "", "modalidad": "Internacional",
            "url": p["link"], "inscripcion": p["link"],
            "fuente": fuente, "fuente_url": fuente_url,
            "organizador": "",
            "descripcion": limpiar(p["resumen"] or texto, 700),
            "etiquetas": p["categorias"],
            "gratis": None,
            "imagen": p["imagen"] or _primera_imagen(p["cuerpo"]),
            "cats_fuente": cats,
            "_motivo": motivo,
        })
    return out


def opportunity_desk(limite, get):
    return _convocatorias("https://opportunitydesk.org/feed/", "Opportunity Desk", "https://opportunitydesk.org/",
                          "convocatoria", ["Idiomas, becas e internacional"], get)


def opportunities_youth(limite, get):
    return _convocatorias("https://opportunitiesforyouth.org/category/volunteering/feed/",
                          "Opportunities for Youth", "https://opportunitiesforyouth.org/category/volunteering/",
                          "voluntariado", ["Voluntariado e impacto social"], get)


WIKICFP = ["industrial engineering", "operations research", "supply chain", "logistics", "optimization"]


def wikicfp(limite, get):
    ahora = datetime.now(LIMA)
    out = {}
    for cat in WIKICFP:
        for p in _rss("http://www.wikicfp.com/cfp/rss?cat=" + cat.replace(" ", "%20"), get):
            if p["link"] in out:  # el mismo CFP aparece en varias categorías
                continue
            desc = limpiar(p["resumen"], 1000)
            corchetes = re.findall(r"\[([^\]]+)\]", desc)
            lugar = corchetes[0] if corchetes else ""
            ini, fin = rango(corchetes[1]) if len(corchetes) > 1 else (None, None)
            motivo = None
            if not ini:
                anio = re.search(r"\b(20\d{2})\s*:", p["titulo"])
                motivo = "congreso de un año pasado" if anio and int(anio.group(1)) < ahora.year \
                    else "sin fechas del congreso"
            elif (fin or ini) < ahora:
                motivo = "congreso ya realizado"
            online = bool(re.search(r"online|virtual", lugar, re.I))
            nombre = re.sub(r"\s*\[.*$", "", desc).strip() or p["titulo"]
            out[p["link"]] = {
                "id": "wikicfp:" + (re.search(r"eventid=(\d+)", p["link"]) or re.search(r"(.*)", p["link"])).group(1)[-40:],
                "titulo": p["titulo"], "tipo": "call for papers",
                "inicio": iso(ini), "fin": iso(fin or ini), "cierre": "",
                "lugar": lugar, "distrito": "",
                "modalidad": "Virtual" if online else "Internacional",
                "url": p["link"], "inscripcion": p["link"],
                "fuente": "WikiCFP", "fuente_url": "http://www.wikicfp.com/cfp/",
                "organizador": "",
                "descripcion": f"Call for papers: {nombre}. Lugar: {lugar or 'n/d'}. "
                               f"Fechas del congreso: {corchetes[1] if len(corchetes) > 1 else 'n/d'}.",
                "etiquetas": ["call for papers", cat],
                "gratis": None, "imagen": "",
                "cats_fuente": ["Investigación y ciencia"],
                "_motivo": motivo,
            }
    return list(out.values())


# ---------------------------------------------------------------- TEDx
def tedx(limite, get):
    """Directorio de TEDx ordenado por fecha: se recorre hasta el horizonte y se queda con el Perú."""
    out = []
    for pagina in range(1, 31):
        r = get("https://www.ted.com/tedx/events", params={"when": "upcoming", "page": pagina}, timeout=25)
        r.raise_for_status()
        m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text, re.S)
        if not m:
            raise RuntimeError("TEDx cambió su página: no encuentro __NEXT_DATA__")
        directorio = json.loads(m.group(1))["props"]["pageProps"]["directory"]
        eventos = directorio.get("events") or []
        for e in eventos:
            v = e.get("venue") or {}
            if v.get("countryName") != "Peru":
                continue
            ini = datetime.fromisoformat(e["beginAt"].replace("Z", "+00:00")) if e.get("beginAt") else None
            fin = datetime.fromisoformat(e["endAt"].replace("Z", "+00:00")) if e.get("endAt") else None
            url = f"https://www.ted.com/tedx/events/{e['id']}"
            out.append({
                "id": f"tedx:{e['id']}", "titulo": (e.get("title") or "").strip(), "tipo": "evento",
                "inicio": iso(ini), "fin": iso(fin), "cierre": "",
                "lugar": v.get("name") or v.get("city") or "", "distrito": v.get("city") or "",
                "modalidad": "Presencial",
                "url": url, "inscripcion": e.get("webstreamUrl") or url,
                "fuente": "TEDx", "fuente_url": "https://www.ted.com/tedx/events",
                "organizador": e.get("groupName") or "",
                "descripcion": f"Evento TEDx ({e.get('licenseLabel') or 'estándar'}) en {v.get('city') or 'Perú'}. "
                               f"Disponibilidad: {e.get('availability') or 'n/d'}.",
                "etiquetas": ["TEDx"], "gratis": None, "imagen": "",
                "cats_fuente": ["Habilidades y liderazgo"],
            })
        ultimo = eventos[-1].get("beginAt") if eventos else None
        if not directorio.get("pageInfo", {}).get("hasNextPage") or \
                (ultimo and datetime.fromisoformat(ultimo.replace("Z", "+00:00")) > limite):
            break
    return out


def fuentes(get):
    """Registro para eventos.FUENTES: nombre → función(limite)."""
    return {
        "Devpost": lambda lim: devpost(lim, get),
        "WikiCFP": lambda lim: wikicfp(lim, get),
        "Opportunity Desk": lambda lim: opportunity_desk(lim, get),
        "Opportunities for Youth": lambda lim: opportunities_youth(lim, get),
        "TEDx": lambda lim: tedx(lim, get),
    }
