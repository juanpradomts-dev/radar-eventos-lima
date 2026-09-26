"""puntaje.py — cuánto aporta cada oportunidad al crecimiento de un estudiante universitario en Lima.

Dos capas, sumadas en `puntaje` (0-100):
  valor_general(ev)      0-60, IGUAL para cualquier estudiante y carrera: formativo > networking > recreativo;
                         bonus por presencial en Lima, gratis o bajo costo, certificado o premio, organizador
                         reconocido (universidad, gremio, empresa), plazo claro y eventos institucionales grandes;
                         penaliza la venta disfrazada, el contenido genérico y los hackathons globales sin vínculo.
  afinidad(ev, perfil)   0-40, leída de perfil.json (áreas con peso y palabras clave, palabras a evitar).
                         Sin perfil.json el radar funciona solo con el valor general.
Cada capa devuelve también las razones: la tarjeta muestra "por qué aparece aquí".
"""
import json
import re
import unicodedata
from pathlib import Path


def norm(s):
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _texto(ev, largo=2500):
    return f"{norm(ev.get('titulo'))} {norm(ev.get('organizador'))} {norm(ev.get('descripcion'))[:largo]} " \
           f"{norm(' '.join(ev.get('etiquetas') or []))}"


# ---------------------------------------------------------------- precio / gratis
# "Premios: $10,000" no es un precio: se quita antes de buscar costos.
_PREMIOS = re.compile(r"(premios?|prizes?|premio total|en premios|award)[^.\n]{0,80}", re.I)
# Solo señales explícitas: "free coffee", "software libre" o "tiempo libre" no hacen gratis un evento.
_GRATIS = re.compile(r"\b(gratis|gratuit[oa]s?|sin costo|no tiene costo|libre acceso|acceso libre|entrada libre|"
                     r"ingreso libre|free (event|entry|admission|registration|of charge|to attend|workshop|webinar)|"
                     r"costo:?\s*(free|gratuito|gratis|libre))\b", re.I)
_PRECIO = re.compile(r"(s/\.?\s?\d|us\$\s?\d|usd\s?\d|\$\s?\d|\d+\s?(soles|dolares|dólares)\b|\bpre-?venta\b|"
                     r"\bprecio\b|\btarifa\b|\bentradas?\s*(general|desde|:|s/|\$|a la venta)|"
                     r"\bcosto\b(?!:?\s*(free|gratuito|gratis|libre|0\b)))", re.I)


def es_gratis(ev):
    """True/False/None. Si el texto menciona un precio, NO es gratis aunque la fuente diga lo contrario."""
    texto = _PREMIOS.sub(" ", f"{ev.get('titulo', '')}\n{ev.get('descripcion', '')}")
    texto = re.sub(r"\bsin costo\b|\bno tiene costo\b", " gratis ", texto, flags=re.I)
    if _PRECIO.search(texto):
        return False
    if _GRATIS.search(texto):
        return True
    return ev.get("gratis") if ev.get("gratis") in (True, False) else None


def precio_soles(ev):
    """Menor precio en soles mencionado (US$ ≈ 3.7), o None."""
    t = _PREMIOS.sub(" ", ev.get("descripcion", "") or "")
    vals = [float(x.replace(",", ".")) for x in re.findall(r"s/\.?\s?(\d+(?:[.,]\d+)?)", t, re.I)]
    vals += [3.7 * float(x.replace(",", ".")) for x in re.findall(r"(?:us\$|usd|\$)\s?(\d+(?:[.,]\d+)?)", t, re.I)]
    return min(vals) if vals else None


# ---------------------------------------------------------------- categorías (máx. 2)
CATEGORIAS = {
    "Tecnología e IA": r"\b(ia|ai|inteligencia artificial|machine learning|llm|genai|gpt|claude|agentes?|agents?|"
                       r"python|javascript|programacion|developer|devs?|software|cloud|aws|azure|kubernetes|"
                       r"ciberseguridad|hacking|blockchain|n8n|automatiza\w*|no-?code|robot\w*|arduino|iot|"
                       r"cisco|redes|tech|tecnolog\w+|open source|linux|github)\b",
    "Datos y analítica": r"\b(datos|data|analytics|analitica|power bi|tableau|sql|big data|ciencia de datos|"
                         r"data science|estadistica|dashboard|excel|bi)\b",
    "Ingeniería y operaciones": r"\b(ingenieria|ingeniero|industrial|supply chain|cadena de suministro|logistica|"
                                r"operaciones|lean|six sigma|kaizen|procurement|manufactura|mantenimiento|calidad|"
                                r"iso \d+|bim|energia|mineria|sostenib\w+|mecanic\w+|electric\w+|pmp|"
                                r"project management|gestion de proyectos|direccion de proyectos|scrum|agile)\b",
    "Negocios y emprendimiento": r"\b(emprend\w+|startup\w*|founders?|vc|venture|inversion|finanzas|fintech|banca|"
                                 r"negocio\w*|pymes?|marketing|ventas|growth|innovacion|business|e-?commerce|"
                                 r"economia|pitch|incubadora|aceleradora|exportaci\w+|comercio)\b",
    "Investigación y ciencia": r"\b(investigacion|research|paper|cientific\w+|ciencia|scopus|tesis|publicacion|"
                               r"academic\w*|congreso|simposio|concytec|laboratorio|biotecnolog\w+|fisica|quimica|"
                               r"matematica\w*|call for papers)\b",
    "Habilidades y liderazgo": r"\b(liderazgo|lider\w*|oratoria|comunicacion efectiva|soft skills|habilidades|"
                               r"productividad|mentoring|mentoria|carrera|empleabilidad|cv|linkedin|entrevista|"
                               r"career|talento|debate|toastmasters|pensamiento critico|tedx)\b",
    "Idiomas, becas e internacional": r"\b(beca\w*|scholarship\w*|fellowship\w*|educationusa|fulbright|chevening|"
                                      r"daad|intercambio|study abroad|mba|maestria|posgrado|ll\.?m|toefl|ielts|"
                                      r"ingles|english|expoestudios|admision)\b",
    "Competencias y hackathons": r"\b(hackathon|hackaton|datathon|datafest|game jam|ideathon|concurso|competencia|"
                                 r"challenge|olimpiada|reto|premiacion|demo ?day)\b",
    # Voluntariado SOLO si el tipo lo es o el texto lo dice explícitamente (ver categorias()).
    "Voluntariado e impacto social": r"\b(voluntari\w+|volunteer\w*)\b",
}
FORMATO = r"\b(taller|workshop|conferencia|charla|seminario|meetup|summit|cumbre|congreso|foro|panel|" \
          r"conversatorio|bootcamp|curso|clase modelo|masterclass|webinar|simposio|keynote|hackathon|feria|" \
          r"jornada|open lab|kickoff|tech week|fest|expo|encuentro|convencion)\b"


def categorias(ev, maximo=2):
    """Las `maximo` categorías con más coincidencias (el título pesa x3). Si nada coincide, las de la fuente."""
    titulo, texto = norm(ev.get("titulo")), _texto(ev, 1500)
    puntos = {}
    for c, rx in CATEGORIAS.items():
        if c.startswith("Voluntariado") and ev.get("tipo") != "voluntariado" and not re.search(rx, texto):
            continue
        p = 3 * len(re.findall(rx, titulo)) + len(re.findall(rx, texto))
        if p:
            puntos[c] = p
    if ev.get("tipo") == "voluntariado":
        puntos["Voluntariado e impacto social"] = puntos.get("Voluntariado e impacto social", 0) + 100
    if not puntos:
        return list(ev.get("cats_fuente") or [])[:maximo], 0
    orden = sorted(puntos, key=lambda c: -puntos[c])
    return orden[:maximo], sum(puntos.values())


# ---------------------------------------------------------------- valor general (0-60)
FORMATIVO = r"\b(taller|workshop|curso|bootcamp|clase|masterclass|seminario|conferencia|charla|webinar|diplomado|" \
            r"capacitacion|training|laboratorio|lab|simposio|congreso)\b"
NETWORKING = r"\b(meetup|networking|summit|cumbre|foro|feria|expo|encuentro|convencion|jornada|kickoff|" \
             r"demo ?day|comunidad|tech week)\b"
COMPETENCIA = r"\b(hackathon|hackaton|datathon|concurso|competencia|challenge|olimpiada|reto|ideathon)\b"
PUERTAS = r"\b(beca\w*|scholarship\w*|fellowship\w*|intercambio|pasantia|internship|practicas|mentoria|" \
          r"mentoring|call for papers|convocatoria|programa de liderazgo|leadership program|ambassador)\b"
CERTIFICADO = r"\b(certificado|certificacion|constancia|certificate|diploma)\b"
PREMIO = r"\b(premio\w*|prizes?|premiacion|awards?)\b"
UNIVERSIDAD = r"\b(universidad|university|pucp|uni|upc|ulima|utec|esan|ucsur|cientifica del sur|san marcos|unmsm|" \
              r"usil|urp|cayetano heredia|upch|pacifico)\b"
GREMIO = r"\b(camara de comercio|amcham|colegio de ingenieros|ipae|cade|sociedad nacional de industrias|adex|" \
         r"confiep|comexperu|pmi|gs1|ieee|informs|iise|concytec|proinnovate|produce|ministerio|embajada|" \
         r"british council|educationusa|onu|pnud|unesco|unicef|bid|banco mundial|cepal|peru sostenible|tedx)\b"
EMPRESA = r"\b(google|aws|amazon|microsoft|ibm|meta|nvidia|oracle|sap|salesforce|anthropic|openai|bcp|interbank|" \
          r"bbva|scotiabank|alicorp|backus|ferreyros|antamina|mckinsey|deloitte|pwc|kpmg|accenture|mastercard|" \
          r"visa|intel|cisco|huawei|samsung)\b"
VENTA = r"\b(precio especial|cupos limitados|ultimos cupos|oferta|descuento|inversion unica|promocion|sorteo|" \
        r"compra|separa tu cupo|matricula abierta)\b"
LATAM = r"\b(peru|lima|latam|latin\w* america|latinoamerica\w*|hispan\w+|espanol|iberoamerica\w*)\b"
# Sesiones para vender un programa pagado (maestría, diplomado): gratis, pero su fin es la admisión.
PROMO_PROGRAMA = r"\b((conferencia|charla|sesion|reunion) informativa|open house|proceso de admision|admision \d{4}|" \
                 r"informes? (de|sobre) (la )?(maestria|diplomado|programa))\b"


def valor_general(ev):
    """(puntos 0-60, [(razón, puntos), …])."""
    titulo, texto = norm(ev.get("titulo")), _texto(ev)
    razones = []
    base = max([(14, "Formativo") if re.search(FORMATIVO, texto) else (0, ""),
                (13, "Abre puertas (beca/programa)") if re.search(PUERTAS, texto) or ev.get("tipo") in (
                    "convocatoria", "call for papers") else (0, ""),
                (12, "Competencia") if re.search(COMPETENCIA, texto) or ev.get("tipo") == "hackathon" else (0, ""),
                (10, "Networking") if re.search(NETWORKING, texto) else (0, "")])
    razones.append((base[1], base[0]) if base[0] else ("Evento sin formato claro", 4))
    if ev.get("tipo") == "voluntariado":
        razones.append(("Voluntariado", 8))
    if ev.get("institucional"):
        razones.append(("Evento institucional", 10))
        if ev.get("escala") == "grande" and ev.get("gratis") is True and _en_lima(ev):
            razones.append(("Grande, gratis y en Lima", 14))  # networking, visibilidad y CV de alto nivel
    if _en_lima(ev):
        razones.append(("Presencial en Lima", 8))
    elif ev.get("modalidad") == "Virtual":
        razones.append(("Virtual", 3))
    elif ev.get("modalidad") == "Internacional":
        razones.append(("Se postula en línea", 3))
    if ev.get("gratis") is True:
        razones.append(("Gratis", 6))
    else:
        p = precio_soles(ev)
        if p is not None and p <= 60:
            razones.append(("Bajo costo", 3))
    if re.search(CERTIFICADO, texto):
        razones.append(("Con certificado", 3))
    if re.search(PREMIO, texto):
        razones.append(("Con premio", 4))
    org = max((7, "Universidad") if re.search(UNIVERSIDAD, texto) else (0, ""),
              (7, "Gremio o institución") if re.search(GREMIO, texto) else (0, ""),
              (5, "Empresa reconocida") if re.search(EMPRESA, texto) else (0, ""))
    if org[0]:
        razones.append((org[1], org[0]))
    if ev.get("cierre"):
        razones.append(("Plazo claro", 4))
    # penalizaciones
    if re.search(VENTA, texto) and ev.get("gratis") is False:
        razones.append(("Parece venta", -10))
    if re.search(PROMO_PROGRAMA, texto):
        razones.append(("Promociona un programa pagado", -12))
    if len(norm(ev.get("descripcion"))) < 80 and not ev.get("organizador"):
        razones.append(("Poca información", -6))
    if ev.get("tipo") == "hackathon" and not re.search(LATAM, texto):
        razones.append(("Hackathon global sin vínculo con el Perú", -10))
    total = max(0, min(60, sum(p for _, p in razones)))
    return total, razones


def _en_lima(ev):
    if ev.get("modalidad") != "Presencial":
        return False
    lugar = norm(f"{ev.get('lugar', '')} {ev.get('distrito', '')} {ev.get('ciudad', '')}")
    fuera = re.search(r"\b(arequipa|cusco|trujillo|piura|chiclayo|ica|paracas|puno|iquitos|huancayo|tacna)\b", lugar)
    return not fuera and ev.get("fuente") != "Devpost"


# ---------------------------------------------------------------- afinidad personal (perfil.json)
def cargar_perfil(ruta):
    """perfil.json → dict, o None si no existe o está vacío (el radar sigue con el valor general)."""
    try:
        p = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not p or not p.get("areas"):
        return None
    for a in p["areas"]:
        simples = [w for w in a.get("palabras", []) if isinstance(w, str) and w]
        a["_rx"] = re.compile(r"\b(" + "|".join(re.escape(norm(w)) for w in simples) + r")\b") if simples else None
        # Palabras ambiguas que solo cuentan junto a otras: {"palabra": "operaciones", "junto_a": ["logistica", …]}
        a["_ctx"] = [(re.compile(r"\b" + re.escape(norm(w["palabra"])) + r"\b"),
                      re.compile(r"\b(" + "|".join(re.escape(norm(x)) for x in w.get("junto_a", [])) + r")\w*"))
                     for w in a.get("palabras", []) if isinstance(w, dict) and w.get("palabra") and w.get("junto_a")]
    p["_evitar"] = [norm(w) for w in p.get("evitar", []) if w]
    return p


def afinidad(ev, perfil):
    """(puntos 0-tope, [(razón, puntos), …]) según perfil.json. Sin perfil: (0, [])."""
    if not perfil:
        return 0, []
    titulo, texto = norm(ev.get("titulo")), _texto(ev)
    razones = []
    def coincide(zona):
        # palabra simple, o palabra ambigua acompañada de su contexto en cualquier parte del texto
        return bool(a["_rx"] and a["_rx"].search(zona)) or any(p.search(zona) and c.search(texto) for p, c in a["_ctx"])

    for a in perfil["areas"]:
        if coincide(titulo):
            razones.append((f"Afín: {a['nombre']}", round(a.get("peso", 5) * 1.5)))
        elif coincide(texto):
            razones.append((f"Afín: {a['nombre']}", a.get("peso", 5)))
    for w in perfil["_evitar"]:
        if re.search(r"\b" + re.escape(w) + r"\b", texto):
            razones.append((f"Evitas «{w}»", -15))
    tope = perfil.get("tope", 40)
    return max(0, min(tope, sum(p for _, p in razones))), razones


def puntuar(ev, perfil):
    """Calcula valor, afinidad, puntaje y la línea de "por qué aparece aquí"."""
    valor, r1 = valor_general(ev)
    afin, r2 = afinidad(ev, perfil)
    ev["valor"], ev["afinidad"], ev["puntaje"] = valor, afin, valor + afin
    positivas = sorted([r for r in r1 + r2 if r[1] > 0], key=lambda r: -r[1])
    negativas = [r for r in r1 + r2 if r[1] < 0]
    ev["por_que"] = " · ".join([n for n, _ in positivas[:4]] + [f"({n})" for n, _ in negativas[:1]])
    return ev


# ---------------------------------------------------------------- recomendados balanceados
def es_imperdible_institucional(e, ahora, dias=7):
    """Institucional grande, gratis y en Lima que empieza (o sigue en curso) dentro de `dias`."""
    from datetime import datetime, timedelta
    if not (e.get("institucional") and e.get("escala") == "grande" and e.get("gratis") is True and _en_lima(e)):
        return False
    try:
        ini = datetime.fromisoformat(e["inicio"])
        fin = datetime.fromisoformat(e.get("fin") or e["inicio"])
    except (KeyError, ValueError):
        return False
    return fin >= ahora and ini <= ahora + timedelta(days=dias)



def recomendados(eventos, ahora, n=8, max_por_tipo=3, min_lima=3, max_por_fuente=3,
                 dias_eventos=14, dias_cierre=45):
    """Los `n` mejores, con cupos: ningún tipo de convocatoria (hackathon, CFP, beca…) ocupa más de
    `max_por_tipo`; al menos `min_lima` eventos presenciales de Lima si existen; y ninguna fuente más de
    `max_por_fuente`. Devuelve la lista de ids."""
    from datetime import timedelta

    def fecha(e):
        from datetime import datetime
        s = e.get("cierre") or (None if e.get("tipo") in ("convocatoria", "voluntariado") else e.get("inicio"))
        return datetime.fromisoformat(s) if s else None

    def en_ventana(e):
        d = fecha(e)
        if not d:
            return False
        tope = dias_eventos if e.get("tipo") in ("evento", None) else dias_cierre
        return d <= ahora + timedelta(days=tope) and (d >= ahora or (e.get("fin") or "") >= ahora.isoformat())

    candidatos = sorted([e for e in eventos if en_ventana(e)], key=lambda e: -e.get("puntaje", 0))
    elegidos, por_tipo, por_fuente = [], {}, {}

    def cabe(e):
        t = e.get("tipo") or "evento"
        return (t == "evento" or por_tipo.get(t, 0) < max_por_tipo) and por_fuente.get(e.get("fuente"), 0) < max_por_fuente

    def agregar(e):
        elegidos.append(e)
        t = e.get("tipo") or "evento"
        por_tipo[t] = por_tipo.get(t, 0) + 1
        por_fuente[e.get("fuente")] = por_fuente.get(e.get("fuente"), 0) + 1

    # Obligatorios: un evento institucional grande, gratis y en Lima que ocurre en ≤7 días entra siempre
    # (caso real: la Cumbre Perú Sostenible quedó fuera con 55 puntos frente a eventos más afines al perfil).
    for e in [e for e in candidatos if es_imperdible_institucional(e, ahora)]:
        if len(elegidos) < n:
            agregar(e)
    for e in [e for e in candidatos if (e.get("tipo") or "evento") == "evento" and _en_lima(e)]:
        if sum(1 for x in elegidos if _en_lima(x)) >= min_lima or len(elegidos) >= n:
            break
        if e not in elegidos and cabe(e):
            agregar(e)
    for e in candidatos:
        if len(elegidos) >= n:
            break
        if e not in elegidos and cabe(e):
            agregar(e)
    for e in candidatos:  # si los cupos dejaron huecos, se completa con lo mejor que quede
        if len(elegidos) >= n:
            break
        if e not in elegidos and ((e.get("tipo") or "evento") == "evento" or por_tipo.get(e.get("tipo"), 0) < max_por_tipo):
            agregar(e)
    elegidos.sort(key=lambda e: -e.get("puntaje", 0))
    return [e["id"] for e in elegidos]
