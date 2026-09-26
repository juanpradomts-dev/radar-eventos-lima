"""Tests mínimos del radar (sin red): `python -m unittest -v test_radar` (también corren con pytest).

Cubren: precio en el texto gana a la bandera "gratis" de la fuente; máximo 2 categorías; posts de blog y
convocatorias de otra región van al Archivo; cupos de Recomendados; detección de la Cumbre Perú Sostenible
desde un HTML guardado; y que todo funciona sin perfil.json.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import eventos
import fuentes_extra
import institucionales
import puntaje

RAIZ = Path(__file__).resolve().parent
LIMA = eventos.LIMA


def ev(titulo, **kw):
    base = {"id": "t:" + titulo, "titulo": titulo, "tipo": "evento", "inicio": "", "fin": "", "cierre": "",
            "lugar": "", "distrito": "Lima", "modalidad": "Presencial", "url": "https://x", "fuente": "Luma",
            "organizador": "Org", "descripcion": "", "gratis": None, "imagen": "", "inscripcion": "https://x",
            "fuente_url": "https://x"}
    base.update(kw)
    return base


class Gratis(unittest.TestCase):
    def test_precio_en_el_texto_gana_a_la_bandera_de_la_fuente(self):
        # Caso real: Luma lo marcaba gratis y cuesta S/99.
        e = ev("[Workshop] Automatiza tu OS con n8n + Notion", gratis=True,
               descripcion="Costo del workshop Precio de preventa: S/99 (sube a S/159 el 21 septiembre).")
        self.assertIs(puntaje.es_gratis(e), False)

    def test_otras_senales_de_precio(self):
        for d in ("Entrada general: S/ 40", "Preventa hasta el viernes", "Costo: USD 4,90", "Inversión: $120",
                  "Entradas desde 35 soles"):
            self.assertIs(puntaje.es_gratis(ev("Charla", gratis=True, descripcion=d)), False, d)

    def test_gratis_explicito_y_null_sin_senal(self):
        self.assertIs(puntaje.es_gratis(ev("Charla", descripcion="Evento gratuito. Costo: Gratuito")), True)
        self.assertIs(puntaje.es_gratis(ev("Charla", descripcion="Entrada libre previa inscripción")), True)
        self.assertIsNone(puntaje.es_gratis(ev("Charla", descripcion="Nos vemos el jueves.")))
        # "free coffee" o "software libre" no hacen gratis un evento
        self.assertIsNone(puntaje.es_gratis(ev("Meetup", descripcion="Free coffee y software libre")))

    def test_premios_no_son_precio(self):
        e = ev("Hackathon", tipo="hackathon", gratis=True, descripcion="Hackathon online. Premios: $10,000 en total.")
        self.assertIs(puntaje.es_gratis(e), True)


class Categorias(unittest.TestCase):
    def test_maximo_dos_y_las_de_mayor_coincidencia(self):
        e = ev("Taller de Python y Power BI para supply chain: IA, datos, logística y liderazgo con beca",
               descripcion="python sql datos analytics dashboard logistica lean operaciones")
        cats, _ = puntaje.categorias(e)
        self.assertLessEqual(len(cats), 2)
        self.assertIn("Datos y analítica", cats)

    def test_voluntariado_solo_si_el_tipo_o_el_texto_lo_dicen(self):
        cats, _ = puntaje.categorias(ev("Foro de impacto social y ODS en comunidades"))
        self.assertNotIn("Voluntariado e impacto social", cats)
        cats, _ = puntaje.categorias(ev("Programa de liderazgo", tipo="voluntariado"))
        self.assertIn("Voluntariado e impacto social", cats)
        cats, _ = puntaje.categorias(ev("Buscamos voluntarios para la feria"))
        self.assertIn("Voluntariado e impacto social", cats)


class RuidoConvocatorias(unittest.TestCase):
    def test_posts_de_blog_van_al_archivo(self):
        for t in ("10 Ways to Stand Out in Scholarship Applications", "How to Write a Winning Essay",
                  "Tips for Investing in Stocks as a Student"):
            self.assertIn("no es una convocatoria", fuentes_extra.motivo_ruido(t), t)

    def test_restringidas_a_otra_region_van_al_archivo(self):
        for t in ("EvalYouth Asia 2026 Core Group: Call for Applications", "UNICEF Club Registration 2026 (UNICEF USA)",
                  "Caribbean Biodiversity Fund Board of Directors 2026", "African Leaders Fellowship 2027"):
            self.assertIn("restringido", fuentes_extra.motivo_ruido(t), t)

    def test_convocatorias_abiertas_pasan(self):
        for t in ("McKinsey Forward Program Fall 2026", "Global Youth Leadership Fellowship for Latin America",
                  "Chevening Scholarships 2027 (international)"):
            self.assertIsNone(fuentes_extra.motivo_ruido(t), t)


class Recomendados(unittest.TestCase):
    def test_cupos(self):
        ahora = datetime(2026, 9, 26, 12, 0, tzinfo=LIMA)
        cierre = (ahora + timedelta(days=10)).isoformat()
        pronto = (ahora + timedelta(days=3)).isoformat()
        lista = [ev(f"Hackathon {i}", tipo="hackathon", fuente="Devpost", modalidad="Virtual", cierre=cierre,
                    inicio=pronto, puntaje=90 - i) for i in range(6)]
        lista += [ev(f"CFP {i}", tipo="call for papers", fuente="WikiCFP", modalidad="Internacional",
                     inicio=pronto, puntaje=80 - i) for i in range(5)]
        lista += [ev(f"Taller Lima {i}", fuente=f"F{i}", inicio=pronto, puntaje=30 - i) for i in range(4)]
        ids = puntaje.recomendados(lista, ahora)
        elegidos = [e for e in lista if e["id"] in ids]
        self.assertEqual(len(ids), 8)
        for tipo in ("hackathon", "call for papers"):
            self.assertLessEqual(sum(e["tipo"] == tipo for e in elegidos), 3, tipo)
        self.assertGreaterEqual(sum(e["tipo"] == "evento" and e["modalidad"] == "Presencial" for e in elegidos), 3)


class Institucionales(unittest.TestCase):
    def test_cumbre_peru_sostenible_se_detecta_con_sus_fechas(self):
        html = (RAIZ / "tests" / "fixtures" / "cumbre_perusostenible.html").read_text(encoding="utf-8")
        conf = json.loads((RAIZ / "institucionales.json").read_text(encoding="utf-8"))
        fuente = next(f for f in conf["fuentes"] if "cumbre.perusostenible.org" in f["url"])
        ahora = datetime(2026, 9, 20, tzinfo=LIMA)
        out = institucionales.extraer(fuente, html, ahora, ahora + timedelta(days=180))
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(e["titulo"], "Cumbre Perú Sostenible 2026")
        self.assertEqual(e["inicio"][:10], "2026-09-24")
        self.assertEqual(e["fin"][:10], "2026-09-26")
        self.assertIs(e["gratis"], True)
        self.assertIn("Lima", e["lugar"])
        self.assertTrue(e["institucional"])

    def test_fechas_en_espanol(self):
        f = lambda s, a=None: [(i.date().isoformat(), j.date().isoformat()) for i, j, _ in institucionales.fechas_es(s, a)]
        self.assertEqual(f("Jueves 24, viernes 25 y sábado 26 de septiembre, 2026"), [("2026-09-24", "2026-09-26")])
        self.assertEqual(f("del 3 al 5 de octubre de 2026"), [("2026-10-03", "2026-10-05")])
        self.assertEqual(f("Del 23 de noviembre al 02 de diciembre", "2026"), [("2026-11-23", "2026-12-02")])
        self.assertEqual(f("5 de noviembre"), [])  # sin año y sin contexto: no se adivina

    def test_grande_gratis_y_en_lima_tiene_bonus_alto(self):
        base = ev("Cumbre de ejemplo 2026", fuente="Institucional", gratis=True, descripcion="Plenarias y paneles.")
        normal, _ = puntaje.valor_general(dict(base))
        grande, _ = puntaje.valor_general(dict(base, institucional=True, escala="grande"))
        self.assertGreaterEqual(grande - normal, 20)


class SinPerfil(unittest.TestCase):
    def test_sin_perfil_json_funciona(self):
        self.assertIsNone(puntaje.cargar_perfil(RAIZ / "no-existe.json"))
        e = puntaje.puntuar(ev("Taller de Excel gratuito en la PUCP", descripcion="Taller gratuito con certificado."), None)
        self.assertEqual(e["afinidad"], 0)
        self.assertGreater(e["valor"], 0)
        self.assertTrue(e["por_que"])

    def test_pipeline_completo_sin_red_y_sin_perfil(self):
        ahora = datetime.now(LIMA)
        en = lambda d: (ahora + timedelta(days=d)).isoformat(timespec="minutes")
        falsos = [ev("Taller de Power BI para operaciones", inicio=en(3), fin=en(3), descripcion="Taller gratuito."),
                  ev("Fiesta de fin de mes", inicio=en(2), fin=en(2)),
                  ev("Congreso de logística", inicio=en(-5), fin=en(-4))]
        viejo = (eventos.FUENTES, eventos.enriquecer, eventos.DATOS, eventos.CARPETA, eventos.PAGINA)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                eventos.FUENTES = {"Prueba": lambda lim: [dict(x) for x in falsos]}
                eventos.enriquecer = lambda e: e
                eventos.DATOS, eventos.CARPETA = Path(tmp) / "eventos.json", Path(tmp) / "site"
                eventos.PAGINA = eventos.CARPETA / "index.html"
                lista, archivo, estado, total = eventos.recolectar(60, None)
                datos = eventos.guardar(lista, archivo, estado, total, {"perfil": False, "recomendados": []})
                pagina = eventos.generar_html(datos)
                self.assertEqual([e["titulo"] for e in lista], ["Taller de Power BI para operaciones"])
                self.assertEqual({e["motivo"].split(" (")[0] for e in archivo}, {"recreativo o de venta", "ya pasó"})
                self.assertIn("Radar de Oportunidades", pagina.read_text(encoding="utf-8"))
            finally:
                eventos.FUENTES, eventos.enriquecer, eventos.DATOS, eventos.CARPETA, eventos.PAGINA = viejo


if __name__ == "__main__":
    unittest.main()
