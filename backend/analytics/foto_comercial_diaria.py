#!/usr/bin/env python3
"""
Foto comercial diaria
=====================================================================
Cada dia (despues del scrape) toma una "foto" de la posicion competitiva de
cada producto del cliente y la guarda en intel_diaria. Acumulada en el tiempo,
es la base de las tendencias de inteligencia comercial (evolucion del price
index, presion competitiva, disponibilidad).

Idempotente: upsert por (fecha, id_cliente, id_producto_cliente). Re-ejecutar
el mismo dia reescribe la foto del dia. NO toca ninguna tabla existente.

Modelo de datos (igual que el Panel Justo):
  - Mi precio  : productos_cliente.ean -> productos_fuente.ean_detectado
                 -> v_precios_actuales (promedio entre las cadenas donde estoy).
  - Competidor : mapa_competitivo_cliente (ean_competidor, retailer_competidor)
                 -> productos_fuente -> v_precios_actuales. Excluye sin stock.

Uso:
    python foto_comercial_diaria.py                 # todos los clientes, hoy
    python foto_comercial_diaria.py --cliente 1
    python foto_comercial_diaria.py --fecha 2026-06-18
"""
import argparse
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL no encontrada en el .env")
    conn = psycopg2.connect(url)
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '300s'")
        c.execute("SET lock_timeout = '15s'")
        c.execute("SET idle_in_transaction_session_timeout = '120s'")
    conn.commit()
    return conn


FOTO_SQL = """
with mias as (
    select pc.id_producto_cliente, v.precio_regular as reg, pf.disponible
    from productos_cliente pc
    join productos_fuente pf on pf.ean_detectado = pc.ean
    join v_precios_actuales v on v.id_producto_fuente = pf.id_producto_fuente
    where pc.id_cliente = %(cli)s and coalesce(pc.activo, true) and pc.ean is not null
),
mi_agg as (
    select id_producto_cliente,
           round(avg(reg)::numeric, 2) as mi_precio_reg,
           count(*) filter (where disponible is not false and reg is not null) as disponible_en
    from mias group by 1
),
comps as (
    select m.id_producto_cliente,
           v.precio_regular as reg,
           coalesce(v.precio_oferta, v.precio_regular, v.precio_actual) as eff,
           (v.precio_oferta is not null and v.precio_regular is not null
            and v.precio_oferta < v.precio_regular) as en_oferta
    from mapa_competitivo_cliente m
    join productos_fuente pf
      on pf.ean_detectado = m.ean_competidor and pf.retailer = m.retailer_competidor
    join v_precios_actuales v on v.id_producto_fuente = pf.id_producto_fuente
    where m.id_cliente = %(cli)s and m.activo and coalesce(pf.disponible, true) is not false
),
comp_agg as (
    select id_producto_cliente,
           round(avg(reg)::numeric, 2) as comp_precio_reg,
           round(min(reg)::numeric, 2) as comp_min_reg,
           round(min(eff)::numeric, 2) as comp_min_oferta,
           count(*) filter (where reg is not null) as n_comp,
           count(*) filter (where en_oferta) as n_comp_oferta
    from comps group by 1
)
insert into intel_diaria
    (fecha, id_cliente, id_producto_cliente, ean, mi_precio_reg, comp_precio_reg,
     price_index, comp_min_reg, comp_min_oferta, n_comp, n_comp_oferta, disponible_en)
select %(fecha)s, %(cli)s, pc.id_producto_cliente, pc.ean,
       ma.mi_precio_reg, ca.comp_precio_reg,
       case when ma.mi_precio_reg is not null and ca.comp_precio_reg > 0
            then round((ma.mi_precio_reg / ca.comp_precio_reg)::numeric, 4) end,
       ca.comp_min_reg, ca.comp_min_oferta,
       coalesce(ca.n_comp, 0), coalesce(ca.n_comp_oferta, 0),
       coalesce(ma.disponible_en, 0)
from productos_cliente pc
left join mi_agg ma on ma.id_producto_cliente = pc.id_producto_cliente
left join comp_agg ca on ca.id_producto_cliente = pc.id_producto_cliente
where pc.id_cliente = %(cli)s and coalesce(pc.activo, true)
  and (ma.mi_precio_reg is not null or ca.n_comp > 0)
on conflict (fecha, id_cliente, id_producto_cliente) do update set
    ean = excluded.ean,
    mi_precio_reg = excluded.mi_precio_reg,
    comp_precio_reg = excluded.comp_precio_reg,
    price_index = excluded.price_index,
    comp_min_reg = excluded.comp_min_reg,
    comp_min_oferta = excluded.comp_min_oferta,
    n_comp = excluded.n_comp,
    n_comp_oferta = excluded.n_comp_oferta,
    disponible_en = excluded.disponible_en,
    creado_en = now()
"""


def clientes_activos(cur):
    cur.execute("select distinct id_cliente from productos_cliente where coalesce(activo, true)")
    return [r[0] for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cliente", type=int, default=None)
    ap.add_argument("--fecha", type=str, default=None, help="YYYY-MM-DD (default: hoy)")
    args = ap.parse_args()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("select coalesce(%s::date, current_date)", (args.fecha,))
            fecha = cur.fetchone()[0]

            ids = [args.cliente] if args.cliente else clientes_activos(cur)
            total = 0
            for cli in ids:
                cur.execute(FOTO_SQL, {"cli": cli, "fecha": fecha})
                n = cur.rowcount
                total += n
                print(f"  cliente {cli}: {n} productos en la foto de {fecha}")
            conn.commit()
            print(f"OK - foto comercial {fecha}: {total} filas en intel_diaria")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
