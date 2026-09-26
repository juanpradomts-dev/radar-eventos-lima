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


# ---------------------------------------------------------------- ajustes 2026-09-26
class Respuesta:
    def __init__(self, status, contenido=b"", headers=None):
        self.status_code, self.content, self.headers = status, contenido, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} Client Error")


class FuentesInstitucionales(unittest.TestCase):
    def test_json_ld_con_comas_sobrantes_y_fecha_rota(self):
        # Así lo publica SNI (plugin EventON): JSON inválido y hora con guiones.
        html = '''<script type="application/ld+json">{ "@context": "http://schema.org", "@type": "Event",
          "name": "Webinar: Microempresa", "startDate": "2026-9-29T11-11-00-00", "endDate": "2026-9-29T23-23-50-00",
          "description":"", }</script>''' * 2  # repetido: se deduplica
        f = {"nombre": "SNI", "organizador": "SNI", "url": "https://sni.org.pe/eventos/", "modo": "agenda",
             "tipo_org": "gremio", "escala": "media", "ciudad": "Lima"}
        ahora = datetime(2026, 9, 26, tzinfo=LIMA)
        out = institucionales.extraer(f, html, ahora, ahora + timedelta(days=90))
        self.assertEqual([(e["titulo"], e["inicio"][:16]) for e in out], [("Webinar: Microempresa", "2026-09-29T11:11")])

    def test_modo_sitemap_lee_las_paginas_recientes(self):
        sm = b"""<urlset><url><loc>https://amcham.org.pe/evento/foro-comercio/</loc><lastmod>2026-09-24T09:45:28-05:00</lastmod></url>
                 <url><loc>https://amcham.org.pe/evento/viejo/</loc><lastmod>2024-01-10T09:00:00-05:00</lastmod></url>
                 <url><loc>https://amcham.org.pe/otra-cosa/</loc><lastmod>2026-09-25T09:00:00-05:00</lastmod></url></urlset>"""
        f = {"nombre": "AmCham", "organizador": "AmCham", "url": "https://amcham.org.pe/", "modo": "sitemap",
             "sitemap": "https://amcham.org.pe/sm.xml", "patron": "/evento/", "dias_modificado": 150,
             "tipo_org": "gremio", "escala": "media", "ciudad": "Lima"}
        ahora = datetime(2026, 9, 26, tzinfo=LIMA)
        urls = institucionales._paginas_sitemap(f, lambda u, **k: Respuesta(200, sm), ahora)
        self.assertEqual(urls, ["https://amcham.org.pe/evento/foro-comercio/"])
        html = "<title>Foro El Futuro del Comercio – AmCham Perú</title><p>Jueves 15 de octubre</p><p>Hotel Westin, Lima</p>"
        e = institucionales._evento_de_pagina(f, urls[0], html, ahora, ahora + timedelta(days=365))
        self.assertEqual((e["titulo"], e["inicio"][:10]), ("Foro El Futuro del Comercio", "2026-10-15"))

    def test_lista_de_vigilancia_sin_ipae_y_descartadas_con_nota(self):
        conf = json.loads((RAIZ / "institucionales.json").read_text(encoding="utf-8"))
        self.assertFalse([f for f in conf["fuentes"] if "ipae.pe" in f["url"]])  # CADE sale de recurrentes.json
        self.assertTrue(all(d.get("nota") for d in conf["descartadas"]))


class SeViene(unittest.TestCase):
    def setUp(self):
        self.ruta = RAIZ / "recurrentes.json"

    def test_cade_ejecutivos_aparece_dos_meses_antes(self):
        sv = institucionales.se_viene(self.ruta, [], hoy=datetime(2026, 9, 26, tzinfo=LIMA))
        cade = [x for x in sv if x["nombre"] == "CADE Ejecutivos"]
        self.assertEqual(len(cade), 1)
        self.assertIn("24/11", cade[0]["texto"])
        self.assertIn("Urubamba", cade[0]["ciudad"])

    def test_no_aparece_si_ya_esta_en_la_lista_o_ya_paso(self):
        hoy = datetime(2026, 9, 26, tzinfo=LIMA)
        self.assertFalse([x for x in institucionales.se_viene(self.ruta, [ev("CADE Ejecutivos 2026")], hoy=hoy)
                          if x["nombre"] == "CADE Ejecutivos"])
        diciembre = institucionales.se_viene(self.ruta, [], hoy=datetime(2026, 12, 10, tzinfo=LIMA))
        self.assertFalse([x for x in diciembre if x["nombre"] == "CADE Ejecutivos"])

    def test_bienal_solo_en_su_anio(self):
        nombres = lambda hoy: [x["nombre"] for x in institucionales.se_viene(self.ruta, [], hoy=hoy)]
        self.assertNotIn("PERUMIN Convención Minera", nombres(datetime(2026, 8, 1, tzinfo=LIMA)))
        self.assertIn("PERUMIN Convención Minera", nombres(datetime(2027, 8, 1, tzinfo=LIMA)))

    def test_recurrentes_verificados(self):
        conf = json.loads(self.ruta.read_text(encoding="utf-8"))
        nombres = {r["nombre"] for r in conf["eventos"]}
        self.assertTrue({"CADE Ejecutivos", "CADE Universitario", "Cumbre Perú Sostenible", "Expoalimentaria"} <= nombres)
        self.assertTrue(all(r.get("fuentes") for r in conf["eventos"]))  # cada dato con su fuente pública


class RecomendadosObligatorios(unittest.TestCase):
    def test_institucional_grande_gratis_en_lima_en_7_dias_entra_siempre(self):
        ahora = datetime(2026, 9, 22, 12, 0, tzinfo=LIMA)
        cumbre = ev("Cumbre Perú Sostenible 2026", fuente="Institucional", institucional=True, escala="grande",
                    gratis=True, inicio="2026-09-24T00:00-05:00", fin="2026-09-26T23:59-05:00", puntaje=55)
        otros = [ev(f"Taller afín {i}", fuente=f"F{i}", inicio="2026-09-24T18:00-05:00", puntaje=90 - i)
                 for i in range(10)]
        self.assertIn(cumbre["id"], puntaje.recomendados(otros + [cumbre], ahora))
        lejos = dict(cumbre, id="lejos", inicio="2026-10-10T00:00-05:00", fin="2026-10-12T23:59-05:00")
        self.assertNotIn("lejos", puntaje.recomendados(otros + [lejos], ahora))  # a >7 días compite normal


class FalsosPositivos(unittest.TestCase):
    def setUp(self):
        self.perfil = puntaje.cargar_perfil(RAIZ / "perfil.json")

    def afin_supply(self, titulo, desc=""):
        _, razones = puntaje.afinidad(ev(titulo, descripcion=desc), self.perfil)
        return any("Supply chain" in r for r, _ in razones)

    def test_operaciones_solo_cuenta_con_contexto_logistico(self):
        self.assertFalse(self.afin_supply("Future Banking Experience 2026", "Nuevas operaciones bancarias y pagos."))
        self.assertFalse(self.afin_supply("NextGen Agents", "Agents that automate business operations."))
        self.assertTrue(self.afin_supply("Operaciones de almacén", "Gestión de inventario y logística."))
        self.assertTrue(self.afin_supply("Taller de supply chain"))

    def test_conferencia_informativa_va_al_archivo_como_admision(self):
        lista, archivo = self._pipeline([ev("Conferencia Informativa: Maestría en Gestión de la Energía",
                                           fuente="Institucional", institucional=True)])
        self.assertEqual(lista, [])
        self.assertEqual(archivo[0]["tipo"], "admisión")
        self.assertTrue(archivo[0]["motivo"].startswith("admisión"))
        self.assertFalse(archivo[0]["institucional"])

    def test_webinar_en_el_titulo_es_virtual(self):
        lista, _ = self._pipeline([ev("Webinar: ISO 21001:2025, claves para una gestión educativa sostenible",
                                     fuente="PUCP", descripcion="Seminario gratuito de gestión de la calidad.")])
        self.assertEqual(lista[0]["modalidad"], "Virtual")

    def _pipeline(self, crudos):
        ahora = datetime.now(LIMA)
        for c in crudos:
            c["inicio"] = c["inicio"] or (ahora + timedelta(days=3)).isoformat(timespec="minutes")
            c["fin"] = c["fin"] or c["inicio"]
        viejo = (eventos.FUENTES, eventos.enriquecer)
        try:
            eventos.FUENTES = {"Prueba": lambda lim: [dict(x) for x in crudos]}
            eventos.enriquecer = lambda e: e
            lista, archivo, _, _ = eventos.recolectar(60, None)
            return lista, archivo
        finally:
            eventos.FUENTES, eventos.enriquecer = viejo


class ReintentoYCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.viejo = fuentes_extra.CACHE
        fuentes_extra.CACHE = Path(self.tmp.name)
        fuentes_extra.CACHE_USADO.clear()
        self.url = "https://opportunitiesforyouth.org/category/volunteering/feed/"

    def tearDown(self):
        fuentes_extra.CACHE = self.viejo
        fuentes_extra.CACHE_USADO.clear()
        self.tmp.cleanup()

    def test_429_reintenta_con_espera_y_luego_responde(self):
        respuestas, esperas = [Respuesta(429, headers={"Retry-After": "7"}), Respuesta(200, b"<rss/>")], []
        out = fuentes_extra.descargar(self.url, lambda u, **k: respuestas.pop(0), dormir=esperas.append)
        self.assertEqual(out, b"<rss/>")
        self.assertEqual(esperas, [7])  # respeta Retry-After
        self.assertTrue(fuentes_extra._cache_de(self.url).exists())  # guarda la respuesta buena

    def test_429_persistente_usa_la_ultima_respuesta_buena(self):
        fuentes_extra.descargar(self.url, lambda u, **k: Respuesta(200, b"<rss>bueno</rss>"), dormir=lambda s: None)
        out = fuentes_extra.descargar(self.url, lambda u, **k: Respuesta(429), dormir=lambda s: None)
        self.assertEqual(out, b"<rss>bueno</rss>")
        self.assertIn(self.url, fuentes_extra.CACHE_USADO)

    def test_sin_cache_el_error_se_reporta(self):
        with self.assertRaises(RuntimeError):
            fuentes_extra.descargar(self.url, lambda u, **k: Respuesta(429), dormir=lambda s: None)


if __name__ == "__main__":
    unittest.main()
