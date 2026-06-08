# Poner los robots a correr solos en la nube (Railway / Render)

Esta guia deja tus robots corriendo **todos los dias a las 10:00 (hora Argentina)** en un
servidor, sin depender de tu PC. Pensada para hacerse casi sin terminal.

Los archivos ya estan listos en `C:\KlavePricing\justo-backend`:
`Dockerfile`, `requirements.txt`, `correr_robots.sh`, `render.yaml`, `.gitignore`, `.dockerignore`.

---

## Paso 1 - Subir el codigo a GitHub (sin terminal, con GitHub Desktop)

1. Instala **GitHub Desktop** (https://desktop.github.com) y crea/inicia sesion con tu cuenta GitHub.
2. `File -> Add local repository` -> elegi la carpeta `C:\KlavePricing\justo-backend`.
   - Si te dice que no es un repositorio, toca **"create a repository"**.
3. En `Publish repository`: nombre `justo-backend`, marca **Keep this code private**, y publica.

> Seguridad: tu archivo `.env` (con la clave de la base) **NO se sube** porque ya esta en
> `.gitignore`. La clave la vas a cargar como variable en la plataforma (Paso 3).

---

## Paso 2 - Tener a mano tu DATABASE_URL

Abri `C:\KlavePricing\justo-backend\.env` y copia el valor de `DATABASE_URL`
(la cadena larga que empieza con `postgresql://...`). La vas a pegar en la plataforma.

---

## Opcion A (recomendada) - Railway

1. Entra a https://railway.app e inicia sesion con GitHub.
2. **New Project -> Deploy from GitHub repo** -> elegi `justo-backend`.
   Railway detecta el `Dockerfile` solo y empieza a construir.
3. En el servicio -> pestania **Variables** -> **New Variable**:
   - Nombre: `DATABASE_URL`
   - Valor: (pega el del Paso 2)
4. Pestania **Settings**:
   - **Cron Schedule**: `0 13 * * *`  (eso es 13:00 UTC = **10:00 Argentina**)
   - Guarda. Con el cron puesto, el contenedor corre a horario y se apaga al terminar.
5. Para probar ya mismo: **Deploy** (la primera build ya ejecuta una corrida). Mira los logs.

---

## Opcion B - Render

1. Entra a https://render.com e inicia sesion con GitHub.
2. **New + -> Blueprint** -> conecta el repo `justo-backend`.
   Render lee `render.yaml` y crea un **Cron Job** llamado `justo-robots-diario`.
3. Te va a pedir la variable `DATABASE_URL` -> pega el valor del Paso 2.
4. Listo: corre `0 13 * * *` (10:00 ART). Para probar: boton **Trigger Run** / **Run**.

> Si el Blueprint diera error: **New + -> Cron Job**, conecta el repo, Runtime = **Docker**,
> Schedule = `0 13 * * *`, y agrega la variable `DATABASE_URL`. Es lo mismo a mano.

---

## Paso 4 - Verificar

- En los logs deberias ver `INICIO corrida...`, cada cadena, y `FIN corrida...`.
- Recarga el dashboard: los precios deberian quedar actualizados.

## Paso 5 - Evitar corridas duplicadas

Cuando el servidor ande, **desactiva** la tarea de Windows (`schtasks /delete /tn "Klave Scraping Diario"`),
asi no corre dos veces (PC + nube) y no se pisan.

---

## Nota importante (geografia)

Railway y Render corren en EE.UU./Europa. Algunas cadenas argentinas pueden **bloquear** IPs de
datacenters de afuera. Si en los logs ves muchos errores 403 / timeouts (sobre todo en Coto),
avisame: lo resolvemos con un proxy en Argentina o pasando a un VPS en **Sao Paulo**
(misma idea, region mas cercana). El resto del setup queda igual.
