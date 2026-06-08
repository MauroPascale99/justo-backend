FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=America/Argentina/Buenos_Aires

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x correr_robots.sh

# Corre el pipeline una vez y termina. El scheduler (cron de Railway/Render)
# lo dispara todos los dias a horario.
CMD ["bash", "correr_robots.sh"]
