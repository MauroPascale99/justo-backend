#!/usr/bin/env bash
set -e
cd /opt/justo
git pull
docker build -t justo-robots /opt/justo
echo "Actualizado. La proxima corrida usa el codigo nuevo."
