#!/usr/bin/env bash
set -euo pipefail

# ======== EDITA ESTAS DOS LINEAS ANTES DE PEGAR ========
REPO_URL="${REPO_URL:-https://github.com/TU_USUARIO/justo-backend.git}"
DATABASE_URL="${DATABASE_URL:-PEGA_TU_DATABASE_URL_AQUI}"
# =======================================================

echo ">> [1/6] Zona horaria Argentina"
timedatectl set-timezone America/Argentina/Buenos_Aires || true

echo ">> [2/6] Instalando Docker y git"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y git ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io
systemctl enable --now docker

echo ">> [3/6] Clonando proyecto en /opt/justo"
rm -rf /opt/justo
git clone "$REPO_URL" /opt/justo
cd /opt/justo

echo ">> [4/6] Guardando credenciales (.env)"
printf 'DB_TIPO=postgres\nDATABASE_URL=%s\n' "$DATABASE_URL" > /opt/justo/.env
chmod 600 /opt/justo/.env

echo ">> [5/6] Construyendo imagen Docker (tarda unos minutos)"
docker build -t justo-robots /opt/justo

echo ">> [6/6] Programando corrida diaria 10:00 (hora Argentina)"
cat > /etc/cron.d/justo-robots <<CRON
CRON_TZ=America/Argentina/Buenos_Aires
0 10 * * * root cd /opt/justo && /usr/bin/docker run --rm --env-file /opt/justo/.env justo-robots >> /var/log/justo-robots.log 2>&1
CRON
chmod 0644 /etc/cron.d/justo-robots
systemctl restart cron || service cron restart || true

echo ""
echo ">> Prueba rapida (captura dirigida: testea acceso a las cadenas + escritura en la base)"
docker run --rm --env-file /opt/justo/.env justo-robots python3 backend/scripts/capturar_especifico_justo.py || true

echo ""
echo "=================================================================="
echo " LISTO. Cron diario 10:00 ART instalado."
echo " Ver logs de la corrida diaria:  tail -n 100 /var/log/justo-robots.log"
echo " Correr a mano cuando quieras:   cd /opt/justo && docker run --rm --env-file .env justo-robots"
echo "=================================================================="
