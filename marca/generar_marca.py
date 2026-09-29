"""Genera los íconos y la vista previa de Radar Lima a partir de marca/logo.svg.

Se corre a mano (en la PC, con Chrome instalado) solo cuando cambia el logo; las imágenes quedan guardadas en
marca/ y eventos.py las copia a site/ en cada publicación. GitHub Actions no necesita Chrome.

    python marca/generar_marca.py
"""
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

AQUI = Path(__file__).resolve().parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
LOGO = (AQUI / "logo.svg").read_text(encoding="utf-8")
FUENTES = ('<link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,500'
           '&family=Outfit:wght@700;800&display=swap" rel="stylesheet">')

# ícono de celular: fondo azul de la portada a sangre (iOS y Android le ponen sus propias esquinas); el pin ocupa
# el 62 % del alto, dentro de la zona segura de los íconos "maskable" (círculo del 80 %)
ICONO = f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:512px;height:512px;overflow:hidden}}
body{{background:linear-gradient(135deg,#2A56A8,#0D2960);display:grid;place-items:center}}
svg{{width:318px;height:318px;filter:drop-shadow(0 10px 18px rgba(0,0,0,.28))}}</style></head><body>{LOGO}</body></html>"""

# ícono de pestaña: solo el pin, fondo transparente
PESTANA = f"""<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;width:256px;height:256px;overflow:hidden;background:transparent}}
svg{{width:256px;height:256px;display:block}}</style></head><body>{LOGO}</body></html>"""

# vista previa al compartir el enlace (WhatsApp, LinkedIn, Telegram): 1200 × 630
VISTA = f"""<!doctype html><html><head><meta charset="utf-8">{FUENTES}<style>
html,body{{margin:0;width:1200px;height:630px;overflow:hidden}}
body{{background:repeating-radial-gradient(circle at 100% 100%,rgba(255,255,255,.07) 0 2px,transparent 2px 86px),
  linear-gradient(135deg,#1D428A,#0D2960);color:#fff;position:relative;
  display:flex;align-items:center;gap:56px;padding:0 96px;box-sizing:border-box;font-family:"DM Sans",sans-serif}}
svg{{width:250px;height:250px;flex:0 0 auto;filter:drop-shadow(0 14px 26px rgba(0,0,0,.3));position:relative;z-index:1}}
.t{{position:relative;z-index:1}}
h1{{font:800 112px/1 "Outfit",sans-serif;margin:0 0 22px;letter-spacing:-.01em}}
h1 b{{color:#FFB27F;font-weight:inherit}}
p{{font-size:38px;line-height:1.3;margin:0 0 30px;opacity:.93;max-width:720px}}
span{{display:inline-block;font-size:26px;background:rgba(255,255,255,.14);border-radius:999px;padding:10px 24px}}
</style></head><body>{LOGO}<div class="t"><h1>Radar <b>Lima</b></h1>
<p>Eventos, talleres y becas para crecer como estudiante</p><span>Se actualiza solo cada 3 horas</span></div></body></html>"""


def foto(html, ancho, alto, destino, transparente=False):
    with tempfile.TemporaryDirectory() as tmp:
        pagina = Path(tmp) / "p.html"
        pagina.write_text(html, encoding="utf-8")
        extra = ["--default-background-color=00000000"] if transparente else []
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=6000",
                        f"--window-size={ancho},{alto}", *extra, f"--screenshot={destino}", pagina.as_uri()],
                       check=True, capture_output=True, timeout=90)


def main():
    grande = AQUI / "icono-512.png"
    foto(ICONO, 512, 512, grande)
    img = Image.open(grande).convert("RGB")
    img.save(grande, optimize=True)
    img.resize((192, 192), Image.LANCZOS).save(AQUI / "icono-192.png", optimize=True)
    img.resize((180, 180), Image.LANCZOS).save(AQUI / "apple-touch-icon.png", optimize=True)

    pin = AQUI / "_pin.png"
    foto(PESTANA, 256, 256, pin, transparente=True)
    Image.open(pin).convert("RGBA").save(AQUI / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    pin.unlink()

    vista = AQUI / "og.png"
    foto(VISTA, 1200, 630, vista)
    Image.open(vista).convert("RGB").save(vista, optimize=True)
    for f in sorted(AQUI.glob("*.png")) + [AQUI / "favicon.ico"]:
        print(f.name, f.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
