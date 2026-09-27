"""inscripciones.py — enlaces de inscripción que las organizaciones publican en su Linktree.

Linktree prohíbe robots (robots.txt: `User-agent: *` → `Disallow: /`), así que el radar NO lo recorre.
Cuando alguien comparte un Linktree, JARVIS lo abre a pedido (consulta de una persona, no un robot) y copia
sus enlaces de inscripción a `inscripciones.json`. Lo que el radar sí lee solo, en cada corrida, es el
DESTINO de cada enlace, revisando robots.txt en cada salto (un bit.ly puede llevar a un sitio que lo prohíbe):
- Google Forms: título, descripción (fecha, hora, lugar) y si todavía acepta respuestas.
- Páginas web de eventos: con los mismos extractores de institucionales.py.
Lo que no se puede leer (Microsoft Forms prohíbe robots; formularios solo para cuentas de la universidad;
páginas sin fecha) no se pierde: va a "Por confirmar" con su nombre y su enlace.
"""
import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import institucionales as inst

LIMA = inst.LIMA
FUENTE = "Inscripciones (Linktree)"
POR_CONFIRMAR = []   # lo que no se pudo leer en la última corrida (lo usa eventos.py para la sección "Por confirmar")
RX_HORA = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?)(?![a-z])|\b(\d{1,2}):(\d{2})\s*(?:h|hrs?|horas)?\b", re.I)
RX_LUGAR = re.compile(r"(?:^|\n)\s*(?:lugar|sede|direcci[oó]n)\s*:\s*([^\n]{3,120})|"
                      r"(?:^|\n)\s*((?:teatro|auditorio|aula|campus|sal[oó]n|centro|hotel|av\.|jr\.|calle)[^\n]{2,100})", re.I)
RX_VIRTUAL = re.compile(r"\b(zoom|google meet|meet\.google|microsoft teams|teams|virtual|en l[ií]nea|online|webinar)\b", re.I)
RX_CERRADO = re.compile(r"ya no acepta respuestas|no longer accepting responses|/closedform", re.I)


def resolver(url, get, permitido, saltos=5):
    """Sigue redirecciones UNA por UNA revisando robots.txt de cada destino antes de pedirlo.
    Devuelve (respuesta, url_final) o (None, motivo)."""
    for _ in range(saltos):
        if not permitido(url):
            return None, f"{urlsplit(url).netloc} no permite robots"
        r = get(url, timeout=25, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"])
            continue
        if r.status_code in (401, 403):
            return None, "pide iniciar sesión (formulario solo para cuentas de la organización)"
        if r.status_code >= 400:
            return None, f"respondió {r.status_code}"
        return r, url
    return None, "demasiadas redirecciones"


def _hora(texto, desde=0):
    """Primera hora que aparece a partir de `desde`: '4:15 p. m.', '3pm', '18:30 h'."""
    for m in RX_HORA.finditer(texto, desde):
        if m.group(1):
            h, mi = int(m.group(1)), int(m.group(2) or 0)
            if not 1 <= h <= 12 or mi > 59:
                continue
            tarde = m.group(3).lower().startswith("p")
            return (h % 12) + (12 if tarde else 0), mi
        h, mi = int(m.group(4)), int(m.group(5))
        if 6 <= h <= 23 and mi <= 59:
            return h, mi
    return None


def evento_de_texto(titulo, descripcion, ahora):
    """Fecha(s), hora, lugar y modalidad sacados del texto de un formulario. None si no hay fecha."""
    anio = inst._anio_de(titulo + " " + descripcion) or str(ahora.year)
    fechas = inst.fechas_es(descripcion, anio) or inst.fechas_es(titulo, anio)
    if not fechas:
        return None
    ini, fin = min(f[0] for f in fechas), max(f[1] for f in fechas)
    if fin < ahora - timedelta(days=180):  # sin año explícito y muy en el pasado: es del año que viene
        ini, fin = ini.replace(year=ini.year + 1), fin.replace(year=fin.year + 1)
    pos = min(fechas, key=lambda f: f[0])[2]
    hm = _hora(descripcion, pos) or _hora(descripcion)
    if hm:
        ini = ini.replace(hour=hm[0], minute=hm[1])
    lugar = ""
    m = RX_LUGAR.search(descripcion)
    if m:
        lugar = re.sub(r"[*\s]+$", "", (m.group(1) or m.group(2)).strip())
    virtual = RX_VIRTUAL.search(titulo + " " + descripcion) and not re.search(r"presencial", descripcion, re.I)
    return {"inicio": ini, "fin": fin if fin.date() != ini.date() else None, "lugar": lugar,
            "modalidad": "Virtual" if virtual else "Presencial"}


def google_form(html, url):
    """Título, descripción, imagen y si está cerrado, desde FB_PUBLIC_LOAD_DATA_ (o las metas como respaldo)."""
    titulo, desc = "", ""
    m = re.search(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\]);\s*</script>", html, re.S)
    if m:
        try:
            d = json.loads(m.group(1))
            titulo = (d[3] if len(d) > 3 and isinstance(d[3], str) else "") or (d[1][8] or "")
            desc = d[1][0] or ""
        except (ValueError, IndexError, TypeError):
            pass
    titulo = titulo or inst._titulo_pagina(html)
    desc = desc or inst._meta(html, "og:description", "description")
    return {"titulo": re.sub(r"^\s*inscripci[oó]n(?:es)?\s*[-:|]?\s*", "", titulo.strip(), flags=re.I).strip(),
            "descripcion": desc.strip(), "imagen": inst._meta(html, "og:image"),
            "cerrado": bool(RX_CERRADO.search(url) or RX_CERRADO.search(html))}


def _tipo(texto):
    t = inst.norm_simple(texto)
    if "voluntari" in t:
        return "voluntariado"
    if re.search(r"\b(convocatoria|postula|integra uno de|seleccion|comites?)\b", t):
        return "convocatoria"
    return "evento"


def _evento(enlace, datos, url_final, fechas):
    iso = lambda d: d.astimezone(LIMA).isoformat(timespec="minutes") if d else ""
    return {
        "id": "insc:" + hashlib.sha1(enlace["url"].encode()).hexdigest()[:12],
        "titulo": datos["titulo"] or enlace["titulo"], "tipo": _tipo(datos["titulo"] + " " + enlace["titulo"]),
        "inicio": iso(fechas["inicio"]), "fin": iso(fechas["fin"]), "cierre": "",
        "lugar": fechas["lugar"], "distrito": enlace.get("distrito", "Lima"), "modalidad": fechas["modalidad"],
        "url": url_final, "inscripcion": url_final,
        "fuente": FUENTE, "fuente_url": enlace.get("origen", ""),
        "organizador": enlace["organizador"], "descripcion": datos["descripcion"][:1500],
        "gratis": None, "imagen": datos.get("imagen", ""),
        "cats_fuente": enlace.get("categorias") or inst.CATS_ORG.get(enlace.get("tipo_org"), ["Habilidades y liderazgo"]),
        "_manual": True,  # lista curada: si el clasificador no encuentra área, vale la del organizador
    }


def _pendiente(enlace, motivo, ahora):
    """Entrada para 'Por confirmar'. Si el propio título trae una fecha 'dd/mm' que ya pasó, no se muestra."""
    m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", enlace["titulo"])
    if m:
        try:
            dia = datetime(ahora.year, int(m.group(2)), int(m.group(1)), 23, 59, tzinfo=LIMA)
            if dia < ahora:
                return None
        except ValueError:
            pass
    return {"titulo": enlace["titulo"], "url": enlace["url"], "medio": f"Linktree de {enlace['organizador']}",
            "fecha_mencionada": "", "nota": motivo}


def recolectar(get, permitido, ruta_json, ahora=None, pausa=1.1):
    """Devuelve (eventos, por_confirmar, estado_por_enlace). Cada enlace falla solo."""
    ahora = ahora or datetime.now(LIMA)
    conf = json.loads(Path(ruta_json).read_text(encoding="utf-8"))
    eventos, pendientes, estado = [], [], {}
    for enlace in conf.get("enlaces", []):
        try:
            r, final = resolver(enlace["url"], get, permitido)
            if r is None:
                p = _pendiente(enlace, final, ahora)
                pendientes += [p] if p else []
                estado[enlace["url"]] = final
                continue
            html = r.content.decode("utf-8", errors="replace")
            if "docs.google.com/forms" in final:
                datos = google_form(html, final)
                time.sleep(pausa)  # robots.txt de docs.google.com pide Crawl-delay: 1
            else:  # página de evento: título y descripción de la página
                datos = {"titulo": re.split(r"\s+[|–-]\s+", inst._titulo_pagina(html))[0].strip(),
                         "descripcion": " \n".join(inst._bloques(html))[:3000],
                         "imagen": inst._meta(html, "og:image"), "cerrado": False}
            fechas = evento_de_texto(datos["titulo"] or enlace["titulo"], datos["descripcion"], ahora)
            if not fechas:
                p = _pendiente(enlace, "sin fecha legible en la inscripción", ahora)
                pendientes += [p] if p else []
                estado[enlace["url"]] = "sin fecha"
                continue
            ev = _evento(enlace, datos, final, fechas)
            if datos["cerrado"]:
                ev["_motivo"] = "inscripciones cerradas"
            eventos.append(ev)
            estado[enlace["url"]] = "cerrado" if datos["cerrado"] else "ok"
        except PermissionError as e:
            estado[enlace["url"]] = str(e)[:120]
        except Exception as e:  # un enlace roto no tumba a los demás
            estado[enlace["url"]] = f"error: {type(e).__name__}"
    POR_CONFIRMAR[:] = pendientes
    return eventos, pendientes, estado
