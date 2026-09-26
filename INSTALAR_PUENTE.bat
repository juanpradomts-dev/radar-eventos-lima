@echo off
rem Doble clic UNA vez: registra la tarea "Radar Eventbrite (puente)" cada 3 h
rem (corre puente_silencioso.vbs sin ventana) y la ejecuta ya para probar.
schtasks /Create /F /TN "Radar Eventbrite (puente)" /SC HOURLY /MO 3 /TR "wscript.exe \"%~dp0puente_silencioso.vbs\""
schtasks /Run /TN "Radar Eventbrite (puente)"
echo.
echo Listo. Eventbrite se subira al radar cada 3 h mientras la PC este encendida.
pause
