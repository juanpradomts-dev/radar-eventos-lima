# Radar Lima

(Antes "Radar de Oportunidades"; nombre visible cambiado el 2026-09-27. La URL no cambia.)

Eventos en Lima que suman como estudiante (charlas, talleres, meetups técnicos, congresos, cumbres y ferias) y convocatorias abiertas (hackathons, becas y programas, calls for papers, voluntariados), sin conciertos ni fiestas. **Nada se descarta:** lo que no pasa el filtro (recreativo, vencido, fuera del Perú, artículos que no son convocatorias…) queda en la sección **Archivo** con su motivo.

Publicado en https://juanpradomts-dev.github.io/radar-eventos-lima/ · se actualiza solo cada 3 h (GitHub Actions → Pages).

## Cómo ordena (puntaje 0-100)
- **Valor general (0-60)**, igual para cualquier estudiante y carrera (`puntaje.py`): formativo > networking > recreativo; suma si es presencial en Lima, gratis o de bajo costo, con certificado o premio, organizado por una universidad, gremio o empresa reconocida, con plazo claro, o si es un evento institucional grande, gratis y en Lima; resta la venta disfrazada, la promoción de programas pagados, la poca información y los hackathons globales sin vínculo con el Perú.
- **Afinidad personal (0-40)**, desde `perfil.json` (áreas con peso y palabras clave, palabras a evitar). Edítalo cuando cambien tus intereses; si lo borras, el radar usa solo el valor general.
- Cada tarjeta muestra en una línea (✨) **por qué aparece**.
- **Recomendados** balanceados: 8, máximo 3 por tipo de convocatoria (hackathon, CFP, beca…) y al menos 3 eventos presenciales de Lima si existen.
- **Gratis**: si el texto trae un precio (S/, US$, preventa, costo, entrada), no es gratis aunque la fuente diga lo contrario.

## Fuentes
- Eventos (`eventos.py`): Luma, Eventbrite, Meetup (iCal por grupo), agenda PUCP, y eventos de redes agregados a mano en `manuales.json`.
- Convocatorias (`fuentes_extra.py`): Devpost, WikiCFP, Opportunity Desk, Opportunities for Youth y TEDx Perú.
- **Institucionales** (`institucionales.py` + `institucionales.json`): lista de vigilancia de cumbres, foros, congresos y ferias que viven en la web del organizador (Cumbre Perú Sostenible, CADE/IPAE, ESAN, PMI Lima, CCL, AmCham, CIP, universidades, gremios, ministerios, ONG…). Extracción genérica: JSON-LD → `.ics` → `<time>` → fechas en español. Agrega una fila al JSON para vigilar otra web.
  - **Por confirmar**: titulares de Bing News (cumbre, foro, congreso, summit o feria, más Lima y el año) que aún no están en el radar. El RSS de Google News lo prohíbe su `robots.txt`.
  - **Se viene** (`recurrentes.json`): eventos anuales o bienales (CADE, Cumbre Perú Sostenible, PERUMIN, Expoalimentaria, Expomina…) con su mes habitual y ediciones verificadas en prensa; aparecen ~2 meses antes aunque su web aún no publique fechas. IPAE bloquea a los servidores de GitHub, así que CADE vive aquí y no se raspa.
  - Las webs que no tienen una agenda legible quedan en `institucionales.json → descartadas` con la nota del porqué.
- **Eventbrite online** (`eventbrite_online` en `eventos.py`): lo virtual no tiene ciudad, así que se busca por tema.
  - La API ya filtra: solo gratis y en español.
  - Entran tecnología, datos, ingeniería e investigación de cualquier país, y lo que organizan universidades y escuelas de negocios.
  - Negocios y habilidades entran solo si son de Latinoamérica y tienen formato de clase (webinar, taller, masterclass…).
  - Además: horario de 7:00 a 22:00 en Lima, fuera cripto, trámites y servicios locales de EE. UU. o España, y la hora se convierte a la de Lima.
  - Hasta 80 por corrida. Lo que no pasa el filtro no se recolecta.
- **IEEE Perú** (`ieee_peru` en `eventos.py`): eventos de las ramas estudiantiles IEEE del Perú (UNI, San Marcos, PUCP, UPC, Callao…), tomados de la API pública de IEEE vTools.
  - Su `robots.txt` pide 60 s entre peticiones y la API no filtra por país. Por eso se hace **una** consulta al día como máximo, guardada en `cache/vtools_peru.json`, y se queda solo la Sección Perú (`R90721`).
  - Quedan fuera las reuniones internas (ExCom, officers).
- **Añadidos a mano** (`agregar_manual.py` + `.github/workflows/agregar.yml`): el panel (`/linktree/`) tiene un formulario **"➕ Añadir un evento"** para lo visto en Instagram, LinkedIn, WhatsApp o un cartel.
  - El formulario dispara el workflow "Agregar evento". Ese workflow valida, detecta la red, evita duplicados y guarda el evento en `manuales.json` (nunca borra). Luego pasa los tests y publica.
  - Al final del radar aparecen los botones del dueño ("➕ Añadir un evento", "🔗 Actualizar Linktree"), solo en el navegador donde está conectada su llave.
- **Inscripciones (Linktree)** (`inscripciones.py` + `inscripciones.json`): muchas organizaciones anuncian en Instagram y ponen el enlace de inscripción en su Linktree.
  - Linktree prohíbe robots (`User-agent: *` → `Disallow: /`), así que el radar no lo recorre. Cuando alguien comparte un Linktree, JARVIS lo abre a pedido y copia sus enlaces de inscripción a `inscripciones.json`.
  - En cada corrida, el radar lee solo el **destino** de cada enlace y revisa `robots.txt` en cada salto: un bit.ly puede llevar a un sitio que lo prohíbe.
  - De Google Forms saca el título, la fecha, la hora y el lugar desde la descripción. Si el formulario deja de aceptar respuestas, el evento pasa al Archivo como "inscripciones cerradas".
  - No se pueden leer solos los formularios de Microsoft Forms (prohíbe robots) ni los que son solo para cuentas de la organización. Esos se muestran arriba en la página, en la sección **"📝 Inscripciones abiertas"**, con su nombre y su enlace.
  - **Botón para actualizar** (solo a pedido; nunca con horario): la página https://juanpradomts-dev.github.io/radar-eventos-lima/linktree/ dispara el workflow `Actualizar Linktree` (`.github/workflows/linktree.yml`).
    - Ese workflow ejecuta `linktree_lector.py`, guarda `inscripciones.json` y pide publicar el radar.
    - El botón exige una llave de GitHub (fine-grained, Actions: Read and write sobre este repo) que el dueño pega una vez y queda solo en su navegador. Nunca está en el código.
    - La página no se enlaza desde el radar y lleva `noindex`.
    - El mismo lector lo usan el botón local de JARVIS (`jarvis/tools/linktree.py`) y el comando `/linktree`.
- Todas son públicas, sin login, y se consultan respetando `robots.txt`; si una falla, cae sola sin tumbar las demás. Los feeds RSS reintentan ante un 429 (respetando `Retry-After`) y, si igual fallan, usan la última respuesta buena guardada en `cache/` (máx. 14 días); la página lo indica como "copia del …".

## Control de calidad (`verificar.py`)
Antes de publicar, cada evento pasa por un verificador. Nunca borra nada: todo lo que corrige conserva el dato de la fuente en `original`.

| Nivel | Cuándo | Ejemplos |
|---|---|---|
| **Corregido** | El dato está mal y se arregla con certeza. | Título en MAYÚSCULAS → formato legible (respeta siglas y números romanos). HTML o acentos rotos. Fin anterior al inicio. Fin no creíble (11:00–23:50 el mismo día). "Webinar" marcado como presencial. Descripción que solo repite el título. |
| **Aviso** | Algo raro que no se arregla solo. | Hora poco probable (10:18) → la página dice "Hora por confirmar". Presencial sin dirección. Fecha a más de 18 meses. Enlace que respondió 404 una vez. |
| **Al Archivo** | No se puede publicar tal cual. | Sin enlace. Fecha ilegible. Ya pasó o ya cerró. Duplicado del mismo día (queda el más completo). Enlace roto (404/410) en dos revisiones seguidas. |

**Enlaces.** Se comprueban hasta 40 por corrida, cada uno como máximo una vez por semana y respetando `robots.txt`. El resultado se guarda en `cache/enlaces.json`. Los 403, 405, 429 y los timeouts suelen ser bloqueos a robots, así que no cuentan como rotos.

**Monitoreo.** En `cache/verificacion.json` quedan las últimas 30 corridas. Una fuente pasa a "en observación" si ≥40 % de sus eventos tiene problemas que no se arreglan solos, o si la proporción de eventos con cualquier nota sube 25 puntos respecto de la corrida anterior (señal de que la fuente cambió su web).

**Dónde se ve.** En la página: "✔ verificadas" y la sección "Control de calidad". En GitHub Actions, en el resumen de cada corrida.

## Logo e íconos (`marca/`)

`marca/logo.svg` es el logo: un pin de ubicación con un radar dentro. De ahí salen el ícono de la pestaña
(`favicon.ico`), el ícono del celular (`apple-touch-icon.png`, `icono-192.png`, `icono-512.png`, `manifest.webmanifest`)
y la vista previa al compartir el enlace (`og.png`, 1200 × 630). Si cambias el logo, regenera las imágenes en la PC
con `python marca/generar_marca.py` (usa Chrome); `eventos.py` las copia a `site/` en cada publicación.

## Uso local
```
pip install requests icalendar
python -m unittest -v test_radar     # tests sin red (fixture de la Cumbre en tests/fixtures/)
python eventos.py [--abrir] [--perfil ""]    # --perfil "" = sin afinidad personal
```
Genera `eventos.json` (historial: no borrar) y `site/index.html`, `site/eventos.ics`, `site/top.ics`.

## Volver atrás
- Antes de los ajustes (institucionales, recurrentes, falsos positivos): `git checkout respaldo-pre-ajustes-2026-09-26`.
- Antes de la mejora de puntaje: `git checkout respaldo-pre-mejora-2026-09-26` (para ver) o `git revert` del merge (para deshacer en `main`). Copia completa en `Claudio/respaldos/radar-eventos-lima_2026-09-26/`.
- Versión original (solo Lima, con descartes): `git checkout original-2026-09-26`.
