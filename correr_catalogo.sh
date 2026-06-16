#!/usr/bin/env bash
# Corrida SEMANAL: catalogo completo de las 5 cadenas VTEX en modo indice
# (--solo-catalogo, sin guardar precios). Sirve para descubrir productos nuevos
# y que un usuario nuevo encuentre los suyos al ingresar.
set -uo pipefail
cd "$(dirname "$0")"

echo "================= INICIO catalogo semanal $(date -u '+%Y-%m-%d %H:%M:%S') UTC ================="
python3 backend/scripts/capturar_catalogo_vtex_completo.py --solo-catalogo
echo "[exit=$?]"
echo "================= FIN catalogo semanal $(date -u '+%Y-%m-%d %H:%M:%S') UTC ================="

# ── Analytics / Share de surtido (ADITIVO, desacoplado) ───────────────────────
# Pasos nuevos que corren DESPUES del scrape. Si fallan NO afectan el scraping
# (ya termino) ni el resto del sistema. Se desactivan con ANALYTICS_SNAPSHOT=0.
if [ "${ANALYTICS_SNAPSHOT:-1}" = "1" ]; then
  echo ""
  echo "----- Analytics: snapshot semanal -----"
  python3 backend/analytics/crear_snapshot_semanal.py || echo "[WARN] snapshot fallo, sigo sin romper nada"
  echo "[exit=$?]"

  echo ""
  echo "----- Analytics: materializar share -----"
  python3 backend/analytics/materializar_share.py || echo "[WARN] materializacion fallo, sigo sin romper nada"
  echo "[exit=$?]"
fi
