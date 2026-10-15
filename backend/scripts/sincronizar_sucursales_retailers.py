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
from html.parser import HTMLParser
from typing import Iterable

import psycopg2
import requests
from dotenv import load_dotenv


FUENTE_COTO = "https://www.coto.com.ar/sucursales/"
FUENTE_CARREFOUR = "https://comerciante.carrefour.com.ar/sucursales"
FUENTES_CENCOSUD = {
    "vea": "https://www.vea.com.ar/api/dataentities/NT/search",
    "jumbo": "https://www.jumbo.com.ar/api/dataentities/NT/search",
    "disco": "https://www.disco.com.ar/api/dataentities/NT/search",
}
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
    latitud: float | None = None
    longitud: float | None = None


class LectorFilasHTML(HTMLParser):
    """Lector mínimo para directorios HTML tabulares, sin dependencia extra."""
    def __init__(self) -> None:
        super().__init__()
        self.filas: list[list[str]] = []
        self._fila: list[str] | None = None
        self._celda: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._fila = []
        elif tag in {"td", "th"} and self._fila is not None:
            self._celda = []

    def handle_data(self, data: str) -> None:
        if self._celda is not None:
            self._celda.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._fila is not None and self._celda is not None:
            texto = re.sub(r"\s+", " ", "".join(self._celda)).strip()
            self._fila.append(texto)
            self._celda = None
        elif tag == "tr" and self._fila is not None:
            if self._fila:
                self.filas.append(self._fila)
            self._fila = None


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


def cargar_carrefour() -> list[Sucursal]:
    """Extrae tiendas del listado oficial de Carrefour para comerciantes."""
    respuesta = requests.get(FUENTE_CARREFOUR, headers={"User-Agent": USER_AGENT}, timeout=60)
    respuesta.raise_for_status()
    lector = LectorFilasHTML()
    lector.feed(respuesta.text)
    sucursales: list[Sucursal] = []
    for indice, fila in enumerate(lector.filas):
        if len(fila) < 2:
            continue
        nombre, direccion = fila[0].strip(), fila[1].strip()
        if not nombre or not direccion or "nombre tienda" in nombre.lower() or "direcci" in direccion.lower():
            continue
        # El directorio no siempre discrimina localidad. Nombre y dirección se
        # conservan textualmente; el geocodificador recibe ambos para resolverla.
        sucursales.append(Sucursal("carrefour", str(indice), nombre, direccion, "", "", FUENTE_CARREFOUR))
    if not sucursales:
        raise RuntimeError("No se encontraron filas de sucursales en Carrefour.")
    return sucursales


def cargar_cencosud(retailer: str) -> list[Sucursal]:
    """Carga tiendas y coordenadas que Cencosud publica en cada localizador."""
    fuente = FUENTES_CENCOSUD[retailer]
    campos = "name,geocoordinates,SellerName,id,country,city,neighborhood,number,postalCode,state,street,address,phone"
    respuesta = requests.get(
        fuente,
        params={"_fields": campos, "_where": "isActive=true", "_sort": "name ASC"},
        headers={"User-Agent": USER_AGENT, "REST-Range": "resources=0-999"},
        timeout=60,
    )
    respuesta.raise_for_status()
    sucursales: list[Sucursal] = []
    for fila in respuesta.json():
        nombre = str(fila.get("name") or "").strip()
        direccion = str(fila.get("address") or "").strip()
        codigo = str(fila.get("id") or fila.get("SellerName") or "").strip()
        coordenadas = str(fila.get("geocoordinates") or "").split(",")
        try:
            latitud, longitud = float(coordenadas[0].strip()), float(coordenadas[1].strip())
        except (ValueError, IndexError):
            latitud = longitud = None
        if not nombre or not direccion or not codigo:
            continue
        sucursales.append(Sucursal(
            retailer, codigo, nombre, direccion,
            str(fila.get("city") or fila.get("neighborhood") or "").strip(),
            str(fila.get("state") or "").strip(), fuente, latitud, longitud,
        ))
    if not sucursales:
        raise RuntimeError(f"No se encontraron sucursales activas de {retailer}.")
    return sucursales


def upsertar(conn, sucursales: Iterable[Sucursal]) -> int:
    filas = list(sucursales)
    with conn.cursor() as cur:
        for item in filas:
            cur.execute(
                """
                INSERT INTO public.sucursales_retailer
                    (retailer, codigo_externo, nombre, direccion, localidad, provincia, fuente_url, latitud, longitud, verificado_en, activa)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), true)
                ON CONFLICT (retailer, direccion, localidad) DO UPDATE SET
                    codigo_externo = EXCLUDED.codigo_externo,
                    nombre = EXCLUDED.nombre,
                    provincia = EXCLUDED.provincia,
                    fuente_url = EXCLUDED.fuente_url,
                    latitud = COALESCE(EXCLUDED.latitud, public.sucursales_retailer.latitud),
                    longitud = COALESCE(EXCLUDED.longitud, public.sucursales_retailer.longitud),
                    verificado_en = now(),
                    activa = true,
                    actualizado_en = now()
                """,
                (item.retailer, item.codigo_externo, item.nombre, item.direccion, item.localidad, item.provincia, item.fuente_url, item.latitud, item.longitud),
            )
    conn.commit()
    return len(filas)


def geocodificar_pendientes(conn, retailer: str, limite: int) -> tuple[int, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id_sucursal, nombre, direccion, localidad, provincia
            FROM public.sucursales_retailer
            WHERE retailer = %s AND activa AND (latitud IS NULL OR longitud IS NULL)
            ORDER BY id_sucursal
            LIMIT %s
            """,
            (retailer, limite),
        )
        pendientes = cur.fetchall()

    actualizadas = 0
    for indice, (id_sucursal, nombre, direccion, localidad, provincia) in enumerate(pendientes):
        consulta = ", ".join(x for x in (direccion, localidad, provincia, nombre, "Argentina") if x)
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
    parser.add_argument("--retailer", choices=["coto", "carrefour", "vea", "jumbo", "disco"], default="coto")
    parser.add_argument("--sin-geocodificar", action="store_true")
    parser.add_argument("--max-geocodificar", type=int, default=200)
    args = parser.parse_args()

    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no encontrada en el entorno.")
    conn = psycopg2.connect(url)
    try:
        cargadores = {"coto": cargar_coto, "carrefour": cargar_carrefour}
        filas = cargadores[args.retailer]() if args.retailer in cargadores else cargar_cencosud(args.retailer)
        etiqueta = {"vea": "Vea", "jumbo": "Jumbo", "disco": "Disco"}.get(args.retailer, args.retailer.title())
        print(f"{etiqueta}: {upsertar(conn, filas)} sucursales oficiales sincronizadas.")
        if not args.sin_geocodificar:
            ok, total = geocodificar_pendientes(conn, args.retailer, args.max_geocodificar)
            print(f"{etiqueta}: {ok}/{total} coordenadas completadas en esta corrida.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
