#!/usr/bin/env python3
"""Normaliza los CSV exportados desde los PBIX SPM y actualiza Justo.

Los códigos de sucursal se resuelven contra el padrón de cobertura ya
georreferenciado. Las filas cuyo código todavía no está en el padrón se dejan
registradas al final para completar su dirección sin inventar ubicaciones.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv


def num(value: str | None) -> float:
    text = (value or '').strip().replace('.', '').replace(',', '.')
    try: return float(text)
    except ValueError: return 0.0


def rows(path: Path):
    if not path.is_file(): return []
    with path.open(encoding='utf-8-sig', newline='') as file:
        return list(csv.DictReader(file, delimiter=';'))


def latest(data: list[dict[str, str]], field: str) -> list[dict[str, str]]:
    values = [row.get(field, '') for row in data if row.get(field)]
    return [row for row in data if row.get(field, '') == max(values)] if values else data


def add(bucket: dict[tuple[str, str], dict[str, Any]], chain: str, code: str, name: str, banner: str, sale: float, stock: float, sku: str, sku_sale: float, sku_stock: float, repo: bool | None = None) -> None:
    if not code: return
    item = bucket.setdefault((chain, str(code).strip()), {'name': name, 'banner': banner, 'sale': 0.0, 'stock': 0.0, 'skus': {}, 'repo': None})
    item['name'] = item['name'] or name; item['banner'] = item['banner'] or banner
    item['sale'] += sale; item['stock'] += stock
    if repo is not None: item['repo'] = repo
    if sku:
        product = item['skus'].setdefault(sku, {'sale': 0.0, 'stock': 0.0})
        product['sale'] += sku_sale; product['stock'] += sku_stock


def cargar_cencosud(root: Path, bucket: dict[tuple[str, str], dict[str, Any]]) -> None:
    data = latest(rows(root / 'REPORTE CENCO' / 'CENCO SUCURSAL.csv'), 'PERIODO')
    for row in data:
        if row.get('Estado Local', '').upper() != 'ACTIVO': continue
        add(bucket, 'Cencosud', row.get('Cód. Local', ''), row.get('Descripción Local', ''), row.get('Bandera', ''), num(row.get('Venta Q')), num(row.get('Stock Q')), row.get('EAN Principal', ''), num(row.get('Venta Q')), num(row.get('Stock Q')))


def cargar_carrefour(root: Path, bucket: dict[tuple[str, str], dict[str, Any]]) -> None:
    data = latest(rows(root / 'REPORTE CARRE' / 'BASE.csv'), 'Mes')
    for row in data:
        add(bucket, 'Carrefour', row.get('Nro de tienda', ''), row.get('Nro. tienda - nombre de tienda', ''), row.get('Formato', ''), num(row.get('Venta mensual (uni)')), num(row.get('Stock tiendas (uni)')), row.get('Código de barras', ''), num(row.get('Venta mensual (uni)')), num(row.get('Stock tiendas (uni)')), row.get('REPO', '').strip().upper() == 'SI')


def cargar_changomas(root: Path, bucket: dict[tuple[str, str], dict[str, Any]]) -> None:
    data = latest(rows(root / 'REPORTE CHANGOMAS' / 'Detalle semanal.csv'), 'Fecha (lunes)')
    for row in data:
        stock = num(row.get('Stock on Hand'))
        add(bucket, 'Changomas', row.get('Tienda ID ID', ''), row.get('Tienda ID DESC', ''), row.get('Tienda ID DESC', ''), num(row.get('Venta Neta')), stock, row.get('Código SKU ID ID', ''), num(row.get('Venta Neta')), stock)


def cargar_dia(root: Path, bucket: dict[tuple[str, str], dict[str, Any]]) -> None:
    data = latest(rows(root / 'REPORTE DIA' / 'VENTA.csv'), 'PERIODO')
    for row in data:
        add(bucket, 'DIA', row.get('SUCURSAL', ''), f"Día {row.get('Dirección', '')}", row.get('BANDERA', 'DIA'), num(row.get('UNIDADES')), 0.0, row.get('CODIGO_EAN', ''), num(row.get('UNIDADES')), 0.0)


def cargar_laanonima(root: Path, bucket: dict[tuple[str, str], dict[str, Any]]) -> None:
    sales = latest(rows(root / 'REPORTE LA ANONIMA' / 'VENTA.csv'), 'Dia')
    stock = latest(rows(root / 'REPORTE LA ANONIMA' / 'STOCK.csv'), 'Dia')
    for row in sales:
        add(bucket, 'La Anónima', row.get('Sucursal', ''), f"La Anónima {row.get('Sucursal', '')}", 'La Anónima', num(row.get('Unidades Vendidas')), 0.0, row.get('Scancode CD', ''), num(row.get('Unidades Vendidas')), 0.0)
    for row in stock:
        add(bucket, 'La Anónima', row.get('Sucursal', ''), f"La Anónima {row.get('Sucursal', '')}", 'La Anónima', 0.0, num(row.get('Unidades Stock Final')), row.get('Articulo ID', ''), 0.0, num(row.get('Unidades Stock Final')))


def importar(root: Path) -> tuple[int, int]:
    bucket: dict[tuple[str, str], dict[str, Any]] = {}
    print('Procesando Cencosud…', flush=True); cargar_cencosud(root, bucket)
    print('Procesando Carrefour…', flush=True); cargar_carrefour(root, bucket)
    print('Procesando Chango Más…', flush=True); cargar_changomas(root, bucket)
    print('Procesando Día…', flush=True); cargar_dia(root, bucket)
    print('Procesando La Anónima…', flush=True); cargar_laanonima(root, bucket)
    load_dotenv(); conn = psycopg2.connect(os.environ['DATABASE_URL'])
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT clave,cadena,codigo FROM public.cobertura_sucursales')
            keys = {(str(chain).casefold(), str(code).strip()): key for key, chain, code in cur.fetchall() if code is not None}
            metrics: list[tuple[Any, ...]] = []; plans: list[tuple[Any, ...]] = []; missing: list[str] = []
            for (chain, code), item in bucket.items():
                key = keys.get((chain.casefold(), code))
                if not key:
                    missing.append(f'{chain};{code};{item["name"]}')
                    continue
                skus = [{'sku': sku, 'venta_semanal': round(value['sale'] / 4.345, 3), 'stock': round(value['stock'], 3), 'activo': True} for sku, value in item['skus'].items()]
                metrics.append((key, json.dumps([item['sale']]), None, item['sale'] / 4.345, None, item['stock'], None, json.dumps(skus, ensure_ascii=False)))
                if item['repo'] is not None: plans.append((key, item['repo'], 'REPORTE CARRE PBIX'))
            if metrics:
                execute_values(cur, '''INSERT INTO public.cobertura_metricas_sucursal (clave_sucursal,venta_unidades_periodos,venta_pesos_periodos,venta_semanal_unidades,venta_semanal_pesos,stock_unidades,stock_pesos,skus) VALUES %s ON CONFLICT (clave_sucursal) DO UPDATE SET venta_unidades_periodos=EXCLUDED.venta_unidades_periodos,venta_pesos_periodos=EXCLUDED.venta_pesos_periodos,venta_semanal_unidades=EXCLUDED.venta_semanal_unidades,venta_semanal_pesos=EXCLUDED.venta_semanal_pesos,stock_unidades=EXCLUDED.stock_unidades,stock_pesos=EXCLUDED.stock_pesos,skus=EXCLUDED.skus,actualizado_en=now()''', metrics, page_size=250)
            if plans:
                execute_values(cur, '''INSERT INTO public.cobertura_reposicion (clave_sucursal,tiene_reposicion,fuente) VALUES %s ON CONFLICT (clave_sucursal) DO UPDATE SET tiene_reposicion=EXCLUDED.tiene_reposicion,fuente=EXCLUDED.fuente,actualizado_en=now()''', plans, page_size=500)
        conn.commit()
    finally: conn.close()
    (root / 'sucursales_sin_padron.csv').write_text('cadena;codigo;nombre\n' + '\n'.join(missing), encoding='utf-8')
    return len(metrics), len(missing)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--exportaciones', type=Path, required=True); args = parser.parse_args()
    ok, missing = importar(args.exportaciones)
    print(f'Métricas SPM actualizadas: {ok}. Sucursales sin padrón: {missing}.')
