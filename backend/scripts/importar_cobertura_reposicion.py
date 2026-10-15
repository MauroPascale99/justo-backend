#!/usr/bin/env python3
"""Importa el snapshot operativo generado desde los reportes SPM.

El mapa de Cobertura y reposición guarda una copia de trabajo autocontenida
para funcionar sin acceso a Power BI. Este importador extrae sus tablas D,
COV y SALES y las normaliza en PostgreSQL. Se puede ejecutar cada vez que se
actualiza el snapshot desde los PBIX de REPORTES SPM.

Uso:
  python backend/scripts/importar_cobertura_reposicion.py --archivo "/ruta/Mapa_Cobertura_Reposicion.html"
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv


def extraer_objeto_javascript(texto: str, nombre: str) -> dict[str, Any]:
    """Decodifica un objeto JSON asignado como ``const NOMBRE = {...}``."""
    inicio_declaracion = texto.index(f"const {nombre} =")
    inicio = texto.index("{", inicio_declaracion)
    nivel = 0
    entre_comillas = False
    escape = False
    for posicion in range(inicio, len(texto)):
        caracter = texto[posicion]
        if entre_comillas:
            if escape:
                escape = False
            elif caracter == "\\":
                escape = True
            elif caracter == '"':
                entre_comillas = False
            continue
        if caracter == '"':
            entre_comillas = True
        elif caracter == "{":
            nivel += 1
        elif caracter == "}":
            nivel -= 1
            if nivel == 0:
                return json.loads(texto[inicio : posicion + 1])
    raise ValueError(f"No se pudo cerrar el objeto {nombre}.")


def valor_lista(lista: list[Any], indice: int, predeterminado: Any = None) -> Any:
    return lista[indice] if indice < len(lista) else predeterminado


def importar(conn: Any, archivo: Path) -> tuple[int, int, int]:
    texto = archivo.read_text(encoding="utf-8")
    datos = extraer_objeto_javascript(texto, "D")
    cobertura = extraer_objeto_javascript(texto, "COV")
    ventas = extraer_objeto_javascript(texto, "SALES")
    lookup = datos["lk"]
    metricas = ventas.get("s", {})
    nombres_sku = ventas.get("skus", [])
    origen = f"REPORTES SPM · {archivo.name} · {date.today().isoformat()}"

    filas_sucursales: list[tuple[Any, ...]] = []
    filas_reposicion: list[tuple[Any, ...]] = []
    filas_metricas: list[tuple[Any, ...]] = []
    for fila in datos["r"]:
            clave = str(valor_lista(fila, 0))
            cadena = str(lookup["c"][valor_lista(fila, 1)])
            banner = str(lookup["b"][valor_lista(fila, 2)])
            filas_sucursales.append((
                clave, cadena, banner, str(valor_lista(fila, 3, "")), str(valor_lista(fila, 4, "")), str(valor_lista(fila, 5, "")),
                str(valor_lista(fila, 6, "")), str(lookup["p"][valor_lista(fila, 7)]), str(lookup["z"][valor_lista(fila, 8)]),
                float(valor_lista(fila, 9)), float(valor_lista(fila, 10)), str(lookup["q"][valor_lista(fila, 11)]), origen,
            ))

            plan = cobertura.get(clave)
            if plan:
                filas_reposicion.append((clave, bool(plan.get("rep")), plan.get("vis"), plan.get("mes"), plan.get("ok"), plan.get("pend"), plan.get("dias"), plan.get("desde"), plan.get("nota"), plan.get("src") or origen))
            else:
                filas_reposicion.append((clave, False, None, None, None, None, None, None, None, origen))

            venta = metricas.get(clave)
            if venta:
                skus = [
                    {"sku": nombres_sku[item[0]] if item[0] < len(nombres_sku) else str(item[0]), "venta_semanal": item[1], "stock": item[2], "activo": bool(item[3])}
                    for item in venta.get("sk", [])
                ]
                filas_metricas.append((
                    clave, json.dumps(venta.get("u", [])), json.dumps(venta.get("v")), venta.get("wu"), venta.get("wv"),
                    venta.get("su"), venta.get("sv"), json.dumps(skus, ensure_ascii=False),
                ))

    with conn.cursor() as cursor:
        execute_values(cursor, """
            INSERT INTO public.cobertura_sucursales
                (clave, cadena, banner, codigo, nombre, direccion, partido, provincia, zona, latitud, longitud, precision_geografica, fuente)
            VALUES %s
            ON CONFLICT (clave) DO UPDATE SET cadena=EXCLUDED.cadena, banner=EXCLUDED.banner, codigo=EXCLUDED.codigo, nombre=EXCLUDED.nombre, direccion=EXCLUDED.direccion, partido=EXCLUDED.partido, provincia=EXCLUDED.provincia, zona=EXCLUDED.zona, latitud=EXCLUDED.latitud, longitud=EXCLUDED.longitud, precision_geografica=EXCLUDED.precision_geografica, fuente=EXCLUDED.fuente, actualizado_en=now()
        """, filas_sucursales, page_size=1000)
        execute_values(cursor, """
            INSERT INTO public.cobertura_reposicion
                (clave_sucursal, tiene_reposicion, visitas_semana, visitas_mes, visitas_realizadas, visitas_pendientes, dias_planificados, fecha_desde, nota, fuente)
            VALUES %s
            ON CONFLICT (clave_sucursal) DO UPDATE SET tiene_reposicion=EXCLUDED.tiene_reposicion, visitas_semana=EXCLUDED.visitas_semana, visitas_mes=EXCLUDED.visitas_mes, visitas_realizadas=EXCLUDED.visitas_realizadas, visitas_pendientes=EXCLUDED.visitas_pendientes, dias_planificados=EXCLUDED.dias_planificados, fecha_desde=EXCLUDED.fecha_desde, nota=EXCLUDED.nota, fuente=EXCLUDED.fuente, actualizado_en=now()
        """, filas_reposicion, page_size=1000)
        execute_values(cursor, """
            INSERT INTO public.cobertura_metricas_sucursal
                (clave_sucursal, venta_unidades_periodos, venta_pesos_periodos, venta_semanal_unidades, venta_semanal_pesos, stock_unidades, stock_pesos, skus)
            VALUES %s
            ON CONFLICT (clave_sucursal) DO UPDATE SET venta_unidades_periodos=EXCLUDED.venta_unidades_periodos, venta_pesos_periodos=EXCLUDED.venta_pesos_periodos, venta_semanal_unidades=EXCLUDED.venta_semanal_unidades, venta_semanal_pesos=EXCLUDED.venta_semanal_pesos, stock_unidades=EXCLUDED.stock_unidades, stock_pesos=EXCLUDED.stock_pesos, skus=EXCLUDED.skus, actualizado_en=now()
        """, filas_metricas, page_size=250)
    conn.commit()
    return len(filas_sucursales), sum(1 for fila in filas_reposicion if fila[1]), len(filas_metricas)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archivo", type=Path, required=True)
    args = parser.parse_args()
    if not args.archivo.is_file():
        raise FileNotFoundError(f"No existe el snapshot: {args.archivo}")
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL no encontrada en el entorno.")
    conn = psycopg2.connect(url)
    try:
        sucursales, reposiciones, metricas = importar(conn, args.archivo)
        print(f"Importadas: {sucursales} sucursales, {reposiciones} con reposición y {metricas} métricas operativas.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
