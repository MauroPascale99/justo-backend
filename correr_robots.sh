#!/usr/bin/env bash
# Corrida diaria JUSTO / Klave Pricing.
# Modelo de dos niveles:
#  1) CATALOGO (liviano, --solo-catalogo): refresca el indice de busqueda de TODAS
#     las cadenas (productos_fuente) para que un usuario nuevo pueda encontrar sus
#     productos al ingresar. NO guarda historico de precios de todo el catalogo.
#  2) CAPTURA DIRIGIDA: precios reales de los productos de clientes + sus
#     competidores en las 7 cadenas (esto si guarda historico).
#  3) Postproceso + 4) Alertas.
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

paso "Catalogo (indice de busqueda, todas las cadenas - liviano)" backend/scripts/capturar_catalogo_vtex_completo.py --solo-catalogo
paso "Captura dirigida (precios clientes + competidores)" backend/scripts/capturar_especifico_justo.py
paso "Postproceso + Supabase" backend/scripts/robot_maestro_universal.py --solo-postproceso
paso "Motor de eventos y alertas" backend/scripts/motor_eventos_precio.py

echo ""
echo "================= FIN corrida $(date -u '+%Y-%m-%d %H:%M:%S') UTC ================="
