# Radar de Oportunidades

Eventos en Lima que suman como estudiante (charlas, talleres, meetups técnicos, congresos) y convocatorias abiertas (hackathons en línea, becas y programas, calls for papers, voluntariados), sin conciertos ni fiestas. **Nada se descarta:** lo que no pasa el filtro (recreativo, vencido, presencial fuera del Perú…) queda en la sección **Archivo** de la página, con su motivo.

- Fuentes de eventos (`eventos.py`): Luma, Eventbrite, Meetup (iCal por grupo), agenda PUCP y eventos de redes agregados a mano en `manuales.json`.
- Fuentes de convocatorias (`fuentes_extra.py`, traídas del Radar de Crecimiento): Devpost, WikiCFP, Opportunity Desk, Opportunities for Youth y TEDx Perú.
- Todas son públicas, sin login, y se consultan respetando `robots.txt`.

Se actualiza solo cada 3 h con GitHub Actions y se publica en GitHub Pages (la dirección sigue siendo `/radar-eventos-lima/`). También genera `eventos.ics` y `top.ics` para suscribirse desde Google Calendar; en las convocatorias se agenda el día de cierre.

Local: `pip install requests icalendar && python eventos.py` → `site/index.html`.

Versión anterior (solo Lima, con descartes): tag `original-2026-09-26`.
