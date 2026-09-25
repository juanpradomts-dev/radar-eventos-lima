@echo off
title Subir Radar de eventos Lima a GitHub
cd /d "%~dp0"
echo.
echo   1/3  Creando repo publico juanpradomts-dev/radar-eventos-lima y subiendo el codigo...
gh repo create juanpradomts-dev/radar-eventos-lima --public --description "Eventos en Lima que suman como estudiante - se actualiza solo cada 3 h" --source . --push
if errorlevel 1 (
  echo   [!] Fallo la creacion. Si el repo ya existe, se intenta solo el push.
  git push -u origin main
)
echo.
echo   2/3  Activando GitHub Pages (publicado por GitHub Actions)...
gh api -X POST repos/juanpradomts-dev/radar-eventos-lima/pages -f build_type=workflow >nul 2>&1
gh api -X PUT repos/juanpradomts-dev/radar-eventos-lima/pages -f build_type=workflow >nul 2>&1
echo.
echo   3/3  Lanzando la primera actualizacion...
gh workflow run actualizar.yml -R juanpradomts-dev/radar-eventos-lima
echo.
echo   Listo. En ~2 minutos queda en:
echo   https://juanpradomts-dev.github.io/radar-eventos-lima/
echo.
pause
