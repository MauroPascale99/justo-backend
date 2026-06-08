# Robots en un VPS en Sao Paulo (region cercana, sin bloqueos)

Objetivo: que los robots corran solos **todos los dias a las 10:00 (hora Argentina)**
en un servidor en Sudamerica, para que ninguna cadena bloquee el scrapeo.
Casi todo se hace con clics; el unico "terminal" es **pegar un bloque** en la consola web del VPS.

Archivos ya listos en `C:\KlavePricing\justo-backend`: `Dockerfile`, `requirements.txt`,
`correr_robots.sh`, `setup_vps.sh`, `actualizar.sh`, `.gitignore`, `.dockerignore`.

---

## Paso 1 - Subir el codigo a GitHub (con GitHub Desktop, sin terminal)

1. Instala **GitHub Desktop** (https://desktop.github.com) e inicia sesion.
2. `File -> Add local repository` -> `C:\KlavePricing\justo-backend`
   (si pide, toca **"create a repository"**).
3. **Publish repository**: nombre `justo-backend`. Podes dejarlo **publico**: es seguro,
   porque tu clave (`.env`) NO se sube (esta en `.gitignore`) y no hay otras credenciales
   en el codigo. Copia la URL del repo (ej: `https://github.com/TU_USUARIO/justo-backend.git`).

> Si preferis repo privado, avisame y te paso la variante con token (un paso extra).

---

## Paso 2 - Crear el VPS en Sao Paulo

Recomiendo **Vultr** (simple y con consola web). Tambien sirve AWS Lightsail (Sao Paulo).

En Vultr (https://www.vultr.com):
1. **Deploy +** -> **Cloud Compute**.
2. Location: **Sao Paulo**.
3. Image: **Ubuntu 24.04 LTS**.
4. Plan: elegi uno de **2 GB de RAM** (1 vCPU / 2 GB; ~US$10/mes). Con 1 GB puede quedar
   justo de memoria en las cadenas grandes.
5. Deploy. Espera ~1 minuto a que diga "Running".

---

## Paso 3 - Abrir la consola web (no necesitas instalar nada)

En el panel del VPS, boton **"View Console"** (Vultr) o **"Connect using browser SSH"**
(Lightsail). Te abre una terminal en el navegador, logueada como **root**.

---

## Paso 4 - Pegar el instalador (editas 2 lineas)

1. Abri `setup_vps.sh` (esta en tu carpeta) y reemplaza:
   - `REPO_URL=` -> la URL de tu repo del Paso 1.
   - `DATABASE_URL=` -> el valor de `DATABASE_URL` de tu `.env`
     (`C:\KlavePricing\justo-backend\.env`).
2. Copia **todo** el contenido del archivo y **pegalo** en la consola del navegador. Enter.
3. El script: instala Docker, baja el codigo, construye, programa el cron de las 10:00 ART,
   y hace una **corrida de prueba** para confirmar que las cadenas responden desde Sao Paulo
   y que escribe en la base.

Cuando termine, deberias ver "LISTO. Cron diario 10:00 ART instalado."

---

## Paso 5 - Verificar

- Ver la ultima corrida:  `tail -n 100 /var/log/justo-robots.log`
- Correr a mano cuando quieras:  `cd /opt/justo && docker run --rm --env-file .env justo-robots`
- Recarga el dashboard: los precios deberian quedar frescos.

---

## Mantenimiento

- **Actualizar el codigo** (cuando cambiemos algo): subis los cambios a GitHub (GitHub Desktop ->
  Commit -> Push) y en el VPS corres:  `cd /opt/justo && bash actualizar.sh`
- **Evitar duplicados**: cuando el VPS este andando, desactiva la tarea de Windows de las 10am
  (`schtasks /delete /tn "Klave Scraping Diario"`).

---

## Costos aproximados

- VPS Vultr Sao Paulo 1 vCPU / 2 GB: ~**US$10/mes**. (1 GB ~US$5, pero puede quedar corto.)
- No hay otros costos: la base sigue en tu Supabase.
