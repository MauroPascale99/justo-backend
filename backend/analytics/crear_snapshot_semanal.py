#!/usr/bin/env python3
"""
Analytics - Crea el snapshot semanal INMUTABLE (global, las 7 cadenas).
========================================================================
Lee de productos_fuente (catalogo completo, 7 retailers incl. Coto/Dia) SOLO las
categorias que algun cliente mapea (an_category_map), filtrando a lo que esta hoy
en gondola (ultima_vez_visto reciente), y congela una observacion por SKU en
an_product_observation. in_stock/price best-effort desde la ultima captura.

- NO toca el scraper ni tablas existentes. Si falla, no afecta nada aguas arriba.
- Inmutable por semana ISO: si ya hay un snapshot 'completo' de esta semana, sale
  (salvo --force, que crea uno nuevo; los snapshots viejos NO se reescriben).
- El calculo del share va aparte (materializar_share.py), aguas abajo.

Uso:
    python crear_snapshot_semanal.py
    python crear_snapshot_semanal.py --dias-frescura 8
    python crear_snapshot_semanal.py --force
"""
import argparse
import os
from datetime import date

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL no encontrada en el .env")
    conn = psycopg2.connect(url)
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '600s'")
        c.execute("SET lock_timeout = '15s'")
        c.execute("SET idle_in_transaction_session_timeout = '120s'")
    conn.commit()
    return conn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias-frescura", type=int, default=8,
                    help="Solo SKUs con ultima_vez_visto en los ultimos N dias.")
    ap.add_argument("--force", action="store_true",
                    help="Crea un snapshot nuevo aunque ya exista uno de esta semana.")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()
    hoy = date.today()
    iso_year, iso_week, _ = hoy.isocalendar()

    # Inmutabilidad: no reescribir un snapshot de la misma semana ISO.
    cur.execute(
        """select id, estado from an_snapshot
           where iso_year = %s and iso_week = %s and origen = 'catalogo_semanal'
           order by id desc limit 1""",
        (iso_year, iso_week),
    )
    row = cur.fetchone()
    if row and row[1] == "completo" and not args.force:
        print(f"Ya existe snapshot completo de la semana {iso_year}-W{iso_week} "
              f"(id={row[0]}). Nada que hacer (usar --force para uno nuevo).")
        conn.close()
        return

    cur.execute(
        """insert into an_snapshot (snapshot_date, iso_year, iso_week, estado, origen)
           values (%s, %s, %s, 'en_proceso', 'catalogo_semanal')
           returning id""",
        (hoy, iso_year, iso_week),
    )
    snap_id = cur.fetchone()[0]
    conn.commit()
    print(f"Snapshot {snap_id} creado para {hoy} (semana {iso_year}-W{iso_week}).")

    # Volcado: 1 observacion por SKU de las categorias mapeadas (union de todos
    # los clientes, deduplicada), congelando in_stock/price desde la ultima captura.
    # El dedup por (snapshot, retailer, categoria_original, dedup_key) lo fuerza
    # la unique constraint via ON CONFLICT DO NOTHING.
    try:
        cur.execute(
            """
            insert into an_product_observation
                (snapshot_id, retailer, categoria_original, ean, marca, seller, in_stock, price, dedup_key)
            select %s,
                   pf.retailer,
                   pf.categoria_original,
                   nullif(pf.ean_detectado, ''),
                   pf.marca_original,
                   null,
                   coalesce(pf.disponible, cp.disponibilidad),
                   coalesce(cp.precio_regular, cp.precio_actual),
                   coalesce(nullif(pf.ean_detectado, ''),
                            'url:' || coalesce(pf.url_producto, pf.id_producto_fuente::text))
            from productos_fuente pf
            join (
                select distinct retailer, categoria_original
                from an_category_map
                where activo
            ) m on m.retailer = pf.retailer
               and m.categoria_original = pf.categoria_original
            left join lateral (
                select disponibilidad, precio_regular, precio_actual
                from capturas_precio c
                where c.id_producto_fuente = pf.id_producto_fuente
                order by c.fecha_captura desc, c.id_captura desc
                limit 1
            ) cp on true
            where pf.categoria_original <> ''
              and pf.ultima_vez_visto >= now() - (%s || ' days')::interval
            on conflict (snapshot_id, retailer, categoria_original, dedup_key) do nothing
            """,
            (snap_id, args.dias_frescura),
        )
        insertadas = cur.rowcount
        cur.execute(
            "update an_snapshot set estado='completo', finished_at=now(), total_obs=%s where id=%s",
            (insertadas, snap_id),
        )
        conn.commit()
        print(f"Snapshot {snap_id} COMPLETO: {insertadas} observaciones.")
    except Exception as e:
        conn.rollback()
        cur.execute("update an_snapshot set estado='error', finished_at=now() where id=%s", (snap_id,))
        conn.commit()
        print(f"ERROR creando snapshot {snap_id}: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
