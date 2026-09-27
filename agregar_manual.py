"""agregar_manual.py — añade al radar un evento que el dueño vio en Instagram, LinkedIn, WhatsApp o un cartel.

Lo llama el workflow "Agregar evento" (botón "➕ Añadir un evento" del panel, solo con la llave de GitHub del dueño).
Recibe el evento como JSON (variable de entorno DATOS o primer argumento), lo valida y lo agrega a manuales.json.
Nunca borra nada. Deja en manuales.json → "ultimo" el resultado, que el panel muestra.

  DATOS='{"titulo": "...", "fecha": "2026-10-10", "hora": "18:30", "url": "https://..."}' python agregar_manual.py
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MANUALES = RAIZ / "manuales.json"
LIMA = timezone(timedelta(hours=-5))
CATEGORIAS = ["Tecnología e IA", "Datos y analítica", "Ingeniería y operaciones", "Negocios y emprendimiento",
              "Investigación y ciencia", "Habilidades y liderazgo", "Idiomas, becas e internacional",
              "Competencias y hackathons", "Voluntariado e impacto social"]


def red_de(url):
    """De dónde vino, según el enlace (lo muestra la tarjeta como fuente)."""
    for patron, nombre in ((r"instagram\.com", "Instagram"), (r"linkedin\.com", "LinkedIn"), (r"tiktok\.com", "TikTok"),
                           (r"facebook\.com|fb\.me", "Facebook"), (r"wa\.me|whatsapp", "WhatsApp"), (r"x\.com|twitter\.com", "X")):
        if re.search(patron, url, re.I):
            return nombre
    return "Añadido a mano"


def validar(d, ahora=None):
    """Devuelve (evento para manuales.json, None) o (None, mensaje de error en lenguaje simple)."""
    ahora = ahora or datetime.now(LIMA)
    texto = lambda k, n: re.sub(r"\s+", " ", str(d.get(k) or "")).strip()[:n]
    titulo = texto("titulo", 160)
    if len(titulo) < 4:
        return None, "Falta el nombre del evento."
    url = texto("url", 600)
    if not re.match(r"https?://", url):
        return None, "El enlace debe empezar con http:// o https:// (el post o la página de inscripción)."
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto("fecha", 10)):
        return None, "Falta la fecha del evento."
    hora = texto("hora", 5) or "00:00"
    if not re.fullmatch(r"\d{2}:\d{2}", hora):
        return None, "La hora no es válida."
    try:
        ini = datetime.fromisoformat(f"{d['fecha']}T{hora}").replace(tzinfo=LIMA)
        fin_txt = texto("fecha_fin", 10)
        fin = datetime.fromisoformat(f"{fin_txt}T23:59").replace(tzinfo=LIMA) if fin_txt else None
    except ValueError:
        return None, "La fecha no es válida."
    if (fin or ini) < ahora - timedelta(days=1):
        return None, "Esa fecha ya pasó."
    if fin and fin < ini:
        return None, "La fecha de término es anterior a la de inicio."
    modalidad = "Virtual" if texto("modalidad", 20).lower().startswith("v") else "Presencial"
    gratis = {"si": True, "sí": True, "no": False}.get(texto("gratis", 3).lower())
    cats = [c for c in d.get("categorias") or [] if c in CATEGORIAS][:2]
    ev = {"titulo": titulo, "inicio": ini.strftime("%Y-%m-%dT%H:%M"), "red": red_de(url), "url": url,
          "modalidad": modalidad, "agregado": ahora.strftime("%Y-%m-%d")}
    if fin:
        ev["fin"] = fin.strftime("%Y-%m-%dT%H:%M")
    for k, n in (("lugar", 150), ("distrito", 60), ("organizador", 120), ("descripcion", 900), ("inscripcion", 600)):
        v = texto(k, n)
        if v and (k != "inscripcion" or re.match(r"https?://", v)):
            ev[k] = v
    if modalidad == "Virtual":
        ev.pop("lugar", None)
        ev.pop("distrito", None)
    elif not ev.get("distrito"):
        ev["distrito"] = "Lima"
    if gratis is not None:
        ev["gratis"] = gratis
    if cats:
        ev["categorias"] = cats
    return ev, None


def agregar(d, ruta=MANUALES, ahora=None):
    ahora = ahora or datetime.now(LIMA)
    conf = json.loads(Path(ruta).read_text(encoding="utf-8")) if Path(ruta).exists() else {"eventos": []}
    ev, error = validar(d, ahora)
    if ev:
        clave = lambda e: (re.sub(r"[^a-z0-9]", "", e["titulo"].lower())[:40], e["inicio"][:10])
        if any(clave(e) == clave(ev) for e in conf.get("eventos", [])):
            ev, error = None, "Ese evento ya estaba en el radar (mismo nombre y fecha)."
    if ev:
        conf.setdefault("eventos", []).append(ev)
    conf["ultimo"] = {"fecha": ahora.isoformat(timespec="minutes"), "ok": bool(ev),
                      "titulo": (ev or {}).get("titulo") or str(d.get("titulo") or "")[:160],
                      "mensaje": "Añadido: aparecerá en el radar en unos minutos." if ev else error}
    Path(ruta).write_text(json.dumps(conf, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return conf["ultimo"]


if __name__ == "__main__":
    crudo = os.environ.get("DATOS") or (sys.argv[1] if len(sys.argv) > 1 else "{}")
    try:
        datos = json.loads(crudo)
    except ValueError:
        datos = {}
    r = agregar(datos if isinstance(datos, dict) else {})
    print(("✔ " if r["ok"] else "✗ ") + r["mensaje"] + " · " + r["titulo"])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as s:
            s.write(f"## ➕ Evento añadido a mano\n\n{'✔' if r['ok'] else '✗'} **{r['titulo']}** — {r['mensaje']}\n")
