@echo off
REM ==========================================================================
REM Genera el Excel diario de vigilancia de precios (Reporte_Vigilancia_Precios.xlsx)
REM Lo usa el Programador de tareas de Windows para la corrida automatica.
REM Si cambia tu instalacion de Python, edita la linea PYTHON_EXE de abajo.
REM ==========================================================================
setlocal
set "PYTHON_EXE=C:\Users\USUARIO\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "SCRIPT=%~dp0backend\scripts\generar_excel_reporte.py"
set "LOGDIR=%~dp0outputs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOG=%LOGDIR%\reporte_diario.log"

echo [%date% %time%] Iniciando generacion de reporte >> "%LOG%"
"%PYTHON_EXE%" "%SCRIPT%" >> "%LOG%" 2>&1
echo [%date% %time%] Finalizado con codigo %ERRORLEVEL% >> "%LOG%"
echo. >> "%LOG%"
endlocal
