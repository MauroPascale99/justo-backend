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
