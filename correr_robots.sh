#!/usr/bin/env bash
# Corrida DIARIA (liviana): refresca precios de los productos de clientes + sus
# competidores en las 7 cadenas, postproceso y alertas. El catalogo completo
# NO va aca (corre 1 vez por semana via correr_catalogo.sh).
set -uo pipefail
cd "$(dirname "$0")"

echo "================= INICIO diaria $(date -u '+%Y-%m-%d %H:%M:%S') UTC ================="

paso () {
  echo ""
  echo "----- $1 -----"
  shift
  python3 "$@"
  echo "[exit=$?]"
}

paso "Captura dirigida (precios clientes + competidores)" backend/scripts/capturar_especifico_justo.py
paso "Postproceso + Supabase" backend/scripts/robot_maestro_universal.py --solo-postproceso
paso "Motor de eventos y alertas" backend/scripts/motor_eventos_precio.py
paso "Purga de historico (retencion)" backend/analytics/purgar_historico.py

echo ""
echo "================= FIN diaria $(date -u '+%Y-%m-%d %H:%M:%S') UTC ================="
