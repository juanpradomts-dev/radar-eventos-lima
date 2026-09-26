"""eventos.py — Radar de eventos en Lima que SUMAN (no conciertos ni fiestas).

Recolecta eventos de Luma, Eventbrite, Meetup (iCal por grupo) y PUCP (fuentes públicas,
sin login, respetando robots.txt),
los clasifica por categoría (Tecnología/IA, Datos, Ingeniería y operaciones,
Negocios, Investigación, Habilidades, Idiomas y becas, Competencias), descarta
lo recreativo y puntúa cada uno según el perfil de JP. Genera:
  eventos.json      datos normalizados + historial de "vistos"
  site/index.html   página autocontenida

La página se recarga sola cada 15 min; el refresco lo hace la GitHub Action
.github/workflows/actualizar.yml cada 3 h y publica site/ en GitHub Pages.

Uso:
  python eventos.py              refresca y genera la página
  python eventos.py --abrir      además la abre en el navegador
  python eventos.py --dias 90    horizonte (def. 60 días)
  python eventos.py --solo-html  regenera la página con el JSON existente
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import html
import json
import re
import secrets
import unicodedata
from threading import Lock
from urllib import robotparser
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent
CARPETA = RAIZ / "site"
DATOS = RAIZ / "eventos.json"          # versionado: guarda cuándo se vio cada evento
PAGINA = CARPETA / "index.html"
LIMA = timezone(timedelta(hours=-5))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128 Safari/537.36",
      "Accept-Language": "es-PE,es;q=0.9"}
BOT = "radar-eventos-lima"  # nombre con el que se consulta robots.txt (cae en "*")


# ---------------------------------------------------------------- robots.txt
_ROBOTS = {}
_ROBOTS_LOCK = Lock()


def permitido(url):
    """Respeta robots.txt del sitio (caché por host). Sin robots.txt = permitido."""
    host = "{0.scheme}://{0.netloc}".format(urlsplit(url))
    with _ROBOTS_LOCK:
        rp = _ROBOTS.get(host)
        if rp is None:
            rp = robotparser.RobotFileParser()
            try:
                r = requests.get(host + "/robots.txt", headers=UA, timeout=15)
                if r.status_code in (401, 403):
                    rp.disallow_all = True
                elif r.ok:
                    rp.parse(r.content.decode("utf-8", errors="replace").splitlines())
                else:
                    rp.allow_all = True
            except requests.RequestException:
                rp.allow_all = True
            _ROBOTS[host] = rp
    return rp.can_fetch(BOT, url)


def get(url, **kw):
    """requests.get que antes verifica robots.txt."""
    if not permitido(url):
        raise PermissionError(f"robots.txt no permite {url}")
    kw.setdefault("headers", UA)
    return requests.get(url, **kw)


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# ---------------------------------------------------------------- clasificación
# Palabras sin tildes (se compara contra norm()). "\b" evita que "ia" pegue en "familia".
CATEGORIAS = {
    "Tecnología e IA": r"\b(ia|ai|inteligencia artificial|machine learning|llm|genai|gpt|claude|"
                       r"agentes?|agents?|python|javascript|programacion|developer|dev|devs|software|cloud|aws|"
                       r"azure|google cloud|kubernetes|kubefest|ciberseguridad|seguridad informatica|pentest|"
                       r"red team|hacking|blockchain|web3|n8n|automatiza\w*|no-?code|notion|replit|"
                       r"robot\w*|arduino|iot|ccna|cisco|redes|tech|tecnolog\w+|open source|linux|github)\b",
    "Datos y analítica": r"\b(datos|data|analytics|analitica|power bi|tableau|sql|big data|"
                         r"ciencia de datos|data science|estadistica|dashboard|excel|bi)\b",
    "Ingeniería y operaciones": r"\b(ingenieria|ingeniero|industrial|supply chain|cadena de suministro|"
                                r"logistica|operaciones|lean|six sigma|kaizen|procurement|compras|"
                                r"manufactura|mantenimiento|calidad|iso \d+|bim|proyectos de inversion|"
                                r"energia|mineria|sostenib\w+|mecanic\w+|electric\w+|pmp|project management|"
                                r"gestion de proyectos|scrum|agile)\b",
    "Negocios y emprendimiento": r"\b(emprend\w+|startup\w*|founders?|vc|venture|inversion|finanzas|"
                                 r"fintech|banca|banking|negocio\w*|pymes?|marketing|ventas|growth|"
                                 r"innovacion|business|e-?commerce|economia|pitch|incubadora|aceleradora|"
                                 r"networking|negociacion)\b",
    "Investigación y ciencia": r"\b(investigacion|research|paper|cientific\w+|ciencia|scopus|tesis|"
                               r"publicacion|academic\w*|congreso|simposio|concytec|laboratorio|"
                               r"biotecnolog\w+|fisica|quimica|matematica\w*)\b",
    "Habilidades y liderazgo": r"\b(liderazgo|lider\w*|oratoria|comunicacion efectiva|soft skills|"
                               r"habilidades|productividad|mentoring|mentoria|carrera|empleabilidad|"
                               r"cv|linkedin|entrevista|career|talento|coaching ejecutivo|debate|"
                               r"toastmasters|pensamiento critico)\b",
    "Idiomas, becas e internacional": r"\b(beca\w*|scholarship|educationusa|fulbright|chevening|"
                                      r"daad|intercambio|estudiar en el extranjero|study abroad|mba|"
                                      r"maestria|posgrado|ll\.?m|toefl|ielts|ingles|english|"
                                      r"expoestudios|feria educativa|admision)\b",
    "Competencias y hackathons": r"\b(hackathon|hackaton|datathon|datafest|game jam|ideathon|"
                                 r"concurso|competencia|challenge|olimpiada|reto|premiacion|demo ?day|"
                                 r"showcase)\b",
}
FORMATO = r"\b(taller|workshop|conferencia|charla|seminario|meetup|summit|congreso|foro|panel|" \
          r"conversatorio|bootcamp|curso|clase modelo|masterclass|webinar|simposio|keynote|" \
          r"hackathon|feria|jornada|open lab|kickoff|tech week|fest)\b"
# Lo que NO suma como estudiante: ocio, venta, espiritualidad, fiestas.
EXCLUIR = r"\b(concierto|fiesta|party|dj|rave|reggaeton|salsa|karaoke|stand ?up|comedia|" \
          r"closet sale|bazar|mercadillo|feria gastronomica|degustacion|cata|wine|cerveza|beer|" \
          r"brunch|dinner|cena|coctel\w*|cocktail|drinks|happy hour|cocina|chef|amigurumi\w*|crochet|manualidades|padel|running|carrera \d+k|\d+k\b|" \
          r"maraton|yoga|meditacion|reiki|tarot|astrolog\w+|constelaciones|sanacion|energia cuantica|" \
          r"retiro espiritual|culto|misa|iglesia|oracion|glow up|belleza|maquillaje|skincare|" \
          r"botanicals|cashflow|trading de|forex|cripto ?trading|multinivel|halloween|pijamada|" \
          r"kawaii|cosplay|anime|drag|speed ?dating|citas|singles|lanzamiento de|pop ?up|" \
          r"recorrido|tour|exposicion de arte|galeria|teatro|cine|danza|baile|esgrima)\b"
# Afinidad con JP: Ing. Industrial, datos/ML (BCP Datafest), supply chain, investigación, IA.
PERFIL = {
    r"\b(industrial|supply chain|cadena de suministro|logistica|almacen|lean|six sigma|operaciones|procurement)\b": 4,
    r"\b(data|datos|machine learning|ml|analytics|python|sql|power bi|estadistica|datafest|datathon)\b": 4,
    r"\b(ia|ai|inteligencia artificial|llm|agentes?|claude|genai)\b": 3,
    r"\b(hackathon|hackaton|competencia|concurso|challenge)\b": 3,
    r"\b(investigacion|research|scopus|paper|congreso|simposio)\b": 3,
    r"\b(beca\w*|educationusa|fulbright|mba|posgrado|intercambio|toefl|ielts)\b": 3,
    r"\b(liderazgo|oratoria|negociacion|mentoring|mentoria)\b": 2,
    r"\b(emprend\w+|startup\w*|founders?|innovacion|fintech|banca)\b": 2,
    r"\b(universidad|pucp|uni|upc|ucsur|ulima|esan|utec|usil|unmsm|san marcos)\b": 1,
    r"\b(gratis|gratuito|free|libre)\b": 1,
}


TOP = 8  # puntaje desde el que un evento es "Top para ti"


def clasificar(ev):
    """Devuelve (categorías, puntaje) o (None, 0) si el evento no suma."""
    titulo = norm(ev["titulo"])
    texto = f"{titulo} {norm(ev.get('descripcion', ''))[:1500]} {norm(' '.join(ev.get('etiquetas', [])))}"
    # El título manda para excluir: una charla de IA que menciona "coffee break" no se descarta.
    if re.search(EXCLUIR, titulo):
        return None, 0
    cats = [c for c, rx in CATEGORIAS.items() if re.search(rx, titulo)]
    if not cats and ev.get("cats_fuente"):  # la fuente ya trae área temática confiable (PUCP)
        cats = ev["cats_fuente"]
    if not cats:  # respaldo: descripción, pero exigiendo formato formativo en el título o texto
        cats = [c for c, rx in CATEGORIAS.items() if len(re.findall(rx, texto)) >= 2]
        if not cats or not re.search(FORMATO, texto):
            return None, 0
    puntos = sum(p for rx, p in PERFIL.items() if re.search(rx, texto))
    puntos += 2 * sum(1 for rx in PERFIL if re.search(rx, titulo))  # afinidad en el título pesa más
    if re.search(FORMATO, titulo):
        puntos += 1
    return cats, puntos


# ---------------------------------------------------------------- fuentes
def _iso(dt):
    return dt.astimezone(LIMA).isoformat(timespec="minutes") if dt else ""


def _parse(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=LIMA)
    except ValueError:
        return None


def luma(limite):
    """API pública de descubrimiento de Luma, centrada en Lima."""
    out, cursor = [], None
    for _ in range(8):
        p = {"latitude": -12.0464, "longitude": -77.0428, "pagination_limit": 50}
        if cursor:
            p["pagination_cursor"] = cursor
        r = get("https://api.lu.ma/discover/get-paginated-events", params=p, timeout=25)
        r.raise_for_status()
        j = r.json()
        for e in j.get("entries", []):
            ev = e.get("event", {})
            g = ev.get("geo_address_info") or {}
            if g.get("country_code") not in (None, "PE"):
                continue
            ini = _parse(ev.get("start_at"))
            tickets = e.get("ticket_info") or {}
            out.append({
                "id": "luma:" + ev.get("api_id", ""),
                "titulo": ev.get("name", "").strip(),
                "inicio": _iso(ini), "fin": _iso(_parse(ev.get("end_at"))),
                "lugar": g.get("short_address") or g.get("city_state") or "",
                "distrito": g.get("city") or "",
                "modalidad": "Virtual" if ev.get("location_type") == "online" else "Presencial",
                "url": "https://lu.ma/" + ev.get("url", ""),
                "fuente": "Luma",
                "organizador": (e.get("calendar") or {}).get("name", ""),
                "descripcion": (e.get("calendar") or {}).get("description_short", "") or "",
                "gratis": True if tickets.get("is_free") else (False if tickets.get("is_free") is False else None),
                "imagen": ev.get("cover_url", ""),
                "inscripcion": "https://lu.ma/" + ev.get("url", ""),
                "fuente_url": "https://lu.ma/lima",
                "_luma_id": ev.get("api_id", ""),
            })
            if ini and ini > limite:
                return out
        cursor = j.get("next_cursor")
        if not j.get("has_more") or not cursor:
            break
    return out


EB_API = "https://www.eventbrite.com.pe/api/v3/destination/search/"
EB_LIMA = "890442199"  # place id que usa la web de Eventbrite para /d/peru--lima/


def eventbrite(limite):
    """API interna de búsqueda de Eventbrite (la que usa su propia web).

    Las páginas /d/peru--lima/ devuelven 405 a las IPs de GitHub, pero esta API no:
    solo pide el patrón CSRF de Django (cookie csrftoken == cabecera X-CSRFToken).
    """
    tok = secrets.token_hex(16)
    cab = {**UA, "Content-Type": "application/json", "X-CSRFToken": tok,
           "Referer": "https://www.eventbrite.com.pe/d/peru--lima/all-events/"}
    if not permitido(EB_API):
        raise PermissionError(f"robots.txt no permite {EB_API}")
    busquedas = [{}, {"tags": ["EventbriteCategory/102"]}] + [
        {"q": q} for q in ("conferencia", "taller", "seminario", "hackathon", "networking",
                           "tecnologia", "datos", "ingenieria", "emprendimiento", "liderazgo")]
    out, diag = {}, set()
    for extra in busquedas:
        for pagina in range(1, 6):
            cuerpo = {"event_search": {"places": [EB_LIMA], "dates": "current_future", "dedup": True, "page": pagina,
                                       "page_size": 50, **extra},
                      "browse_surface": "search",  # sin esto la API ignora "q"
                      "expand.destination_event": ["primary_venue", "image", "ticket_availability",
                                                   "primary_organizer"]}
            r = requests.post(EB_API, headers=cab, cookies={"csrftoken": tok}, data=json.dumps(cuerpo), timeout=25)
            diag.add(str(r.status_code))
            if not r.ok:
                break
            res = r.json().get("events") or {}
            lista = res.get("results") or []
            for e in lista:
                if e.get("is_cancelled"):
                    continue
                ini = _parse(f"{e.get('start_date')}T{e.get('start_time') or '00:00'}")
                fin = _parse(f"{e.get('end_date')}T{e.get('end_time') or '00:00'}")
                v = e.get("primary_venue") or {}
                a = v.get("address") or {}
                t = e.get("ticket_availability") or {}
                out[e.get("id")] = {
                    "id": "eb:" + str(e.get("id")),
                    "titulo": (e.get("name") or "").strip(),
                    "inicio": _iso(ini), "fin": _iso(fin),
                    "lugar": ", ".join(x for x in (v.get("name"), a.get("address_1")) if x),
                    "distrito": a.get("city") or "",
                    "modalidad": "Virtual" if e.get("is_online_event") else "Presencial",
                    "url": e.get("url", ""),
                    "fuente": "Eventbrite",
                    "organizador": (e.get("primary_organizer") or {}).get("name", "") or "",
                    "descripcion": e.get("summary") or "",
                    "etiquetas": [x.get("display_name", "") for x in e.get("tags") or []],
                    "gratis": t.get("is_free"),
                    "imagen": (e.get("image") or {}).get("url", ""),
                    "inscripcion": e.get("url", ""),
                    "fuente_url": "https://www.eventbrite.com.pe/d/peru--lima/all-events/",
                }
            if not lista or pagina >= ((res.get("pagination") or {}).get("page_count") or 1):
                break
    if not out:
        raise RuntimeError("0 resultados: HTTP " + ",".join(sorted(diag)))
    return list(out.values())


def _local(texto):
    t = f" {norm(texto)} "
    if re.search(r"\b(peru|lima|pucp|uni|upc|utec|san marcos)\b", t):
        return True
    return sum(t.count(w) for w in (" de ", " la ", " para ", " con ", " el ", " y ", " en ")) >= 3


# Meetup prohíbe en robots.txt su buscador (/find/), pero permite el iCal de cada grupo:
# se siguen los grupos de Lima que publican cosas que suman.
GRUPOS_MEETUP = ["awsperu", "aws-sbg-at-national-university-of-engineering",
                 "aws-sbg-at-technological-university-of-peru", "bi-expert", "msperu",
                 "speak-up-conversation-club", "practice-english-saturday", "lince-english-group"]
VIRTUAL = r"\b(online|virtual|zoom|google meet|meet\.google|teams|youtube|webinar|transmision en vivo)\b"


def _texto_ical(v):
    if isinstance(v, list):  # propiedad repetida (Meetup duplica X-WR-CALNAME)
        v = v[0] if v else None
    if v is None:
        return ""
    return v.to_ical().decode("utf-8") if hasattr(v, "to_ical") and not isinstance(v, str) else str(v)


def _fecha_ical(v):
    if v is None:
        return None
    d = v.dt
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=LIMA)  # TZID America/Lima ya viene resuelto
    return datetime(d.year, d.month, d.day, tzinfo=LIMA)  # evento de día completo


def meetup(limite):
    from icalendar import Calendar
    out, errores = {}, []
    for g in GRUPOS_MEETUP:
        url_cal = f"https://www.meetup.com/{g}/events/ical/"
        try:
            r = get(url_cal, timeout=25)
            r.raise_for_status()
            # bytes, no r.text: requests adivina latin-1 para text/calendar y sale mojibake
            cal = Calendar.from_ical(r.content.decode("utf-8", errors="replace"))
        except Exception as e:  # un grupo roto no tumba a los demás
            errores.append(f"{g}: {e}")
            continue
        grupo = _texto_ical(cal.get("X-WR-CALNAME")) or _texto_ical(cal.get("NAME")) or g
        for ve in cal.walk("VEVENT"):
            if str(ve.get("STATUS", "")).upper() == "CANCELLED":
                continue
            ini = _fecha_ical(ve.get("DTSTART"))
            if not ini or ini > limite:
                continue
            titulo = str(ve.get("SUMMARY", "")).strip()
            desc = str(ve.get("DESCRIPTION", ""))
            if desc.startswith(grupo):  # Meetup antepone el nombre del grupo a la descripción
                desc = desc[len(grupo):].lstrip("\n ")
            lugar = str(ve.get("LOCATION", "") or "")
            online = not lugar and bool(re.search(VIRTUAL, norm(titulo + " " + desc[:600])))
            # un online solo entra si está en español o cita Perú (misma regla que antes)
            if online and not _local(titulo + " " + desc[:400]):
                continue
            url = str(ve.get("URL", "") or "")
            uid = str(ve.get("UID", "")) or f"{g}:{titulo}:{ini.isoformat()}"
            out[uid] = {
                "id": "meetup:" + uid.split("@")[0].removeprefix("event_"),
                "titulo": titulo,
                "inicio": _iso(ini), "fin": _iso(_fecha_ical(ve.get("DTEND")) or ini),
                "lugar": lugar,
                "distrito": "" if online else "Lima",
                "modalidad": "Virtual" if online else "Presencial",
                "url": url,
                "fuente": "Meetup",
                "organizador": grupo,
                "descripcion": desc,
                "gratis": True if re.search(r"\b(gratis|gratuit[oa]|free)\b", norm(desc)) else None,
                "imagen": "",
                "inscripcion": url,
                "fuente_url": url_cal,
            }
    if errores and len(errores) == len(GRUPOS_MEETUP):
        raise RuntimeError("todos los grupos fallaron: " + "; ".join(errores)[:120])
    return list(out.values())


AREAS_PUCP = {
    "Ciencias e Ingeniería": "Ingeniería y operaciones", "Investigación": "Investigación y ciencia",
    "Negocios y Empresa": "Negocios y emprendimiento", "Innovación": "Negocios y emprendimiento",
    "Internacional": "Idiomas, becas e internacional",
}
TIPOS_FUERA_PUCP = {"Cine", "Concierto", "Exposición", "Teatro", "Danza", "Misa", "Feria gastronómica",
                    "Deporte", "Actividad deportiva", "Festival"}


def pucp(limite):
    """Agenda oficial PUCP (sitio Gatsby: los eventos vienen en page-data.json)."""
    r = get("https://agenda.pucp.edu.pe/page-data/index/page-data.json", timeout=25)
    r.raise_for_status()
    ahora = datetime.now(LIMA)
    out = []
    for edge in r.json()["result"]["data"]["allApiExternaEventosNext"]["edges"]:
        n = edge["node"]
        tipo = (n.get("tipo_evento") or {}).get("Nombre", "")
        if tipo in TIPOS_FUERA_PUCP:
            continue
        # Próxima ocurrencia: días específicos (Fecha + hora local) o rangos cortos.
        # Rangos largos (exposiciones, podcasts de meses) no son "un evento al que ir".
        ocurrencias = []
        for f in n.get("Fechas") or []:
            if f.get("_xcomponent") == "frecuencia.dia-especifico" and f.get("Fecha"):
                ini = _parse(f"{f['Fecha']}T{(f.get('Inicio') or '00:00')[:5]}")
                fin = _parse(f"{f['Fecha']}T{(f.get('Fin') or '23:59')[:5]}")
            elif f.get("_xcomponent") == "frecuencia.rango":
                ini, fin = _parse(f.get("Inicio")), _parse(f.get("Fin"))
                if not ini or not fin or fin - ini > timedelta(days=10):
                    continue
            else:
                continue
            if ini and (fin or ini) >= ahora:
                ocurrencias.append((ini, fin))
        if not ocurrencias:
            continue
        ini, fin = min(ocurrencias)
        lugares = [l.get("Ubicacion") or (l.get("agenda_master_lugar_pucp") or {}).get("Nombre")
                   for l in n.get("Lugar") or []]
        areas = [a.get("Nombre", "") for a in n.get("area_tematicas") or []]
        etiquetas = [e.get("Nombre", "") for e in n.get("agenda_master_etiquetas") or []]
        virtual = any("virtual" in norm(x or "") or "zoom" in norm(x or "") for x in lugares)
        out.append({
            "id": "pucp:" + n["slug"],
            "titulo": n["Titulo"].strip(),
            "inicio": _iso(ini), "fin": _iso(fin),
            "lugar": ", ".join(dict.fromkeys(x for x in lugares if x)) or "PUCP",
            "distrito": "San Miguel",
            "modalidad": "Virtual" if virtual else "Presencial",
            "url": "https://agenda.pucp.edu.pe/evento/" + n["slug"] + "/",
            "fuente": "PUCP",
            "organizador": "PUCP",
            "descripcion": f"{tipo} · " + " · ".join(areas + etiquetas),
            "etiquetas": [tipo] + areas + etiquetas,
            "cats_fuente": list(dict.fromkeys(AREAS_PUCP[a] for a in areas if a in AREAS_PUCP)),
            "gratis": None,
            "imagen": ("https://api-agenda.pucp.edu.pe" + ((n.get("ImagenDestacada") or {}).get("url") or ""))
                      if (n.get("ImagenDestacada") or {}).get("url") else "",
            "inscripcion": "https://agenda.pucp.edu.pe/evento/" + n["slug"] + "/",
            "fuente_url": "https://agenda.pucp.edu.pe/",
            "_pucp_slug": n["slug"],
        })
    return out


def _texto_prosemirror(nodo):
    if isinstance(nodo, dict):
        if nodo.get("type") == "text":
            return nodo.get("text", "")
        sep = "\n" if nodo.get("type") in ("paragraph", "heading", "list_item", "bullet_list") else ""
        return "".join(_texto_prosemirror(h) for h in nodo.get("content") or []) + sep
    return ""


def _html_a_texto(h):
    h = re.sub(r"</(p|li|h\d)>|<br\s*/?>", "\n", h or "")
    return html.unescape(re.sub(r"<[^>]+>", "", h)).strip()


def enriquecer(ev):
    """Descripción completa, organizador, costo y link de inscripción real (1 request por evento)."""
    try:
        if ev.get("_luma_id"):
            j = get("https://api.lu.ma/event/get", params={"event_api_id": ev["_luma_id"]},
                    timeout=20).json()
            desc = _texto_prosemirror(j.get("description_mirror") or {}).strip()
            if desc:
                ev["descripcion"] = desc
            hosts = [h.get("name") for h in j.get("hosts") or [] if h.get("name")]
            cal = (j.get("calendar") or {}).get("name")
            ev["organizador"] = cal if cal and cal != "Personal" else ", ".join(hosts[:2])
            t = j.get("ticket_info") or {}
            if t.get("is_free") is not None:
                ev["gratis"] = bool(t["is_free"])
        elif ev.get("_pucp_slug"):
            j = get(f"https://agenda.pucp.edu.pe/page-data/evento/{ev['_pucp_slug']}/page-data.json",
                    timeout=20).json()
            e = j["result"]["pageContext"]["resultData"]["evento"]
            desc = _html_a_texto(e.get("Descripcion"))
            if desc:
                ev["descripcion"] = desc
            costo = e.get("Costo") or ""
            ev["gratis"] = True if costo.startswith("Gratuito") else (False if costo else None)
            link = (e.get("LinkInscripcion") or "").strip()
            if link.startswith("http"):
                ev["inscripcion"] = link
    except Exception:
        pass  # sin detalle igual sirve: queda lo del listado
    return ev


def manuales(limite):
    """Eventos vistos en redes sociales (Instagram, LinkedIn...) que se agregan a mano en
    manuales.json. Esas redes exigen login y prohíben el scraping, así que no se leen solas."""
    ruta = RAIZ / "manuales.json"
    if not ruta.exists():
        return []
    out = []
    for i, m in enumerate(json.loads(ruta.read_text(encoding="utf-8")).get("eventos", [])):
        red = m.get("red") or "Redes"
        out.append({
            "id": f"manual:{i}:{norm(m['titulo'])[:30]}",
            "titulo": m["titulo"].strip(),
            "inicio": _iso(_parse(m["inicio"])), "fin": _iso(_parse(m.get("fin"))),
            "lugar": m.get("lugar", ""), "distrito": m.get("distrito", ""),
            "modalidad": m.get("modalidad", "Presencial"),
            "url": m["url"], "inscripcion": m.get("inscripcion") or m["url"],
            "fuente": red, "fuente_url": m["url"],
            "organizador": m.get("organizador", ""),
            "descripcion": m.get("descripcion", ""),
            "gratis": m.get("gratis"),
            "imagen": m.get("imagen", ""),
            "cats_fuente": m.get("categorias") or ["Habilidades y liderazgo"],
            "_manual": True,
        })
    return out


FUENTES = {"Luma": luma, "Eventbrite": eventbrite, "Meetup": meetup, "PUCP": pucp, "Redes (manual)": manuales}


# ---------------------------------------------------------------- pipeline
def recolectar(dias):
    ahora = datetime.now(LIMA)
    limite = ahora + timedelta(days=dias)
    crudos, estado = [], {}
    for nombre, f in FUENTES.items():
        try:
            lote = f(limite)
            crudos += lote
            # 0 resultados en una fuente automática = casi siempre bloqueo (p. ej. Eventbrite
            # ante IPs de GitHub): se trata como caída para conservar sus eventos previos.
            if not lote and nombre != "Redes (manual)":
                raise RuntimeError("0 resultados (posible bloqueo)")
            estado[nombre] = {"ok": True, "n": len(lote)}
        except Exception as e:  # una fuente caída no tumba el radar
            estado[nombre] = {"ok": False, "n": 0, "error": str(e)[:160]}
    vistos, eventos = set(), []
    for ev in crudos:
        ini = _parse(ev["inicio"])
        fin = _parse(ev["fin"]) or ini
        if not ini or fin < ahora or ini > limite or not ev["titulo"]:
            continue
        clave = (re.sub(r"[^a-z0-9]", "", norm(ev["titulo"]))[:40], ev["inicio"][:10])
        if clave in vistos:
            continue
        cats, puntos = clasificar(ev)
        if not cats and ev.get("_manual"):
            cats, puntos = ev["cats_fuente"], clasificar(dict(ev, cats_fuente=["_"]))[1]
        if not cats:
            continue
        vistos.add(clave)
        ev["categorias"], ev["puntaje"] = cats, puntos
        ev.pop("etiquetas", None)
        ev.pop("cats_fuente", None)
        eventos.append(ev)
    with ThreadPoolExecutor(8) as pool:
        eventos = list(pool.map(enriquecer, eventos))
    for ev in eventos:
        ev["descripcion"] = re.sub(r"[*_#`\\]+", "", ev["descripcion"])
        ev["descripcion"] = re.sub(r"\n{3,}", "\n\n", ev["descripcion"]).strip()[:700]
        for k in [k for k in ev if k.startswith("_")]:
            ev.pop(k)
    eventos.sort(key=lambda e: e["inicio"])
    return eventos, estado, len(crudos)


def guardar(eventos, estado, total):
    previo = {}
    try:
        previo = json.loads(DATOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    primera_vez = previo.get("primera_vez") or {}
    ahora = datetime.now(LIMA).isoformat(timespec="minutes")
    # Si una fuente falló en esta corrida (bloqueo, timeout), conserva sus eventos
    # anteriores que sigan vigentes en vez de hacerlos desaparecer de la página.
    caidas = {k for k, v in estado.items() if not v["ok"]}
    if caidas:
        ids = {e["id"] for e in eventos}
        eventos += [e for e in previo.get("eventos", []) if e["fuente"] in caidas
                    and e["id"] not in ids and e["inicio"] >= ahora[:10]]
        eventos.sort(key=lambda e: e["inicio"])
    for ev in eventos:
        primera_vez.setdefault(ev["id"], ahora)
        ev["visto_desde"] = primera_vez[ev["id"]]
    # olvida ids viejos para que el archivo no crezca sin fin
    vivos = {e["id"] for e in eventos}
    primera_vez = {k: v for k, v in primera_vez.items() if k in vivos}
    datos = {"actualizado": ahora, "fuentes": estado, "revisados": total,
             "eventos": eventos, "primera_vez": primera_vez}
    DATOS.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return datos


def _ics_texto(s):
    return re.sub(r"([,;\\])", r"\\\1", s or "").replace("\n", "\\n")


def generar_ics(eventos, nombre, ruta):
    """Feed iCalendar: suscribible desde Google Calendar (se actualiza solo)."""
    utc = lambda iso: _parse(iso).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//radar-eventos-lima//ES",
              "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{nombre}",
              "X-WR-TIMEZONE:America/Lima", "REFRESH-INTERVAL;VALUE=DURATION:PT3H",
              "X-PUBLISHED-TTL:PT3H"]
    for e in eventos:
        fin = e["fin"] or _iso(_parse(e["inicio"]) + timedelta(hours=2))
        lineas += ["BEGIN:VEVENT", f"UID:{re.sub(r'[^A-Za-z0-9:_-]', '', e['id'])}@radar-eventos-lima",
                   f"DTSTAMP:{sello}", f"DTSTART:{utc(e['inicio'])}", f"DTEND:{utc(fin)}",
                   f"SUMMARY:{_ics_texto(e['titulo'])}",
                   f"LOCATION:{_ics_texto(e['lugar'] or e['modalidad'])}",
                   f"DESCRIPTION:{_ics_texto(' · '.join(e['categorias']) + chr(10) + e['url'])}",
                   f"URL:{e['url']}", "END:VEVENT"]
    lineas.append("END:VCALENDAR")
    # RFC 5545: líneas de máx. 75 octetos, continuación con espacio
    out = []
    for l in lineas:
        b = l.encode("utf-8")
        while len(b) > 75:
            corte = 75
            while (b[corte] & 0xC0) == 0x80:  # no partir un carácter UTF-8
                corte -= 1
            out.append(b[:corte].decode("utf-8")); b = b" " + b[corte:]
        out.append(b.decode("utf-8"))
    ruta.write_text("\r\n".join(out) + "\r\n", encoding="utf-8", newline="")


def generar_html(datos):
    CARPETA.mkdir(exist_ok=True)
    plantilla = (RAIZ / "plantilla.html").read_text(encoding="utf-8")
    publico = {k: v for k, v in datos.items() if k != "primera_vez"}
    js = json.dumps(publico, ensure_ascii=False).replace("</", "<\\/")
    PAGINA.write_text(plantilla.replace("/*__DATOS__*/null", js), encoding="utf-8")
    generar_ics(datos["eventos"], "Radar Lima · todos", CARPETA / "eventos.ics")
    generar_ics([e for e in datos["eventos"] if e["puntaje"] >= TOP],
                "Radar Lima · Top para ti", CARPETA / "top.ics")
    (CARPETA / "eventos.json").write_text(js, encoding="utf-8")
    return PAGINA


def main():
    ap = argparse.ArgumentParser(description="Radar de eventos formativos en Lima")
    ap.add_argument("--dias", type=int, default=60)
    ap.add_argument("--abrir", action="store_true")
    ap.add_argument("--solo-html", action="store_true")
    a = ap.parse_args()
    if a.solo_html:
        datos = json.loads(DATOS.read_text(encoding="utf-8"))
    else:
        eventos, estado, total = recolectar(a.dias)
        datos = guardar(eventos, estado, total)
        fuentes = ", ".join(f"{k} {v['n']}" + ("" if v["ok"] else " (FALLÓ)") for k, v in estado.items())
        print(f"[radar] {len(datos['eventos'])} eventos que suman (de {total} revisados) · {fuentes}")
    ruta = generar_html(datos)
    print(ruta)
    if a.abrir:
        import webbrowser
        webbrowser.open(ruta.as_uri())


if __name__ == "__main__":
    main()
