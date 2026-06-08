#!/usr/bin/env bash
# Corrida diaria de los robots JUSTO / Klave Pricing (pensado para contenedor).
# No usa 'set -e': si una cadena falla, igual seguimos con las demas.
set -uo pipefail
cd "$(dirname "$0")"

echo "================= INICIO corrida $(date -u '+%Y-%m-%d %H:%M:%S') UTC ================="

paso () {
  echo ""
  echo "----- $1 -----"
  shift
  python3 "$@"
  echo "[exit=$?]"
}

paso "VTEX completo (Carrefour, Jumbo, Disco, Vea, Chango Mas)" backend/scripts/capturar_catalogo_vtex_completo.py
paso "Coto (catalogo)"        backend/main.py --fuente coto
paso "Dia"                    backend/main.py --fuente dia
paso "Captura dirigida (clientes + competidores, todas las cadenas)" backend/scripts/capturar_especifico_justo.py
paso "Postproceso + Supabase" backend/scripts/robot_maestro_universal.py --solo-postproceso
paso "Motor de eventos y alertas" backend/scripts/motor_eventos_precio.py

echo ""
echo "================= FIN corrida $(date -u '+%Y-%m-%d %H:%M:%S') UTC ================="
