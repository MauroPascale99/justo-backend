#!/bin/bash

# Obtener directorio del script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Crear carpeta de logs si no existe
mkdir -p logs_diarios

# Formatear fecha para el archivo de log (YYYYMMDD)
FILENAME_DATE=$(date +'%Y%m%d')

echo "==========================================" >> logs_diarios/ejecucion_${FILENAME_DATE}.log
echo "[$(date)] INICIO DE SCRAPING DIARIO" >> logs_diarios/ejecucion_${FILENAME_DATE}.log
echo "==========================================" >> logs_diarios/ejecucion_${FILENAME_DATE}.log

# 1. Ejecutar el scraper de VTEX para todas las cadenas (Carrefour, Jumbo, Disco, Vea, Chango Mas)
echo "[$(date)] Corriendo VTEX Completo (Carrefour, Jumbo, Disco, Vea, Chango Mas)..." >> logs_diarios/ejecucion_${FILENAME_DATE}.log
python3 backend/scripts/capturar_catalogo_vtex_completo.py >> logs_diarios/ejecucion_${FILENAME_DATE}.log 2>&1

# 2. Ejecutar Coto
echo "[$(date)] Corriendo Coto..." >> logs_diarios/ejecucion_${FILENAME_DATE}.log
python3 backend/main.py --fuente coto >> logs_diarios/ejecucion_${FILENAME_DATE}.log 2>&1

# 3. Ejecutar Dia
echo "[$(date)] Corriendo Dia..." >> logs_diarios/ejecucion_${FILENAME_DATE}.log
python3 backend/main.py --fuente dia >> logs_diarios/ejecucion_${FILENAME_DATE}.log 2>&1

# 4. Ejecutar postproceso analítico (maestro postproceso) y actualizar Supabase
echo "[$(date)] Corriendo Postproceso Analítico y Actualización Supabase..." >> logs_diarios/ejecucion_${FILENAME_DATE}.log
python3 backend/scripts/robot_maestro_universal.py --solo-postproceso >> logs_diarios/ejecucion_${FILENAME_DATE}.log 2>&1

# 5. Ejecutar motor de eventos y alertas
echo "[$(date)] Corriendo Motor de Eventos de Precios y Alertas..." >> logs_diarios/ejecucion_${FILENAME_DATE}.log
python3 backend/scripts/motor_eventos_precio.py >> logs_diarios/ejecucion_${FILENAME_DATE}.log 2>&1

echo "==========================================" >> logs_diarios/ejecucion_${FILENAME_DATE}.log
echo "[$(date)] FIN DE SCRAPING Y ANALISIS DIARIO" >> logs_diarios/ejecucion_${FILENAME_DATE}.log
echo "==========================================" >> logs_diarios/ejecucion_${FILENAME_DATE}.log
