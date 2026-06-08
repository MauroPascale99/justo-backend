@echo off
:: ==========================================================================
:: Corrida diaria de scraping JUSTO / Klave Pricing
:: Lo dispara el Programador de tareas de Windows (10:00 diario).
:: ==========================================================================
cd /d "C:\KlavePricing\justo-backend"

:: Python (ajustar si cambia la instalacion)
set "PYTHON_EXE=C:\Users\USUARIO\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

if not exist "logs_diarios" mkdir logs_diarios

set filename_date=%date:~10,4%%date:~4,2%%date:~7,2%
set filename_date=%filename_date: =0%
set "LOG=logs_diarios\ejecucion_%filename_date%.log"

echo ========================================== >> "%LOG%"
echo [%date% %time%] INICIO DE SCRAPING DIARIO >> "%LOG%"
echo ========================================== >> "%LOG%"

:: 1. VTEX completo (Carrefour, Jumbo, Disco, Vea, Chango Mas)
echo [%date% %time%] Corriendo VTEX Completo... >> "%LOG%"
"%PYTHON_EXE%" -X utf8 backend/scripts/capturar_catalogo_vtex_completo.py >> "%LOG%" 2>&1

:: 2. Coto (catalogo completo)
echo [%date% %time%] Corriendo Coto... >> "%LOG%"
"%PYTHON_EXE%" -X utf8 backend/main.py --fuente coto >> "%LOG%" 2>&1

:: 3. Dia
echo [%date% %time%] Corriendo Dia... >> "%LOG%"
"%PYTHON_EXE%" -X utf8 backend/main.py --fuente dia >> "%LOG%" 2>&1

:: 4. Captura dirigida UNIVERSAL: productos de TODOS los clientes + sus competidores
::    busca por EAN y por marca en CADA cadena (rellena precios de competencia
::    que el catalogo masivo no trae en jumbo/vea/disco/changomas + Coto todas las categorias)
echo [%date% %time%] Corriendo Captura Dirigida Universal (clientes + competidores)... >> "%LOG%"
"%PYTHON_EXE%" -X utf8 backend/scripts/capturar_especifico_justo.py >> "%LOG%" 2>&1

:: 5. Postproceso analitico + actualizacion Supabase
echo [%date% %time%] Corriendo Postproceso Analitico y Supabase... >> "%LOG%"
"%PYTHON_EXE%" -X utf8 backend/scripts/robot_maestro_universal.py --solo-postproceso >> "%LOG%" 2>&1

:: 6. Motor de eventos y alertas
echo [%date% %time%] Corriendo Motor de Eventos de Precios y Alertas... >> "%LOG%"
"%PYTHON_EXE%" -X utf8 backend/scripts/motor_eventos_precio.py >> "%LOG%" 2>&1

echo ========================================== >> "%LOG%"
echo [%date% %time%] FIN DE SCRAPING Y ANALISIS DIARIO >> "%LOG%"
echo ========================================== >> "%LOG%"
