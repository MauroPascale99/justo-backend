#!/usr/bin/env python3
"""Sincroniza el padrón de sucursales desde directorios oficiales.

La tarea es incremental: siempre conserva las direcciones oficiales y sólo
geocodifica las sucursales que todavía no tienen coordenadas.  Así se evita
consultar de nuevo el geocodificador para todo el padrón en cada corrida.

Uso:
    python3 backend/scripts/sincronizar_sucursales_retailers.py --retailer coto
    python3 backend/scripts/sincronizar_sucursales_retailers.py --retailer coto --sin-geocodificar
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Iterable

import psycopg2
import requests
from dotenv import load_dotenv


FUENTE_COTO = "https://www.coto.com.ar/sucursales/"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "JustoAR-Sucursales/1.0 (contacto@ecom360.ar)"


@dataclass(frozen=True)
class Sucursal:
    retailer: str
    codigo_externo: str
    nombre: str
    direccion: str
    localidad: str
    provincia: str
    fuente_url: str


def cargar_coto() -> list[Sucursal]:
    """Extrae el JSON embebido en el directorio oficial de Coto."""
    respuesta = requests.get(FUENTE_COTO, headers={"User-Agent": USER_AGENT}, timeout=60)
    respuesta.raise_for_status()
    coincidencia = re.search(r"const\s+SOURCE_DATA\s*=\s*", respuesta.text)
    if not coincidencia:
        raise RuntimeError("Coto cambió el formato de su directorio de sucursales.")
    datos, _ = json.JSONDecoder().raw_decode(respuesta.text[coincidencia.end():].lstrip())
    sucursales: list[Sucursal] = []
    for region in datos:
        provincia = str(region.get("heading") or "").strip()
        for fila in region.get("rows", []):
            direccion = re.sub(r"\s+", " ", str(fila.get("direccion") or "")).strip()
            nombre = re.sub(r"\s+", " ", str(fila.get("nombre") or "Coto")).strip()
            codigo = str(fila.get("sucursal") or "").strip()
            if not direccion or not codigo:
                continue
            # El sitio usa el último segmento para barrio/localidad en la mayoría
            # de las filas. Conservamos la dirección original sin inventar datos.
            localidad = direccion.rsplit(" - ", 1)[-1].strip() if " - " in direccion else provincia
            sucursales.append(Sucursal("coto", codigo, nombre, direccion, localidad, provincia, FUENTE_COTO))
    return sucursales


def upsertar(conn, sucursales: Iterable[Sucursal]) -> int:
    filas = list(sucursales)
    with conn.cursor() as cur:
        for item in filas:
            cur.execute(
                """
                INSERT INTO public.sucursales_retailer
                    (retailer, codigo_externo, nombre, direccion, localidad, provincia, fuente_url, verificado_en, activa)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now(), true)
                ON CONFLICT (retailer, direccion, localidad) DO UPDATE SET
                    codigo_externo = EXCLUDED.codigo_externo,
                    nombre = EXCLUDED.nombre,
                    provincia = EXCLUDED.provincia,
                    fuente_url = EXCLUDED.fuente_url,
                    verificado_en = now(),
                    activa = true,
                    actualizado_en = now()
                """,
                (item.retailer, item.codigo_externo, item.nombre, item.direccion, item.localidad, item.provincia, item.fuente_url),
            )
    conn.commit()
    return len(filas)


def geocodificar_pendientes(conn, retailer: str, limite: int) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id_sucursal, direccion, localidad, provincia
            FROM public.sucursales_retailer
            WHERE retailer = %s AND activa AND (latitud IS NULL OR longitud IS NULL)
            ORDER BY id_sucursal
            LIMIT %s
            """,
            (retailer, limite),
        )
        pendientes = cur.fetchall()

    actualizadas = 0
    for indice, (id_sucursal, direccion, localidad, provincia) in enumerate(pendientes):
        consulta = ", ".join(x for x in (direccion, localidad, provincia, "Argentina") if x)
        try:
            respuesta = requests.get(
                NOMINATIM,
                params={"q": consulta, "format": "jsonv2", "countrycodes": "ar", "limit": 1},
                headers={"User-Agent": USER_AGENT},
                timeout=45,
            )
            respuesta.raise_for_status()
            resultado = respuesta.json()
            if resultado:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE public.sucursales_retailer SET latitud=%s, longitud=%s, actualizado_en=now() WHERE id_sucursal=%s",
                        (resultado[0]["lat"], resultado[0]["lon"], id_sucursal),
                    )
                conn.commit()
                actualizadas += 1
        except requests.RequestException as exc:
            print(f"[WARN] No se pudo geocodificar sucursal {id_sucursal}: {exc}", file=sys.stderr)
        if indice < len(pendientes) - 1:
            time.sleep(1.1)  # Política pública de Nominatim: máx. una consulta/segundo.
    return actualizadas, len(pendientes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retailer", choices=["coto"], default="coto")
    parser.add_argument("--sin-geocodificar", action="store_true")
    parser.add_argument("--max-geocodificar", type=int, default=200)
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no encontrada en el entorno.")
    conn = psycopg2.connect(url)
    try:
        filas = cargar_coto()
        print(f"Coto: {upsertar(conn, filas)} sucursales oficiales sincronizadas.")
        if not args.sin_geocodificar:
            ok, total = geocodificar_pendientes(conn, args.retailer, args.max_geocodificar)
            print(f"Coto: {ok}/{total} coordenadas completadas en esta corrida.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
