"""eventos.py — Radar Lima: eventos en Lima y convocatorias que SUMAN (no conciertos ni fiestas).

Recolecta de Luma, Eventbrite, Meetup (iCal por grupo), PUCP y, desde fuentes_extra.py, Devpost
(hackathons), WikiCFP (calls for papers), Opportunity Desk (becas y programas), Opportunities for
Youth (voluntariado) y TEDx. Todas públicas, sin login y respetando robots.txt.
Clasifica por categoría (Tecnología/IA, Datos, Ingeniería y operaciones, Negocios, Investigación,
Habilidades, Idiomas y becas, Competencias, Voluntariado) y puntúa según el perfil de JP.
NADA SE DESCARTA: lo que no pasa el filtro (recreativo, vencido, fuera del Perú…) va al Archivo
de la página con su motivo. Genera:
  eventos.json      datos normalizados + Archivo + historial de "vistos"
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
import os
import re
import secrets
import shutil
import unicodedata
from threading import Lock
from urllib import robotparser
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import fuentes_extra
import inscripciones
import institucionales
import puntaje
import verificar

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
FORMATO = r"\b(taller|workshop|conferencia|charla|seminario|meetup|summit|cumbre|congreso|foro|panel|" \
          r"conversatorio|bootcamp|curso|clase modelo|masterclass|webinar|simposio|keynote|hackathon|feria|" \
          r"jornada|open lab|kickoff|tech week|fest|expo|encuentro|convencion)\b"
# Lo que NO suma como estudiante: ocio, venta, espiritualidad, fiestas (va al Archivo, no se borra).
EXCLUIR = r"\b(concierto|fiesta|party|dj|rave|reggaeton|salsa|karaoke|stand ?up|comedia|" \
          r"closet sale|bazar|mercadillo|feria gastronomica|degustacion|cata|wine|cerveza|beer|" \
          r"brunch|dinner|cena|coctel\w*|cocktail|drinks|happy hour|cocina|chef|amigurumi\w*|crochet|manualidades|padel|running|carrera \d+k|\d+k\b|" \
          r"maraton|yoga|meditacion|reiki|tarot|astrolog\w+|constelaciones|sanacion|energia cuantica|" \
          r"retiro espiritual|culto|misa|iglesia|oracion|glow up|belleza|maquillaje|skincare|" \
          r"botanicals|cashflow|trading de|forex|cripto ?trading|multinivel|halloween|pijamada|" \
          r"kawaii|cosplay|anime|drag|speed ?dating|citas|singles|lanzamiento de|pop ?up|" \
          r"recorrido|tour|exposicion de arte|galeria|teatro|cine|danza|baile|esgrima)\b"
# Afinidad personal: perfil.json (editable). Sin ese archivo, solo cuenta el valor general.
PERFIL_JSON = RAIZ / "perfil.json"
INSTITUCIONALES_JSON = RAIZ / "institucionales.json"
RECURRENTES_JSON = RAIZ / "recurrentes.json"  # eventos anuales verificados → "Se viene"
TOP = 55           # puntaje (0-100) desde el que algo es "Destacado" (valor general + afinidad del perfil)
VIRTUAL_TITULO = r"\b(webinar|webinars|online|virtual|en linea|via zoom|por zoom)\b"
TOP_SIN_PERFIL = 40  # sin perfil.json solo hay valor general (0-60): "Destacado" desde 40


def motivo_recreativo(ev):
    """El título manda para excluir: una charla de IA que menciona "coffee break" no se archiva."""
    m = re.search(EXCLUIR, norm(ev["titulo"]))
    return f"recreativo o de venta ({m.group(0)})" if m else None


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
            fuera = g.get("country_code") not in (None, "PE")
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
                "_motivo": f"fuera del Perú ({g.get('country') or g.get('country_code')})" if fuera else None,
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


# Eventos VIRTUALES: lo online no tiene ciudad, así que se busca por tema. Solo gratis y en español (la propia
# API filtra), y solo lo que toca un área formativa: sin eso entrarían miles de webinars de ventas o de trámites
# de otros países. Lo que no pasa este filtro no se recolecta (no llega a la lista ni al Archivo).
EB_ONLINE_Q = ("taller", "webinar", "charla", "conferencia", "seminario", "tecnologia", "inteligencia artificial",
               "datos", "python", "excel", "emprendimiento", "liderazgo", "logistica", "ingenieria", "programacion",
               "investigacion", "empleabilidad")
MAX_ONLINE = 80
DIAS_ONLINE = 45
# Lo online de otros países que no le sirve a un estudiante de Lima: dinero milagroso, trámites locales, networking
# por zonas de España, coaching de venta. (Se revisó una muestra real de 80 antes de fijar esta lista.)
EB_ONLINE_FUERA = (r"\b(trading|forex|cripto\w*|bitcoin|deudas?|rentas?|libertad financiera|ingresos pasivos|"
                   r"inversion inmobiliaria|multinivel|fiscal\w*|impuestos|deducciones|migra\w*|visa|green card|"
                   r"hipoteca|seguro social|zona (albacete|valencia|malaga|madrid|barcelona|sevilla)|"
                   r"especializacion en coaching|riesgo suicida|pool de|new york|nyc|ciudad de ny|condado|quickbooks|"
                   r"small business|padres|familias|crianza|defensa de la vida|iglesia|dropshipping|cannab\w*|"
                   r"viajes desde casa|tu dinero|publica tu libro|buen fin)\b")
MIN_VALOR_ONLINE = 22  # valor general mínimo (0-60) para que un online entre: formativo de verdad, no solo "networking"
# Temas que valen aunque el organizador no sea latinoamericano (con horario razonable en Lima).
EB_ONLINE_TEMAS_GLOBALES = {"Tecnología e IA", "Datos y analítica", "Ingeniería y operaciones", "Investigación y ciencia"}


ZONAS_LATAM = re.compile(r"America/(Lima|Bogota|Mexico_City|Monterrey|Merida|Cancun|Chihuahua|Hermosillo|Mazatlan|"
                         r"Argentina/.+|Buenos_Aires|Santiago|Montevideo|Asuncion|La_Paz|Guayaquil|Caracas|Panama|"
                         r"Costa_Rica|El_Salvador|Guatemala|Tegucigalpa|Managua|Santo_Domingo|Puerto_Rico|Havana)$")
ORG_ACADEMICO = r"\b(universidad|university|business school|escuela de (negocios|posgrado)|instituto|academia|colegio de)\b"
FORMATO_CLASE = r"\b(webinar|taller|masterclass|master class|charla|conferencia|curso|seminario|bootcamp|workshop|open lab)\b"
ORG_FUERA = r"\b(nyc|new york|sbdc|small business|realt\w*|decrypto)\b"


def _online_util(ev, zona, ini, ahora):
    """¿Le sirve a un estudiante de Lima? Tech, datos, ingeniería o investigación de cualquier lugar; lo organizado
    por universidades; y negocios o habilidades solo de Latinoamérica y con formato de clase. Hora razonable en
    Lima y que no haya empezado hace tiempo (eso suele ser un curso pagado en curso)."""
    if not 7 <= ini.hour <= 22 or ini < ahora - timedelta(days=1):
        return False
    texto = norm(ev["titulo"] + " " + ev["descripcion"][:300])
    org = norm(ev.get("organizador", ""))
    if motivo_recreativo(ev) or re.search(EB_ONLINE_FUERA, texto) or re.search(ORG_FUERA, org):
        return False
    cats, coincidencias = puntaje.categorias(ev)
    if not coincidencias:
        return False
    if set(cats) & EB_ONLINE_TEMAS_GLOBALES or re.search(ORG_ACADEMICO, org):
        return True
    return bool(ZONAS_LATAM.match(zona or "")) and bool(re.search(FORMATO_CLASE, norm(ev["titulo"])))


def _hora_lima(fecha, hora, zona):
    """'2026-10-01', '15:30', 'Atlantic/Canary' → datetime en hora de Lima (los online vienen en la hora del organizador)."""
    if not fecha:
        return None
    try:
        tz = ZoneInfo(zona) if zona else LIMA
    except Exception:
        tz = LIMA
    try:
        return datetime.fromisoformat(f"{fecha}T{hora or '00:00'}").replace(tzinfo=tz).astimezone(LIMA)
    except ValueError:
        return None


def eventbrite_online(limite, post=None):
    """Eventos ONLINE de Eventbrite: gratis, en español y de temas formativos; hora convertida a la de Lima."""
    post = post or requests.post
    tok = secrets.token_hex(16)
    cab = {**UA, "Content-Type": "application/json", "X-CSRFToken": tok,
           "Referer": "https://www.eventbrite.com.pe/d/online/all-events/"}
    if not permitido(EB_API):
        raise PermissionError(f"robots.txt no permite {EB_API}")
    ahora = datetime.now(LIMA)
    tope = min(limite, ahora + timedelta(days=DIAS_ONLINE))
    out, diag = {}, set()
    for q in EB_ONLINE_Q:
        cuerpo = {"event_search": {"online_events_only": True, "price": "free", "languages": ["es"],
                                   "dates": "current_future", "dedup": True, "page": 1, "page_size": 50, "q": q},
                  "browse_surface": "search",
                  "expand.destination_event": ["image", "ticket_availability", "primary_organizer"]}
        r = post(EB_API, headers=cab, cookies={"csrftoken": tok}, data=json.dumps(cuerpo), timeout=25)
        diag.add(str(r.status_code))
        if not r.ok:
            continue
        for e in (r.json().get("events") or {}).get("results") or []:
            clave = str(e.get("id"))
            if clave in out or e.get("is_cancelled") or not e.get("is_online_event"):
                continue
            ini = _hora_lima(e.get("start_date"), e.get("start_time"), e.get("timezone"))
            if not ini or ini > tope:
                continue
            ev = {
                "id": "eb:" + clave,
                "titulo": (e.get("name") or "").strip(),
                "inicio": _iso(ini), "fin": _iso(_hora_lima(e.get("end_date"), e.get("end_time"), e.get("timezone"))),
                "lugar": "", "distrito": "", "modalidad": "Virtual",
                "url": e.get("url", ""), "inscripcion": e.get("url", ""),
                "fuente": "Eventbrite online", "fuente_url": "https://www.eventbrite.com.pe/d/online/all-events/",
                "organizador": (e.get("primary_organizer") or {}).get("name", "") or "",
                "descripcion": e.get("summary") or "",
                "etiquetas": [x.get("display_name", "") for x in e.get("tags") or []],
                "gratis": True if (e.get("ticket_availability") or {}).get("is_free", True) else None,
                "imagen": (e.get("image") or {}).get("url", ""),
            }
            if not _online_util(ev, e.get("timezone"), ini, ahora):
                continue  # fuera de alcance: no se recolecta (ni lista ni Archivo)
            out[clave] = ev
    if not out:
        raise RuntimeError("0 resultados: HTTP " + ",".join(sorted(diag)))
    # se quedan los de más valor formativo (no los primeros por fecha), y se devuelven en orden de fecha
    valor = {k: puntaje.valor_general(e)[0] for k, e in out.items()}
    mejores = sorted((k for k in out if valor[k] >= MIN_VALOR_ONLINE), key=lambda k: -valor[k])[:MAX_ONLINE]
    return sorted((out[k] for k in mejores), key=lambda x: x["inicio"])


def _local(texto):
    t = f" {norm(texto)} "
    if re.search(r"\b(peru|lima|pucp|uni|upc|utec|san marcos)\b", t):
        return True
    return sum(t.count(w) for w in (" de ", " la ", " para ", " con ", " el ", " y ", " en ")) >= 3


# Meetup prohíbe en robots.txt su buscador (/find/), pero permite el iCal de cada grupo:
# se siguen los grupos de Lima que publican cosas que suman.
GRUPOS_MEETUP = ["awsperu", "aws-sbg-at-national-university-of-engineering",
                 "aws-sbg-at-technological-university-of-peru", "bi-expert", "msperu",
                 "speak-up-conversation-club", "practice-english-saturday", "lince-english-group",
                 # comunidades tech de Lima (2026-09-27: sin eventos próximos, pero se vigilan por si vuelven a publicar)
                 "grupos-de-usuarios-de-python-en-lima-peru", "Machine-Learning-Peru", "pythonperu",
                 "Data-Science-Lima", "wia-lima-peru", "perutech", "women-techmakers-lima"]
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
            # un online solo va a la lista si está en español o cita Perú; si no, al Archivo
            fuera = online and not _local(titulo + " " + desc[:400])
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
                "_motivo": "virtual en otro idioma y sin relación con el Perú" if fuera else None,
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
            "_motivo": f"tipo de evento no formativo ({tipo})" if tipo in TIPOS_FUERA_PUCP else None,
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


# IEEE vTools: ahí publican sus eventos las ramas estudiantiles IEEE (UNI, San Marcos, PUCP, UPC, Callao…).
# API pública permitida por robots.txt, que pide 60 s entre peticiones y no filtra por país: se hace UNA consulta
# (~1000 eventos del mundo, ~5 MB) como máximo una vez al día, y se guarda solo lo de la Sección Perú.
VTOOLS_API = "https://events.vtools.ieee.org/RST/events/api/public/v5/events/list?span=now~&limit=1000"
SECCION_PERU = "R90721"
CACHE_VTOOLS = RAIZ / "cache" / "vtools_peru.json"
VTOOLS_INTERNO = r"\b(excom|officer|meeting ?#|reunion (de )?(junta|directiva|interna)|asamblea)\b"


def _ieee_evento(a):
    h = a.get("primary-host") or {}
    ini = _parse((a.get("start-time") or "").replace(".000Z", "Z"))
    fin = _parse((a.get("end-time") or "").replace(".000Z", "Z"))
    virtual = bool(a.get("virtual")) or a.get("location-type") == "virtual"
    lugar = ", ".join(x for x in (a.get("building"), a.get("room-number"), a.get("address1")) if x)
    costo = str(a.get("cost") or "").strip()
    link = a.get("link") or f"https://events.vtools.ieee.org/m/{a.get('id')}"
    return {
        "id": f"ieee:{a.get('id')}",
        "titulo": (a.get("title") or "").strip(),
        "inicio": _iso(ini), "fin": _iso(fin),
        "lugar": "" if virtual else lugar, "distrito": "" if virtual else (a.get("city") or ""),
        "modalidad": "Virtual" if virtual else "Presencial",
        "url": link, "inscripcion": a.get("registration-url") or link,
        "fuente": "IEEE Perú", "fuente_url": "https://events.vtools.ieee.org/",
        "organizador": "IEEE · " + (h.get("name") or "Sección Perú"),
        "descripcion": _html_a_texto(a.get("description") or "")[:1500],
        "gratis": True if costo in ("", "0", "0.0", "0.00", "None") else None,
        "imagen": a.get("image") or "",
        "cats_fuente": ["Tecnología e IA", "Ingeniería y operaciones"],
    }


def ieee_peru(limite, get_=None, ahora=None):
    """Eventos de la Sección Perú de IEEE (ramas estudiantiles), con la consulta del día guardada en cache/."""
    ahora = ahora or datetime.now(LIMA)
    try:
        guardado = json.loads(CACHE_VTOOLS.read_text(encoding="utf-8"))
        vigente = ahora - _parse(guardado["fecha"]) < timedelta(hours=20)
    except (OSError, ValueError, KeyError, TypeError):
        guardado, vigente = None, False
    if vigente:
        crudos = guardado["eventos"]
    else:
        r = (get_ or get)(VTOOLS_API, timeout=150)
        r.raise_for_status()
        datos = r.json()
        datos = datos.get("data", datos) if isinstance(datos, dict) else datos
        crudos = [d.get("attributes", d) for d in datos
                  if str(((d.get("attributes", d)).get("primary-host") or {}).get("section_spoids")) == SECCION_PERU]
        CACHE_VTOOLS.parent.mkdir(exist_ok=True)
        CACHE_VTOOLS.write_text(json.dumps({"fecha": _iso(ahora), "eventos": crudos}, ensure_ascii=False), encoding="utf-8")
    out = []
    for a in crudos:
        if a.get("cancelled") or re.search(VTOOLS_INTERNO, norm(a.get("title") or "")):
            continue
        ev = _ieee_evento(a)
        if ev["inicio"] and _parse(ev["inicio"]) <= limite:
            out.append(ev)
    return out


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


FUENTES = {"Luma": luma, "Eventbrite": eventbrite, "Eventbrite online": eventbrite_online, "Meetup": meetup, "PUCP": pucp, "IEEE Perú": lambda lim: ieee_peru(lim),
           **fuentes_extra.fuentes(get), "Institucionales": lambda lim: _institucionales(lim),
           "Inscripciones (Linktree)": lambda lim: _inscripciones(lim),
           "Redes (manual)": manuales}
INSCRIPCIONES_JSON = RAIZ / "inscripciones.json"


def _inscripciones(limite):
    # Linktree no se recorre (prohíbe robots): se leen los destinos de los enlaces que JARVIS copió de él.
    # Lo que no se puede leer queda en inscripciones.POR_CONFIRMAR para la sección "Por confirmar".
    return inscripciones.recolectar(get, permitido, INSCRIPCIONES_JSON)[0] if INSCRIPCIONES_JSON.exists() else []
_ESTADO_INST = {}


def _institucionales(limite):
    # Las cumbres y ferias se anuncian con meses de anticipación: horizonte largo, como las convocatorias.
    lote, estado = institucionales.recolectar(get, INSTITUCIONALES_JSON,
                                              datetime.now(LIMA) + timedelta(days=DIAS_CONVOCATORIAS))
    _ESTADO_INST.clear()
    _ESTADO_INST.update(estado)
    if estado and all(isinstance(v, str) for v in estado.values()):
        raise RuntimeError("todas las páginas institucionales fallaron")
    return lote
# Convocatorias, becas y calls for papers se anuncian con meses de anticipación: horizonte más largo.
TIPOS_CON_PLAZO = {"convocatoria", "voluntariado"}
DIAS_CONVOCATORIAS = 365


# ---------------------------------------------------------------- pipeline
def _limpiar_desc(ev, largo):
    ev["descripcion"] = re.sub(r"[*_#`\\]+", "", ev.get("descripcion") or "")
    ev["descripcion"] = re.sub(r"\n{3,}", "\n\n", ev["descripcion"]).strip()[:largo]
    for k in [k for k in ev if k.startswith("_") or k in ("etiquetas", "cats_fuente")]:
        ev.pop(k)
    return ev


def recolectar(dias, perfil=None):
    """Devuelve (eventos, archivo, estado, revisados). Nada se descarta: lo que no pasa el filtro
    va al archivo con su `motivo`. Solo quedan fuera los duplicados (ya están una vez) y lo que
    todavía está más allá del horizonte (aparecerá cuando se acerque)."""
    ahora = datetime.now(LIMA)
    limite = ahora + timedelta(days=dias)
    limite_largo = ahora + timedelta(days=max(dias, DIAS_CONVOCATORIAS))
    crudos, estado = [], {}
    for nombre, f in FUENTES.items():
        try:
            antes = set(fuentes_extra.CACHE_USADO)
            lote = f(limite)
            crudos += lote
            # 0 resultados en una fuente automática = casi siempre bloqueo (p. ej. Eventbrite
            # ante IPs de GitHub): se trata como caída para conservar sus eventos previos.
            if not lote and nombre not in ("Redes (manual)", "Institucionales", "Inscripciones (Linktree)", "IEEE Perú"):
                raise RuntimeError("0 resultados (posible bloqueo)")
            estado[nombre] = {"ok": True, "n": len(lote)}
            copias = [v for k, v in fuentes_extra.CACHE_USADO.items() if k not in antes]
            if copias:  # respondió con error (p. ej. 429) y se usó la última respuesta buena
                estado[nombre]["cache"] = min(copias)
        except Exception as e:  # una fuente caída no tumba el radar
            estado[nombre] = {"ok": False, "n": 0, "error": str(e)[:160]}
    vistos, candidatos, archivo = set(), [], []
    for ev in crudos:
        if not ev.get("titulo"):
            continue
        tipo = ev.setdefault("tipo", "evento")
        ev.setdefault("cierre", "")
        ini = _parse(ev["inicio"])
        fin = _parse(ev["fin"]) or ini
        cierre = _parse(ev["cierre"])
        clave = (re.sub(r"[^a-z0-9]", "", norm(ev["titulo"]))[:40], ev["inicio"][:10])
        if clave in vistos:
            continue
        motivo = ev.get("_motivo")
        if not motivo and tipo not in TIPOS_CON_PLAZO:
            if not ini:
                motivo = "sin fecha"
            elif fin < ahora:
                motivo = "ya pasó"
        # Más allá del horizonte todavía no toca mostrarlo (no es un descarte: aparecerá luego).
        referencia = cierre if tipo in TIPOS_CON_PLAZO else ini
        tope = limite if tipo == "evento" and not ev.get("institucional") else limite_largo
        if not motivo and referencia and referencia > tope:
            continue
        vistos.add(clave)
        ev["motivo"] = motivo or motivo_recreativo(ev)
        (archivo if ev["motivo"] else candidatos).append(ev)
    # detalle completo (descripción, precio real) solo de lo que puede ir a la lista
    with ThreadPoolExecutor(8) as pool:
        candidatos = list(pool.map(enriquecer, candidatos))
    eventos = []
    for ev in candidatos:
        ev["gratis"] = puntaje.es_gratis(ev)  # el precio en el texto gana a la bandera de la fuente
        if re.search(VIRTUAL_TITULO, norm(ev["titulo"])):
            ev["modalidad"] = "Virtual"  # caso: un webinar de ISO 21001 figuraba presencial
        if re.search(puntaje.PROMO_PROGRAMA, norm(ev["titulo"])):
            # "Conferencia informativa" de una maestría o diplomado: es admisión, no una oportunidad de crecer
            ev["tipo"], ev["institucional"] = "admisión", False
            ev["motivo"] = "admisión: promociona una maestría o diplomado pagado"
            archivo.append(ev)
            continue
        cats, coincidencias = puntaje.categorias(ev)
        if ev.get("_manual") and not cats:
            cats = ev["cats_fuente"]
        ev["categorias"] = cats
        puntaje.puntuar(ev, perfil)
        if not cats or (not coincidencias and not ev.get("cats_fuente") and not re.search(FORMATO, norm(
                ev["titulo"] + " " + ev.get("descripcion", "")))):
            ev["motivo"] = "no encaja en ningún área formativa"
        elif ev["tipo"] in TIPOS_CON_PLAZO and not coincidencias and not ev.get("afinidad"):
            ev["motivo"] = "sin afinidad"  # la convocatoria no toca ninguna área (ni del perfil)
        (archivo if ev.get("motivo") else eventos).append(ev)
    for ev in archivo:  # el archivo también muestra categoría y puntaje (sin pedir el detalle)
        if "puntaje" not in ev:
            ev["gratis"] = puntaje.es_gratis(ev)
            ev["categorias"] = puntaje.categorias(ev)[0]
            puntaje.puntuar(ev, perfil)
    eventos = [_limpiar_desc(ev, 700) for ev in eventos]
    archivo = [_limpiar_desc(ev, 300) for ev in archivo]  # más corto: el archivo es para consultar
    for ev in eventos:
        ev.pop("motivo", None)
    eventos.sort(key=lambda e: e["cierre"] or e["inicio"])
    archivo.sort(key=lambda e: (e["motivo"], e["inicio"]))
    return eventos, archivo, estado, len(crudos)


def _vigente(e, hoy):
    if e.get("tipo") in TIPOS_CON_PLAZO and not e.get("cierre"):
        # sin fecha límite: se conserva mientras la publicación sea reciente (misma regla que al recolectar)
        pub = _parse(e.get("publicado"))
        return bool(pub) and datetime.now(LIMA) - pub <= timedelta(days=45)
    return (e.get("cierre") or e.get("fin") or e["inicio"]) >= hoy


def guardar(eventos, archivo, estado, total, extras=None):
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
                    and e["id"] not in ids and _vigente(e, ahora[:10])]
        eventos.sort(key=lambda e: e.get("cierre") or e["inicio"])
        ids_arch = {e["id"] for e in archivo}
        archivo += [e for e in previo.get("archivo", []) if e["fuente"] in caidas and e["id"] not in ids_arch]
    for ev in eventos:
        primera_vez.setdefault(ev["id"], ahora)
        ev["visto_desde"] = primera_vez[ev["id"]]
    # olvida ids viejos para que el archivo no crezca sin fin
    vivos = {e["id"] for e in eventos}
    primera_vez = {k: v for k, v in primera_vez.items() if k in vivos}
    # Historial de eventos institucionales por año: alimenta "Se viene" cuando un evento se repite.
    historial = previo.get("historial_institucional") or {}
    for e in eventos + archivo:
        if e.get("institucional"):
            nombre = re.sub(r"\s+20\d\d$", "", e["titulo"]).strip()
            historial.setdefault(nombre, {})[e["inicio"][:4]] = e["inicio"][:10]
    datos = {"actualizado": ahora, "fuentes": estado, "revisados": total, "top": TOP,
             "eventos": eventos, "archivo": archivo, **(extras or {}),
             "historial_institucional": historial, "primera_vez": primera_vez}
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
        titulo, ini, fin = e["titulo"], e["inicio"], e["fin"] or _iso(_parse(e["inicio"]) + timedelta(hours=2))
        if e.get("cierre"):  # convocatorias y hackathons: en el calendario va el cierre, no un bloque de semanas
            titulo, ini, fin = "Cierra: " + titulo, _iso(_parse(e["cierre"]) - timedelta(hours=1)), e["cierre"]
        elif e.get("tipo") in TIPOS_CON_PLAZO:
            continue  # sin fecha límite publicada no hay nada que agendar
        elif e.get("tipo") == "call for papers":
            titulo = "Congreso (CFP): " + titulo
        # UID con el sufijo de siempre: así los calendarios ya suscritos no duplican eventos.
        lineas += ["BEGIN:VEVENT", f"UID:{re.sub(r'[^A-Za-z0-9:_-]', '', e['id'])}@radar-eventos-lima",
                   f"DTSTAMP:{sello}", f"DTSTART:{utc(ini)}", f"DTEND:{utc(fin)}",
                   f"SUMMARY:{_ics_texto(titulo)}",
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
    publico = {k: v for k, v in datos.items() if k not in ("primera_vez", "historial_institucional")}
    js = json.dumps(publico, ensure_ascii=False).replace("</", "<\\/")
    PAGINA.write_text(plantilla.replace("/*__DATOS__*/null", js), encoding="utf-8")
    generar_ics(datos["eventos"], "Radar Lima · todo", CARPETA / "eventos.ics")
    generar_ics([e for e in datos["eventos"] if e["puntaje"] >= datos.get("top", TOP)],
                "Radar Lima · destacados", CARPETA / "top.ics")
    (CARPETA / "eventos.json").write_text(js, encoding="utf-8")
    # logo e íconos (pestaña, celular, vista previa al compartir): se generan a mano con marca/generar_marca.py
    for f in (RAIZ / "marca").iterdir():
        if f.suffix in (".svg", ".png", ".ico", ".webmanifest"):
            shutil.copyfile(f, CARPETA / f.name)
    # página del botón de Linktree (privada en la práctica: sin enlace desde el radar, noindex, y el botón exige
    # la llave de GitHub de JP guardada en su navegador)
    (CARPETA / "linktree").mkdir(exist_ok=True)
    (CARPETA / "linktree" / "index.html").write_text((RAIZ / "pagina_linktree.html").read_text(encoding="utf-8"),
                                                     encoding="utf-8")
    return PAGINA


def main():
    ap = argparse.ArgumentParser(description="Radar Lima: eventos en Lima y convocatorias que suman")
    ap.add_argument("--dias", type=int, default=60)
    ap.add_argument("--abrir", action="store_true")
    ap.add_argument("--solo-html", action="store_true")
    ap.add_argument("--perfil", default=str(PERFIL_JSON), help="perfil.json de afinidad ('' = sin perfil)")
    a = ap.parse_args()
    if a.solo_html:
        datos = json.loads(DATOS.read_text(encoding="utf-8"))
    else:
        perfil = puntaje.cargar_perfil(a.perfil) if a.perfil else None
        eventos, archivo, estado, total = recolectar(a.dias, perfil)
        ahora = datetime.now(LIMA)
        # Control de calidad de cada evento antes de publicarlo (corrige, avisa o archiva; nunca borra)
        eventos, archivo, calidad = verificar.revisar(eventos, archivo, ahora, get=get,
                                                      ruta_cache=RAIZ / "cache" / "enlaces.json",
                                                      ruta_historial=RAIZ / "cache" / "verificacion.json")
        for f in calidad["fuentes_a_revisar"]:  # el evento dice "Institucional"; la fuente, "Institucionales"
            clave = f["fuente"] if f["fuente"] in estado else next((k for k in estado if k.startswith(f["fuente"])), None)
            if clave:
                estado[clave]["revisar"] = f["detalle"]
        if os.environ.get("GITHUB_STEP_SUMMARY"):  # resumen visible en cada corrida de GitHub Actions
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as s:
                s.write(verificar.resumen_markdown(calidad))
        previo = {}
        try:
            previo = json.loads(DATOS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        extras = {
            "perfil": bool(perfil), "top": TOP if perfil else TOP_SIN_PERFIL,
            "recomendados": puntaje.recomendados(eventos, ahora),
            "institucionales": _ESTADO_INST.copy(),
            "se_viene": institucionales.se_viene(RECURRENTES_JSON, eventos),
            "calidad": calidad,
        }
        try:
            extras["por_confirmar"] = institucionales.descubrir(get, INSTITUCIONALES_JSON,
                                                                [e["titulo"] for e in eventos])
        except Exception as e:  # el descubrimiento es un extra: si falla, el radar sigue
            extras["por_confirmar"], estado["Descubrimiento"] = [], {"ok": False, "n": 0, "error": str(e)[:160]}
        # inscripciones de Linktree que no se pudieron leer solas (Microsoft Forms, formularios privados, sin fecha):
        # sección propia arriba en la página, no escondidas al final
        extras["inscripciones_abiertas"] = list(inscripciones.POR_CONFIRMAR)
        datos = guardar(eventos, archivo, estado, total, extras)
        fuentes = ", ".join(f"{k} {v['n']}" + ("" if v["ok"] else " (FALLÓ)") for k, v in estado.items())
        print(f"[radar] {len(datos['eventos'])} en la lista · {len(datos['archivo'])} en el Archivo "
              f"(de {total} revisados) · {fuentes}")
        print(f"[radar] perfil: {'sí' if perfil else 'no'} · recomendados: {len(extras['recomendados'])} · "
              f"por confirmar: {len(extras['por_confirmar'])} · se viene: {len(extras['se_viene'])}")
        en = calidad.get("enlaces") or {}
        print(f"[radar] verificación: {calidad['revisados']} revisados · {calidad['corregidos']} corregidos · "
              f"{calidad['avisos']} con aviso · {calidad['archivados']} al Archivo · "
              f"{en.get('comprobados', 0)} enlaces comprobados ({en.get('rotos', 0)} rotos)"
              + (" · REVISAR: " + ", ".join(f["fuente"] for f in calidad["fuentes_a_revisar"])
                 if calidad["fuentes_a_revisar"] else ""))
    ruta = generar_html(datos)
    print(ruta)
    if a.abrir:
        import webbrowser
        webbrowser.open(ruta.as_uri())


if __name__ == "__main__":
    main()
