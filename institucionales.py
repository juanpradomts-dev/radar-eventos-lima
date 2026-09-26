"""institucionales.py — eventos que viven en la web del organizador (cumbres, foros, congresos, ferias).

Caso que originó esto: la Cumbre Perú Sostenible (24–26 set 2026, gratuita, Lima) nunca apareció porque
no está en Luma, Eventbrite ni Meetup. Tres piezas:
  1. Lista de vigilancia (institucionales.json) + extracción genérica por página, en este orden:
     JSON-LD schema.org/Event → enlaces .ics → <time datetime> → fechas en español
     ("24, 25 y 26 de septiembre, 2026", "del 3 al 5 de octubre"). Con solo la fecha igual se publica,
     con enlace a la web oficial.
  2. Descubrimiento: Bing News RSS con "cumbre|foro|congreso|summit|feria + Lima + año" → "Por confirmar".
  3. Recurrentes anuales → "Se viene" (~2 meses antes aunque la web aún no publique fechas).
Respeta robots.txt (usa el `get` de eventos.py) y cada página falla sola.
"""
import html as htmlmod
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

LIMA = timezone(timedelta(hours=-5))
MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}
NOMBRE_MES = {v: k for k, v in MESES.items() if k != "septiembre"}
_MES = r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
_DIA = r"(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
_SEP = r"\s*(?:,|y|al|a|-|–|hasta el)\s*"
_ANIO = r"(?:\s*(?:,|de|del)?\s*(20\d\d))?"
# "del 23 de noviembre al 02 de diciembre [de 2026]"
RX_CRUZADO = re.compile(rf"\b(\d{{1,2}})\s+(?:de\s+)?{_MES}(?:\s+(?:de\s+)?(20\d\d))?\s+(?:al|a|hasta el)\s+"
                        rf"(?:{_DIA}\s+)?(\d{{1,2}})\s+(?:de\s+)?{_MES}{_ANIO}", re.I)
# "24, viernes 25 y sábado 26 de septiembre, 2026" / "25 a 26 de Septiembre 2026" / "07 de octubre 2026"
RX_MISMO_MES = re.compile(rf"\b(\d{{1,2}})((?:{_SEP}(?:{_DIA}\s+)?\d{{1,2}})*)\s+(?:de\s+)?{_MES}{_ANIO}", re.I)
EVENTO = re.compile(r"\b(cumbre|foro|congreso|summit|feria|expo\w*|convenci[oó]n|conferencia|seminario|taller|"
                    r"workshop|webinar|charla|clase modelo|conversatorio|encuentro|jornada|simposio|panel|day|"
                    r"curso|diplomado|hackat[oh]n|concurso|premio|ceremonia|festival de|semana de|bootcamp)\b", re.I)
ETIQUETA = re.compile(r"^(fecha|hora|horario|costo|precio|lugar|modalidad|inicio|duraci[oó]n|ver m[aá]s|leer m[aá]s|"
                      r"conocer m[aá]s|m[aá]s informaci[oó]n|inscr[ií]bete|registrate|reg[ií]strate|gratuito|free|"
                      r"presencial|virtual|h[ií]brido|programa|comit[eé]|auspiciadores)\b", re.I)


def _fecha(d, m, a, fin=False):
    try:
        return datetime(int(a), MESES[m.lower()], int(d), 23 if fin else 0, 59 if fin else 0, tzinfo=LIMA)
    except (ValueError, KeyError):
        return None


def fechas_es(texto, anio_defecto=None):
    """Rangos (inicio, fin, posición) en español. Sin año explícito se usa `anio_defecto` (p. ej. el año del
    título de la página); si tampoco hay, la fecha se ignora: evita tomar '5 de noviembre' de 2018 como actual."""
    out, usados = [], []
    for m in RX_CRUZADO.finditer(texto):
        a2 = m.group(6) or anio_defecto
        a1 = m.group(3) or a2
        if not a2:
            continue
        ini, fin = _fecha(m.group(1), m.group(2), a1), _fecha(m.group(4), m.group(5), a2, fin=True)
        if ini and fin and ini > fin:
            ini = ini.replace(year=ini.year - 1)
        if ini and fin:
            out.append((ini, fin, m.start()))
            usados.append((m.start(), m.end()))
    for m in RX_MISMO_MES.finditer(texto):
        if any(a <= m.start() < b for a, b in usados):
            continue
        anio = m.group(4) or anio_defecto
        if not anio:
            continue
        dias = [int(m.group(1))] + [int(x) for x in re.findall(r"\d{1,2}", m.group(2) or "")]
        if not all(1 <= d <= 31 for d in dias):
            continue
        ini, fin = _fecha(min(dias), m.group(3), anio), _fecha(max(dias), m.group(3), anio, fin=True)
        if ini and fin:
            out.append((ini, fin, m.start()))
    return sorted(out, key=lambda x: x[2])


def _bloques(html):
    """Texto visible partido en bloques (uno por nodo de texto)."""
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    out = []
    for b in re.split(r"<[^>]+>", html):
        b = re.sub(r"\s+", " ", htmlmod.unescape(b)).strip()
        if b and not re.fullmatch(r"[|·•\-–>»«]+", b):
            out.append(b)
    return out


def _meta(html, *nombres):
    for n in nombres:
        m = re.search(rf'<meta[^>]+(?:property|name)=["\']{re.escape(n)}["\'][^>]+content=["\']([^"\']+)', html, re.I) \
            or re.search(rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(n)}["\']', html, re.I)
        if m:
            return htmlmod.unescape(m.group(1)).strip()
    return ""


def _titulo_pagina(html):
    t = _meta(html, "og:title")
    if not t:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        t = htmlmod.unescape(m.group(1)).strip() if m else ""
    return t


def _anio_de(texto):
    m = re.search(r"\b(20\d\d)\b", texto or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------- 1) JSON-LD
def _eventos_jsonld(html):
    out = []

    def recorrer(n):
        if isinstance(n, list):
            for x in n:
                recorrer(x)
        elif isinstance(n, dict):
            tipos = n.get("@type")
            tipos = tipos if isinstance(tipos, list) else [tipos]
            if any(isinstance(t, str) and t.endswith("Event") for t in tipos) and n.get("startDate"):
                out.append(n)
            for k in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
                if k in n:
                    recorrer(n[k])
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            crudo = re.sub(r",\s*([}\]])", r"\1", m.group(1).strip())  # comas sobrantes (JSON inválido)
            recorrer(json.loads(crudo, strict=False))
        except ValueError:
            continue
    return out


def _parse_iso(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        # formatos rotos pero legibles: "2026-9-29T11-11-00-00", "2026-09-29 18:30"
        m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2})[:\-](\d{2}))?", str(s))
        if not m:
            return None
        try:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4) or 0), int(m.group(5) or 0))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=LIMA)


# ---------------------------------------------------------------- extracción por página
# Categorías por tipo de organizador (las páginas institucionales casi no traen descripción; la lista es curada).
CATS_ORG = {"foro": ["Negocios y emprendimiento", "Habilidades y liderazgo"],
            "feria": ["Negocios y emprendimiento", "Ingeniería y operaciones"],
            "gremio": ["Negocios y emprendimiento", "Habilidades y liderazgo"],
            "colegio profesional": ["Ingeniería y operaciones", "Habilidades y liderazgo"],
            "universidad": ["Investigación y ciencia", "Habilidades y liderazgo"],
            "ministerio": ["Investigación y ciencia", "Negocios y emprendimiento"],
            "embajada": ["Idiomas, becas e internacional"],
            "ong": ["Voluntariado e impacto social", "Habilidades y liderazgo"]}


def _item(fuente, titulo, ini, fin, url, lugar="", descripcion="", imagen="", gratis=None, via=""):
    iso = lambda d: d.astimezone(LIMA).isoformat(timespec="minutes") if d else ""
    slug = re.sub(r"[^a-z0-9]+", "-", (fuente["organizador"] + " " + titulo).lower())[:60]
    return {
        "id": f"inst:{slug}:{iso(ini)[:10]}",
        "titulo": titulo.strip()[:160], "tipo": "evento", "institucional": True,
        "escala": fuente.get("escala", "media"),
        "inicio": iso(ini), "fin": iso(fin or ini), "cierre": "",
        "lugar": lugar or fuente.get("ciudad", "Lima"), "distrito": fuente.get("ciudad", "Lima"),
        "ciudad": fuente.get("ciudad", "Lima"),
        "modalidad": "Presencial",
        "url": url, "inscripcion": url,
        "fuente": "Institucional", "fuente_url": fuente["url"],
        "organizador": fuente["organizador"],
        "descripcion": descripcion, "gratis": gratis, "imagen": imagen,
        "etiquetas": [fuente.get("tipo_org", "")], "extraido_por": via,
        "cats_fuente": fuente.get("categorias") or CATS_ORG.get(fuente.get("tipo_org"), ["Habilidades y liderazgo"]),
    }


def extraer(fuente, html, ahora, limite, get=None):
    """Eventos de UNA página según su modo. Devuelve lista de items (formato de eventos.py)."""
    base = fuente["url"]
    desc_pag = _meta(html, "og:description", "description")
    img_pag = _meta(html, "og:image")
    vigente = lambda ini, fin: ini and (fin or ini) >= ahora and ini <= limite
    out, vistos = [], set()
    # 1) JSON-LD (algunas webs repiten el mismo evento en varios bloques: se deduplica)
    for n in _eventos_jsonld(html):
        ini, fin = _parse_iso(n.get("startDate")), _parse_iso(n.get("endDate"))
        if not vigente(ini, fin) or (n.get("name"), ini) in vistos:
            continue
        vistos.add((n.get("name"), ini))
        loc = n.get("location") or {}
        loc = loc[0] if isinstance(loc, list) and loc else loc
        lugar = loc.get("name", "") if isinstance(loc, dict) else str(loc)
        ofertas = n.get("offers") or {}
        ofertas = ofertas[0] if isinstance(ofertas, list) and ofertas else ofertas
        precio = str(ofertas.get("price", "")) if isinstance(ofertas, dict) else ""
        gratis = True if n.get("isAccessibleForFree") or precio in ("0", "0.0", "0.00") else (False if precio else None)
        img = n.get("image")
        img = img[0] if isinstance(img, list) and img else img
        out.append(_item(fuente, htmlmod.unescape(n.get("name", "")), ini, fin, urljoin(base, n.get("url") or base),
                         lugar, htmlmod.unescape(re.sub(r"<[^>]+>", "", n.get("description") or ""))[:700],
                         img if isinstance(img, str) else "", gratis, "json-ld"))
    if out:
        return out
    # 2) enlaces .ics
    if get is not None:
        for href in list(dict.fromkeys(re.findall(r'href=["\']([^"\']+\.ics[^"\']*)["\']', html, re.I)))[:3]:
            try:
                from icalendar import Calendar
                cal = Calendar.from_ical(get(urljoin(base, href.replace("webcal://", "https://")), timeout=20)
                                         .content.decode("utf-8", "replace"))
            except Exception:
                continue
            for ve in cal.walk("VEVENT"):
                d0, d1 = ve.get("DTSTART"), ve.get("DTEND")
                conv = lambda v: None if v is None else (v.dt if isinstance(v.dt, datetime) else
                                                         datetime(v.dt.year, v.dt.month, v.dt.day, tzinfo=LIMA))
                ini, fin = conv(d0), conv(d1)
                ini = ini if not ini or ini.tzinfo else ini.replace(tzinfo=LIMA)
                fin = fin if not fin or fin.tzinfo else fin.replace(tzinfo=LIMA)
                if vigente(ini, fin):
                    out.append(_item(fuente, str(ve.get("SUMMARY", "")), ini, fin, str(ve.get("URL", "") or base),
                                     str(ve.get("LOCATION", "") or ""), str(ve.get("DESCRIPTION", ""))[:700], "", None, "ics"))
        if out:
            return out
    bloques = _bloques(html)
    titulo_pag = _titulo_pagina(html)
    if fuente.get("modo") == "evento":
        return _evento_unico(fuente, html, bloques, titulo_pag, desc_pag, img_pag, ahora, limite)
    # 3) <time datetime> con el encabezado o enlace más cercano como título
    for m in re.finditer(r'<time[^>]+datetime=["\']([^"\']+)["\'][^>]*>', html, re.I):
        ini = _parse_iso(m.group(1))
        if not vigente(ini, None):
            continue
        antes = html[max(0, m.start() - 900): m.start()]
        cands = re.findall(r"<(?:h[1-4]|a)[^>]*>(.*?)</(?:h[1-4]|a)>", antes, re.S | re.I)
        titulo = next((re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", c))).strip()
                       for c in reversed(cands) if len(re.sub(r"<[^>]+>", "", c).strip()) > 12), "")
        if titulo and EVENTO.search(titulo):
            out.append(_item(fuente, titulo, ini, ini.replace(hour=23, minute=59), base, "", "", "", None, "time"))
    if out:
        return out
    # 4) fechas en español en la agenda: título = bloque previo con forma de título; exige palabra de evento
    return _agenda_regex(fuente, bloques, ahora, limite)


def _evento_unico(fuente, html, bloques, titulo_pag, desc_pag, img_pag, ahora, limite):
    anio = _anio_de(titulo_pag) or _anio_de(fuente["url"])
    texto = " | ".join(bloques)
    for ini, fin, pos in fechas_es(texto, anio):
        if fin < ahora or ini > limite:
            continue
        # lugar: el bloque que sigue a la fecha si nombra una ciudad o un recinto
        tras = texto[pos: pos + 400].split(" | ")[1:4]
        lugar = next((b for b in tras if re.search(r"\b(lima|per[uú]|arequipa|centro|parque|campus|auditorio|"
                                                   r"hotel|plaza|convenciones)\b", b, re.I)), "")
        cerca = texto[max(0, pos - 400): pos + 400]
        gratis = True if re.search(r"\bgratuit[oa]s?\b|\bgratis\b|entrada libre|ingreso libre", cerca, re.I) else None
        nombre = fuente.get("evento") or titulo_pag
        if anio and anio not in nombre:
            nombre = f"{nombre} {ini.year}"
        return [_item(fuente, nombre, ini, fin, fuente["url"], lugar, desc_pag, img_pag, gratis, "fecha en texto")]
    return []


def _agenda_regex(fuente, bloques, ahora, limite, maximo=15):
    out, vistos = [], set()
    for i, b in enumerate(bloques):
        etiqueta = re.match(r"^(fecha|inicio|fecha y horario)\s*:", b, re.I)
        # sin año explícito solo se acepta si viene rotulado ("Fecha: 5 de noviembre") → año actual/siguiente
        anio = str(ahora.year) if etiqueta else None
        for ini, fin, _ in fechas_es(b, anio):
            if etiqueta and not re.search(r"20\d\d", b) and fin < ahora:
                ini, fin = ini.replace(year=ini.year + 1), fin.replace(year=fin.year + 1)
            if fin < ahora or ini > limite:
                continue
            titulo, formato = "", ""
            for j in range(i - 1, max(-1, i - 9), -1):
                c = bloques[j]
                if fechas_es(c, "2000") or ETIQUETA.match(c) or re.fullmatch(r"[\d\s:apm.–-]+", c, re.I):
                    continue
                if len(c) < 30 and EVENTO.search(c) and not titulo:
                    formato = formato or c  # "Seminario", "Clase modelo"
                    continue
                if 12 <= len(c) <= 160 and re.search(r"[a-záéíóúñ]{3}", c, re.I):
                    titulo = c
                    break
            if not titulo:
                continue
            if not (EVENTO.search(titulo) or formato):
                continue  # un titular de noticia con fecha no es un evento
            nombre = f"{formato}: {titulo}" if formato and formato.lower() not in titulo.lower() else titulo
            clave = (nombre.lower(), ini.date())
            if clave in vistos:
                continue
            vistos.add(clave)
            tras = " ".join(bloques[i + 1: i + 4])
            gratis = True if re.search(r"gratuit|gratis|free\b", tras, re.I) else (
                False if re.search(r"s/\s?\d|usd\s?\d|us\$|\$\s?\d", tras, re.I) else None)
            out.append(_item(fuente, nombre, ini, fin, fuente["url"], "", "", "", gratis, "fecha en texto"))
            if len(out) >= maximo:
                return out
    return out


def _paginas_sitemap(fuente, get, ahora):
    """URLs de eventos modificadas hace poco según el sitemap del sitio (más recientes primero)."""
    xml = get(fuente["sitemap"], timeout=25).content.decode("utf-8", "replace")
    pares = re.findall(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", xml)
    patron = re.compile(fuente.get("patron") or ".", re.I)
    desde = ahora - timedelta(days=fuente.get("dias_modificado", 120))
    recientes = [(u, _parse_iso(m)) for u, m in pares if patron.search(u)]
    recientes = [(u, m) for u, m in recientes if m and m >= desde]
    recientes.sort(key=lambda x: x[1], reverse=True)
    return [u for u, _ in recientes[: fuente.get("maximo", 12)]]


def _evento_de_pagina(fuente, url, html, ahora, limite):
    """Una página = un evento: título de la página y la primera fecha futura (año actual si no lo dice)."""
    bloques = _bloques(html)
    titulo = re.split(r"\s+[|–-]\s+", _titulo_pagina(html))[0].strip()
    texto = " | ".join(bloques)
    anio = _anio_de(titulo) or str(ahora.year)
    for ini, fin, pos in fechas_es(texto, anio):
        if fin >= ahora and ini <= limite:
            cerca = texto[max(0, pos - 400): pos + 400]
            gratis = True if re.search(r"\bgratuit[oa]s?\b|\bgratis\b|ingreso libre|entrada libre", cerca, re.I) else None
            return _item(fuente, titulo, ini, fin, url, "", _meta(html, "og:description", "description"),
                         _meta(html, "og:image"), gratis, "sitemap + fecha en texto")
    return None


def recolectar(get, ruta_json, limite):
    """Recorre la lista de vigilancia. Devuelve (eventos, estado_por_pagina). Cada página falla sola."""
    conf = json.loads(Path(ruta_json).read_text(encoding="utf-8"))
    ahora = datetime.now(LIMA)
    eventos, estado = [], {}
    for f in conf.get("fuentes", []):
        try:
            if f.get("modo") == "sitemap":
                lote = []
                for u in _paginas_sitemap(f, get, ahora):
                    try:
                        e = _evento_de_pagina(f, u, get(u, timeout=25).content.decode("utf-8", "replace"), ahora, limite)
                    except Exception:
                        continue  # una página rota no tumba a las demás
                    if e:
                        lote.append(e)
                eventos += lote
                estado[f["nombre"]] = len(lote)
                continue
            r = get(f["url"], timeout=25)
            r.raise_for_status()
            html = r.content.decode("utf-8", errors="replace")  # bytes: requests adivina mal el charset
            lote = extraer(f, html, ahora, limite, get)
            eventos += lote
            estado[f["nombre"]] = len(lote)
        except Exception as e:
            estado[f["nombre"]] = f"falló: {str(e)[:80]}"
    return eventos, estado


# ---------------------------------------------------------------- 2) descubrimiento (Por confirmar)
# El título tiene que nombrar un evento; "Congreso" a secas en el Perú suele ser el Parlamento.
DESCUBRIR = re.compile(r"\b(cumbre|foro|summit|feria|expo\w*|convenci[oó]n|congreso (internacional|nacional|"
                       r"latinoamericano|mundial|de )|conferencia|encuentro|semana de|festival)\b", re.I)
GENERICAS = {"lima", "peru", "perú", "2025", "2026", "2027", "summit", "cumbre", "foro", "feria", "congreso",
             "evento", "edicion", "edición", "internacional", "nacional", "conferencia", "encuentro", "semana",
             "expo", "latam", "para", "sobre", "desde", "este", "esta", "será", "sera", "llega", "reunirá"}
NO_EVENTO = re.compile(r"\b(congreso de la rep[uú]blica|congresistas?|proyecto de ley|pleno|alcald\w+|candidat\w+|"
                       r"debate (municipal|presidencial|electoral)|elecciones|electoral|senado|propuestas|fiscal\w*|"
                       r"policial|crimen|asesinato|detenid\w+|camiset\w+|gastron\w+|concierto|fiesta|moda|cerveza|"
                       r"vino|f[uú]tbol|anime|cosplay)\b", re.I)
def descubrir(get, ruta_json, conocidos, maximo=12):
    """Titulares recientes de Bing News sobre cumbres/foros/congresos en Lima que NO están en el radar."""
    conf = json.loads(Path(ruta_json).read_text(encoding="utf-8")).get("descubrimiento", {})
    ahora = datetime.now(LIMA)
    # Palabras distintivas: sin las genéricas, un "Summit Lima 2026" no tapa a cualquier otro summit.
    distintivas = lambda s: set(re.findall(r"[a-záéíóúñ0-9]{4,}", s.lower())) - GENERICAS
    marcas = [m for m in (distintivas(c) for c in conocidos) if m]
    out, vistos = [], set()
    for q in conf.get("consultas", []):
        url = "https://www.bing.com/news/search?format=rss&setlang=es&cc=PE&q=" + quote_plus(q.format(anio=ahora.year))
        try:
            xml = get(url, timeout=20).content.decode("utf-8", "replace")
        except Exception:
            continue
        for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
            campo = lambda n: htmlmod.unescape(re.sub(r"<[^>]+>", "", (re.search(rf"<{n}[^>]*>(.*?)</{n}>", it, re.S)
                                                                     or [None, ""])[1])).strip()
            titulo, desc, link, medio = campo("title"), campo("description"), campo("link"), campo("News:Source")
            texto = f"{titulo} {desc}"
            if not DESCUBRIR.search(titulo) or not re.search(r"\b(lima|per[uú])\b", texto, re.I) \
                    or NO_EVENTO.search(texto):
                continue
            clave = re.sub(r"[^a-z0-9]", "", titulo.lower())[:50]
            palabras = distintivas(titulo)
            # ya está en el radar (todas sus palabras distintivas aparecen en el titular), o es otro titular
            # del mismo evento que uno ya propuesto (comparten la mayoría de palabras distintivas)
            if clave in vistos or any(m <= palabras or len(m & palabras) >= max(3, 0.6 * min(len(m), len(palabras)))
                                      for m in marcas):
                continue
            vistos.add(clave)
            marcas.append(palabras)
            real = parse_qs(urlsplit(link).query).get("url", [link])[0]
            fechas = [f for f in fechas_es(texto, str(ahora.year)) if f[1] >= ahora]
            out.append({"titulo": titulo[:160], "url": real, "medio": medio or urlsplit(real).netloc,
                        "publicado": campo("pubDate"), "resumen": desc[:240],
                        "fecha_mencionada": fechas[0][0].isoformat(timespec="minutes") if fechas else ""})
            if len(out) >= maximo:
                return out
    return out


# ---------------------------------------------------------------- 3) recurrentes anuales (Se viene)
def se_viene(ruta_recurrentes, eventos, hoy=None, ventana_dias=70):
    """Eventos anuales (o bienales) de recurrentes.json cuyo mes habitual empieza en ≤ ~2 meses y que todavía
    no tienen fecha publicada en el radar. Si ya se sabe la fecha de esta edición, se muestra con esa fecha."""
    try:
        conf = json.loads(Path(ruta_recurrentes).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    hoy = hoy or datetime.now(LIMA)
    listados = [norm_simple(e["titulo"]) for e in eventos]
    out = []
    for r in conf.get("eventos", []):
        meses = r.get("meses") or [r["mes"]]
        cada = r.get("cada_anios", 1)
        ediciones = {str(x["anio"]): x for x in r.get("ediciones", [])}
        for anio in (hoy.year, hoy.year + 1):
            if cada > 1 and (anio - int(r.get("anio_referencia", anio))) % cada:
                continue  # bienal: este año no toca
            edicion = ediciones.get(str(anio))
            fecha = datetime.fromisoformat(edicion["inicio"]).replace(tzinfo=LIMA) if edicion and edicion.get("inicio") \
                else datetime(anio, meses[0], 1, tzinfo=LIMA)
            dias = (fecha - hoy).days
            if -20 <= dias <= ventana_dias:
                break
        else:
            continue
        if edicion and edicion.get("fin") and datetime.fromisoformat(edicion["fin"]).replace(tzinfo=LIMA) < hoy:
            continue  # la edición de este año ya pasó
        if any(norm_simple(r["nombre"]) in t for t in listados):
            continue  # ya está en la lista con su fecha
        nombres = [NOMBRE_MES[m] for m in meses]
        out.append({
            "nombre": r["nombre"], "organizador": r.get("organizador", ""), "url": r.get("url", ""),
            "mes": meses[0], "ciudad": (edicion or {}).get("lugar") or r.get("ciudad", "Lima"),
            "texto": (f"{anio}: del {edicion['inicio'][8:10]}/{edicion['inicio'][5:7]} al {edicion['fin'][8:10]}/{edicion['fin'][5:7]}"
                      if edicion and edicion.get("fin") else f"suele ser en {' u '.join(nombres)}")
                     + (" · cada 2 años" if cada == 2 else ""),
            "dato": r.get("dato", ""),
        })
    return out


def norm_simple(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()
