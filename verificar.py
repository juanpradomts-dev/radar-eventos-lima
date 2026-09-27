"""verificar.py — control de calidad de TODO evento antes de publicarlo, y monitoreo de las fuentes.

Cada corrida revisa fechas, horas, textos, enlaces, precio, lugar y duplicados. Tres niveles, y
nunca se borra nada (regla del radar):
- "corregido": el dato estaba mal y se arregla con certeza; el valor de la fuente queda en `original`.
- "aviso": algo raro que no se puede arreglar solo; el evento se publica y queda anotado.
- "archivado": no se puede publicar tal cual (sin enlace, ya pasó, duplicado, enlace roto confirmado);
  pasa al Archivo con el motivo "no pasó la verificación: …".
Además vigila las fuentes: si una empieza a traer muchos datos malos, la marca "para revisar".
El informe sale en la página (Control de calidad) y en el resumen de cada corrida de GitHub Actions.
"""
import difflib
import html
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIMA = timezone(timedelta(hours=-5))
CON_PLAZO = {"convocatoria", "voluntariado"}
VIRTUAL = r"\b(webinar|webinars|online|virtual|en linea|via zoom|por zoom)\b"
# siglas que se respetan al pasar un título de MAYÚSCULAS a formato legible
SIGLAS = {"UPC", "UNI", "UNMSM", "PUCP", "UTEC", "UCSUR", "ESAN", "USIL", "UPN", "UDEP", "UP", "UPCH", "ULIMA",
          "IA", "AI", "TI", "IT", "ML", "UX", "UI", "IEEE", "AWS", "PMI", "SNI", "CADE", "IPAE", "INFORMS", "ONU",
          "ONG", "MYPE", "MYPES", "PYME", "PYMES", "SUNAT", "SUNAFIL", "CCL", "ADEX", "GS1", "ISO", "BCP", "BBVA",
          "IBM", "SAP", "ERP", "CRM", "KPI", "B2B", "NFT", "API", "QA", "CEO", "EEUU", "USA", "EE.UU.", "TEDX"}
MENORES = {"de", "del", "la", "las", "el", "los", "en", "y", "e", "o", "u", "a", "al", "para", "con", "por", "sin",
           "su", "sus", "un", "una", "the", "of", "and", "for", "in", "on", "to"}
DIAS_ENLACE = 7        # un enlace comprobado se vuelve a mirar después de una semana
MAX_ENLACES = 40       # por corrida (ser amable con los sitios)
HISTORIAL_MAX = 30     # corridas guardadas para el monitoreo


def _p(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=LIMA)


def _norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


# ---------------------------------------------------------------- arreglos de texto
def texto_limpio(s):
    """Quita HTML suelto (&amp;, <br>) y repara acentos rotos por doble codificación (Ã© → é)."""
    if not s:
        return s
    t = html.unescape(s)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</?[a-z][^>]{0,200}>", "", t, flags=re.I)
    if re.search(r"Ã[\x80-\xbf©±¡³º­]|â€", t):
        try:
            t = t.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return t


def titulo_legible(t):
    """'XVIII CONGRESO INTERNACIONAL DE DIRECCIÓN' → 'XVIII Congreso Internacional de Dirección'.
    Respeta siglas conocidas, números romanos, palabras con cifras y siglas cortas sin vocales (PTW)."""
    out = []
    for i, w in enumerate(t.split(" ")):
        limpio = re.sub(r"[^\wÁÉÍÓÚÜÑ.]", "", w)
        if (limpio.upper() in SIGLAS or re.fullmatch(r"[IVXLC]+", limpio) or re.search(r"\d", limpio)
                or (len(limpio) <= 4 and not re.search(r"[AEIOUÁÉÍÓÚ]", limpio))):
            out.append(w)
        elif i and w.lower() in MENORES:
            out.append(w.lower())
        else:
            out.append(w[:1] + w[1:].lower())
    return " ".join(out)


def _en_mayusculas(t):
    letras = [c for c in t if c.isalpha()]
    return len(letras) >= 12 and all(c.isupper() for c in letras)


# ---------------------------------------------------------------- revisión de un evento
def revisar_evento(e, ahora):
    """Revisa y corrige un evento en su lugar. Devuelve [(nivel, detalle)]."""
    notas = []

    def corrige(campo, nuevo, detalle):
        e.setdefault("original", {}).setdefault(campo, e.get(campo))
        e[campo] = nuevo
        notas.append(("corregido", detalle))

    # textos
    for campo in ("titulo", "descripcion", "lugar", "organizador"):
        v = e.get(campo)
        if v and texto_limpio(v) != v:
            corrige(campo, texto_limpio(v).strip(), f"{campo}: tenía HTML o acentos rotos")
    t = (e.get("titulo") or "").strip()
    if len(t) < 4:
        return notas + [("archivado", "sin título legible")]
    if _en_mayusculas(t):
        corrige("titulo", titulo_legible(t), "título en MAYÚSCULAS → formato legible")
    desc = (e.get("descripcion") or "").strip()
    if desc and _norm(desc) == _norm(e["titulo"]):
        corrige("descripcion", "", "la descripción solo repetía el título")

    # enlaces
    if not re.match(r"https?://", e.get("url") or ""):
        return notas + [("archivado", "sin enlace válido a la fuente")]
    for campo in ("inscripcion", "imagen"):
        if e.get(campo) and not re.match(r"https?://", e[campo]):
            corrige(campo, "", f"{campo}: enlace inválido")

    # fechas y horas
    tipo = e.get("tipo") or "evento"
    ini, fin, cierre = _p(e.get("inicio")), _p(e.get("fin")), _p(e.get("cierre"))
    if not ini and tipo not in CON_PLAZO:
        return notas + [("archivado", "fecha ilegible")]
    if cierre and cierre < ahora:
        return notas + [("archivado", "la convocatoria ya cerró")]
    if tipo not in CON_PLAZO and not cierre and (fin or ini) < ahora - timedelta(hours=1):
        return notas + [("archivado", "ya pasó")]
    if ini and fin and fin < ini:
        corrige("fin", "", "la hora de término era anterior al inicio")
        fin = None
    todo_el_dia = ini and ini.hour == 0 and ini.minute == 0
    # (solo eventos con hora: en convocatorias inicio = fin = cierre a las 23:59 es el plazo real, no un relleno)
    if ini and fin and fin > ini and fin.date() == ini.date() and not todo_el_dia and not cierre and tipo not in CON_PLAZO:
        fin_local = fin.astimezone(LIMA)
        if fin - ini > timedelta(hours=12):
            corrige("fin", "", f"hora de término no creíble ({ini:%H:%M}–{fin:%H:%M})")
        elif fin_local.hour == 23 and fin_local.minute >= 45:
            # SNI y otras webs rellenan el término con 23:50/23:59 cuando no lo saben
            corrige("fin", "", f"hora de término de relleno ({fin_local:%H:%M})")
    if ini and not cierre and tipo not in CON_PLAZO and not todo_el_dia:
        loc = ini.astimezone(LIMA)
        if loc.minute % 5:
            e["hora_dudosa"] = True
            notas.append(("aviso", f"hora poco probable ({loc:%H:%M}): se muestra 'por confirmar'"))
        elif 0 < loc.hour < 6 and e.get("modalidad") == "Presencial":
            e["hora_dudosa"] = True
            notas.append(("aviso", f"presencial de madrugada ({loc:%H:%M}): se muestra 'por confirmar'"))
    if ini and ini > ahora + timedelta(days=540):
        notas.append(("aviso", "fecha a más de un año y medio"))
    if tipo == "evento" and ini and fin and (fin - ini).days > 60:
        notas.append(("aviso", f"dura {(fin - ini).days} días"))

    # lugar y modalidad
    if e.get("modalidad") == "Presencial" and re.search(VIRTUAL, _norm(e["titulo"])):
        corrige("modalidad", "Virtual", "el título dice webinar/virtual")
    if e.get("modalidad") == "Presencial" and not (e.get("lugar") or e.get("distrito")):
        notas.append(("aviso", "presencial sin dirección"))
    return notas


def duplicados(eventos):
    """Pares casi idénticos del mismo día (distinta fuente o distinto enlace). Se queda el más completo."""
    fuera = {}
    por_dia = {}
    for e in eventos:
        por_dia.setdefault((e.get("cierre") or e.get("inicio") or "")[:10], []).append(e)
    for grupo in por_dia.values():
        for i, a in enumerate(grupo):
            for b in grupo[i + 1:]:
                if a["id"] in fuera or b["id"] in fuera:
                    continue
                na = re.sub(r"[^a-z0-9 ]", "", _norm(a["titulo"]))
                nb = re.sub(r"[^a-z0-9 ]", "", _norm(b["titulo"]))
                if difflib.SequenceMatcher(None, na, nb).ratio() >= .9:
                    queda, sale = sorted([a, b], key=lambda x: -len(x.get("descripcion") or ""))
                    fuera[sale["id"]] = f"duplicado de «{queda['titulo'][:60]}» ({queda['fuente']})"
    return fuera


# ---------------------------------------------------------------- enlaces
def comprobar_enlaces(eventos, get, ruta_cache, ahora, limite=MAX_ENLACES):
    """Mira si los enlaces siguen vivos. Solo 404/410 cuentan como rotos (403, 405, 429 o un timeout
    suelen ser bloqueos a robots, no páginas caídas). Roto dos veces seguidas = roto de verdad."""
    try:
        cache = json.loads(Path(ruta_cache).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    urls = list(dict.fromkeys(e.get("inscripcion") or e["url"] for e in eventos))
    viejo = (ahora - timedelta(days=DIAS_ENLACE)).isoformat()
    pendientes = [u for u in urls if cache.get(u, {}).get("fecha", "") < viejo][:limite]

    def mirar(u):
        try:
            r = get(u, timeout=12, stream=True, allow_redirects=True)
            r.close()
            return u, r.status_code
        except PermissionError:
            return u, "robots"
        except Exception:
            return u, "sin respuesta"

    with ThreadPoolExecutor(8) as pool:
        for u, codigo in pool.map(mirar, pendientes):
            antes = cache.get(u, {})
            roto = codigo in (404, 410)
            cache[u] = {"codigo": codigo, "fecha": ahora.isoformat(timespec="minutes"),
                        "fallos": antes.get("fallos", 0) + 1 if roto else 0}
    vivos = set(urls)
    cache = {u: v for u, v in cache.items() if u in vivos}  # no crece sin fin
    Path(ruta_cache).parent.mkdir(parents=True, exist_ok=True)
    Path(ruta_cache).write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache, len(pendientes)


# ---------------------------------------------------------------- corrida completa
def revisar(eventos, archivo, ahora=None, get=None, ruta_cache=None, ruta_historial=None):
    """Revisa la lista que se va a publicar. Devuelve (eventos, archivo, informe)."""
    ahora = ahora or datetime.now(LIMA)
    informe = {"fecha": ahora.isoformat(timespec="minutes"), "revisados": len(eventos), "corregidos": 0,
               "avisos": 0, "archivados": 0, "problemas": [], "enlaces": {}, "fuentes_a_revisar": []}
    por_fuente = {}
    salen = {}

    def anotar(e, nivel, detalle):
        informe["problemas"].append({"id": e["id"], "titulo": e["titulo"][:90], "fuente": e.get("fuente", ""),
                                     "nivel": nivel, "detalle": detalle, "url": e.get("url", "")})
        por_fuente.setdefault(e.get("fuente", "?"), set()).add(e["id"])

    for e in eventos:
        try:
            notas = revisar_evento(e, ahora)
        except Exception as ex:  # el verificador nunca tumba el radar
            notas = [("aviso", f"no se pudo revisar ({type(ex).__name__})")]
        for nivel, detalle in notas:
            anotar(e, nivel, detalle)
            if nivel == "archivado":
                salen[e["id"]] = detalle
    for id_, motivo in duplicados([e for e in eventos if e["id"] not in salen]).items():
        e = next(x for x in eventos if x["id"] == id_)
        anotar(e, "archivado", motivo)
        salen[id_] = motivo

    if get and ruta_cache:
        try:
            cache, n = comprobar_enlaces([e for e in eventos if e["id"] not in salen], get, ruta_cache, ahora)
            rotos = 0
            for e in eventos:
                c = cache.get(e.get("inscripcion") or e["url"])
                if not c or e["id"] in salen or c["codigo"] not in (404, 410):
                    continue
                rotos += 1
                if c["fallos"] >= 2:
                    anotar(e, "archivado", f"enlace roto ({c['codigo']}) en dos revisiones seguidas")
                    salen[e["id"]] = f"enlace roto ({c['codigo']})"
                else:
                    anotar(e, "aviso", f"el enlace respondió {c['codigo']}; se vuelve a mirar en la próxima corrida")
            informe["enlaces"] = {"comprobados": n, "rotos": rotos,
                                  "sin_comprobar": sum(1 for v in cache.values() if not isinstance(v["codigo"], int))}
        except Exception as ex:
            informe["enlaces"] = {"error": str(ex)[:120]}

    for e in eventos:
        if e["id"] in salen:
            e["motivo"] = "no pasó la verificación: " + salen[e["id"]]
    archivo = archivo + [e for e in eventos if e["id"] in salen]
    eventos = [e for e in eventos if e["id"] not in salen]
    for clave, nivel in (("corregidos", "corregido"), ("avisos", "aviso"), ("archivados", "archivado")):
        informe[clave] = len({p["id"] for p in informe["problemas"] if p["nivel"] == nivel})  # eventos, no notas

    # monitoreo de fuentes: proporción de eventos con problemas en esta corrida y en la anterior
    totales = {}
    for e in eventos + [x for x in archivo if x["id"] in salen]:
        totales[e.get("fuente", "?")] = totales.get(e.get("fuente", "?"), 0) + 1
    tasas = {f: round(len(por_fuente.get(f, ())) / n, 2) for f, n in totales.items()}
    historial = []
    if ruta_historial:
        try:
            historial = json.loads(Path(ruta_historial).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            historial = []
    previa = historial[-1]["tasas"] if historial else {}
    for f, tasa in tasas.items():
        if totales[f] >= 3 and tasa >= .4:
            informe["fuentes_a_revisar"].append({"fuente": f, "detalle": f"{round(tasa * 100)}% de sus eventos con problemas"})
        elif totales[f] >= 3 and tasa - previa.get(f, tasa) >= .25:
            informe["fuentes_a_revisar"].append({"fuente": f, "detalle": f"los problemas subieron de "
                                                 f"{round(previa[f] * 100)}% a {round(tasa * 100)}%"})
    if ruta_historial:
        historial.append({"fecha": informe["fecha"], "revisados": informe["revisados"],
                          "corregidos": informe["corregidos"], "avisos": informe["avisos"],
                          "archivados": informe["archivados"], "tasas": tasas})
        Path(ruta_historial).write_text(json.dumps(historial[-HISTORIAL_MAX:], ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    informe["problemas"] = informe["problemas"][:80]
    return eventos, archivo, informe


def resumen_markdown(inf):
    """Resumen para GitHub Actions ($GITHUB_STEP_SUMMARY)."""
    en = inf.get("enlaces") or {}
    lineas = ["## 🛡️ Control de calidad del Radar Lima", "",
              f"**{inf['revisados']}** eventos revisados · **{inf['corregidos']}** corregidos · "
              f"**{inf['avisos']}** avisos · **{inf['archivados']}** al Archivo · "
              f"{en.get('comprobados', 0)} enlaces comprobados ({en.get('rotos', 0)} rotos)", ""]
    if inf["fuentes_a_revisar"]:
        lineas += ["### ⚠️ Fuentes para revisar", *[f"- **{x['fuente']}**: {x['detalle']}" for x in inf["fuentes_a_revisar"]], ""]
    if inf["problemas"]:
        lineas += ["| Nivel | Evento | Fuente | Detalle |", "|---|---|---|---|"]
        lineas += [f"| {p['nivel']} | {p['titulo'][:60].replace('|', '/')} | {p['fuente']} | "
                   f"{p['detalle'].replace('|', '/')} |" for p in inf["problemas"]]
    return "\n".join(lineas) + "\n"
