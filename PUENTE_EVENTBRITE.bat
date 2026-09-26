@echo off
rem Puente Eventbrite: Eventbrite bloquea (405) las IPs de GitHub, asi que esta PC
rem recolecta Eventbrite y sube eventbrite.json; el push dispara la Action que publica.
rem Lo corre la tarea programada "Radar Eventbrite (puente)" cada 3 h.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
git pull -q --rebase origin main
python eventos.py --puente-eventbrite || exit /b 1
git add eventbrite.json
git diff --cached --quiet && exit /b 0
git commit -q -m "puente eventbrite: datos desde la PC"
git push -q origin main || (git pull -q --rebase origin main && git push -q origin main)
