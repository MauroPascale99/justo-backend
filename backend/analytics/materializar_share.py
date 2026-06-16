#!/usr/bin/env python3
"""
Analytics - Materializa el share POR CLIENTE desde un snapshot.
================================================================
Desacoplado, aguas abajo. Lee an_product_observation del snapshot, resuelve:
  - canonica del cliente:  an_category_map -> an_canonical_category
  - is_own:                EAN contra productos_cliente (primero), marca (fallback)
y materializa, por cliente:
  - an_category_snapshot : rollup retailer x nodo canonico (total_skus, in_stock, avg_price)
  - an_category_share    : share de surtido por categoria y subcategoria + CONSOLIDADO
  - an_brand_share       : ranking competitivo por marca (nivel categoria)

Dedup: se cuenta count(distinct dedup_key). dedup_key = ean (o 'url:..' si falta),
asi el mismo EAN en dos retailers cuenta 1 en CONSOLIDADO y la competencia no se
infla. Re-ejecutable: borra y reescribe SOLO las filas de (snapshot, cliente).
NO toca an_snapshot ni an_product_observation (el snapshot es inmutable).

Uso:
    python materializar_share.py                      # ultimo snapshot completo, todos los clientes
    python materializar_share.py --snapshot 12
    python materializar_share.py --snapshot 12 --cliente 1
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
        c.execute("SET statement_timeout = '600s'")
        c.execute("SET lock_timeout = '15s'")
        c.execute("SET idle_in_transaction_session_timeout = '120s'")
    conn.commit()
    return conn


# CTE base reutilizable: observaciones del snapshot ya resueltas a canonica + is_own
# para un cliente. Parametros: %(snap)s, %(cli)s
BASE_CTE = """
with obs as (
    select o.retailer,
           o.dedup_key,
           upper(trim(coalesce(o.marca, '(sin marca)'))) as marca,
           lower(coalesce(o.marca, ''))      as marca_norm,
           o.ean,
           o.in_stock,
           o.price,
           cc.id            as canonical_id,
           cc.categoria,
           cc.subcategoria
    from an_product_observation o
    join an_category_map m
      on m.id_cliente = %(cli)s and m.activo
     and m.retailer = o.retailer
     and m.categoria_original = o.categoria_original
    join an_canonical_category cc
      on cc.id = m.canonical_category_id and cc.id_cliente = %(cli)s
    where o.snapshot_id = %(snap)s
),
own_ean as (
    select distinct ean from productos_cliente
    where id_cliente = %(cli)s and ean is not null and coalesce(activo, true)
),
own_marca as (
    select distinct lower(marca) as m from productos_cliente
    where id_cliente = %(cli)s and marca is not null and coalesce(activo, true)
),
obs2 as (
    select obs.*,
           (obs.ean in (select ean from own_ean)
            or obs.marca_norm in (select m from own_marca)) as is_own
    from obs
),
catnode as (
    select categoria, id as cat_node_id
    from an_canonical_category
    where id_cliente = %(cli)s and subcategoria is null
)
"""


def materializar_cliente(cur, snap_id: int, snap_date, id_cliente: int):
    params = {"snap": snap_id, "cli": id_cliente, "date": snap_date}

    # Limpieza idempotente de lo materializado de (snapshot, cliente)
    for tabla in ("an_category_snapshot", "an_category_share", "an_brand_share"):
        cur.execute(f"delete from {tabla} where snapshot_id=%(snap)s and id_cliente=%(cli)s", params)

    # 1) Rollup por (retailer, nodo canonico mapeado)
    cur.execute(BASE_CTE + """
        insert into an_category_snapshot
            (snapshot_id, id_cliente, snapshot_date, retailer, canonical_category_id,
             total_skus, total_in_stock, avg_price)
        select %(snap)s, %(cli)s, %(date)s, retailer, canonical_id,
               count(distinct dedup_key),
               count(distinct dedup_key) filter (where in_stock),
               round(avg(price), 2)
        from obs2
        group by retailer, canonical_id
    """, params)
    rollup = cur.rowcount

    # 2) Share de surtido - nivel SUBCATEGORIA (por retailer y CONSOLIDADO)
    cur.execute(BASE_CTE + """
        insert into an_category_share
            (snapshot_id, id_cliente, snapshot_date, retailer, canonical_category_id,
             nivel, own_skus, total_skus, share_surtido, category_size)
        select %(snap)s, %(cli)s, %(date)s, retailer, canonical_id, 'subcategoria',
               count(distinct dedup_key) filter (where is_own),
               count(distinct dedup_key),
               round(count(distinct dedup_key) filter (where is_own)::numeric
                     / nullif(count(distinct dedup_key), 0), 4),
               count(distinct dedup_key)
        from obs2
        where subcategoria is not null
        group by retailer, canonical_id
    """, params)

    cur.execute(BASE_CTE + """
        insert into an_category_share
            (snapshot_id, id_cliente, snapshot_date, retailer, canonical_category_id,
             nivel, own_skus, total_skus, share_surtido, category_size)
        select %(snap)s, %(cli)s, %(date)s, 'CONSOLIDADO', canonical_id, 'subcategoria',
               count(distinct dedup_key) filter (where is_own),
               count(distinct dedup_key),
               round(count(distinct dedup_key) filter (where is_own)::numeric
                     / nullif(count(distinct dedup_key), 0), 4),
               count(distinct dedup_key)
        from obs2
        where subcategoria is not null
        group by canonical_id
    """, params)

    # 3) Share de surtido - nivel CATEGORIA (apunta al nodo categoria, subcat NULL)
    cur.execute(BASE_CTE + """
        insert into an_category_share
            (snapshot_id, id_cliente, snapshot_date, retailer, canonical_category_id,
             nivel, own_skus, total_skus, share_surtido, category_size)
        select %(snap)s, %(cli)s, %(date)s, o.retailer, cn.cat_node_id, 'categoria',
               count(distinct o.dedup_key) filter (where o.is_own),
               count(distinct o.dedup_key),
               round(count(distinct o.dedup_key) filter (where o.is_own)::numeric
                     / nullif(count(distinct o.dedup_key), 0), 4),
               count(distinct o.dedup_key)
        from obs2 o
        join catnode cn on cn.categoria = o.categoria
        group by o.retailer, cn.cat_node_id
    """, params)

    cur.execute(BASE_CTE + """
        insert into an_category_share
            (snapshot_id, id_cliente, snapshot_date, retailer, canonical_category_id,
             nivel, own_skus, total_skus, share_surtido, category_size)
        select %(snap)s, %(cli)s, %(date)s, 'CONSOLIDADO', cn.cat_node_id, 'categoria',
               count(distinct o.dedup_key) filter (where o.is_own),
               count(distinct o.dedup_key),
               round(count(distinct o.dedup_key) filter (where o.is_own)::numeric
                     / nullif(count(distinct o.dedup_key), 0), 4),
               count(distinct o.dedup_key)
        from obs2 o
        join catnode cn on cn.categoria = o.categoria
        group by cn.cat_node_id
    """, params)

    # 4) Ranking por marca (nivel categoria), por retailer y CONSOLIDADO
    cur.execute(BASE_CTE + """,
        tot_ret as (
            select retailer, categoria, count(distinct dedup_key) tot
            from obs2 group by retailer, categoria
        )
        insert into an_brand_share
            (snapshot_id, id_cliente, snapshot_date, retailer, canonical_category_id,
             marca, skus, share, is_own)
        select %(snap)s, %(cli)s, %(date)s, o.retailer, cn.cat_node_id, o.marca,
               count(distinct o.dedup_key),
               round(count(distinct o.dedup_key)::numeric / nullif(t.tot, 0), 4),
               bool_or(o.is_own)
        from obs2 o
        join catnode cn on cn.categoria = o.categoria
        join tot_ret t on t.retailer = o.retailer and t.categoria = o.categoria
        group by o.retailer, cn.cat_node_id, o.marca, t.tot
    """, params)

    cur.execute(BASE_CTE + """,
        tot_con as (
            select categoria, count(distinct dedup_key) tot
            from obs2 group by categoria
        )
        insert into an_brand_share
            (snapshot_id, id_cliente, snapshot_date, retailer, canonical_category_id,
             marca, skus, share, is_own)
        select %(snap)s, %(cli)s, %(date)s, 'CONSOLIDADO', cn.cat_node_id, o.marca,
               count(distinct o.dedup_key),
               round(count(distinct o.dedup_key)::numeric / nullif(t.tot, 0), 4),
               bool_or(o.is_own)
        from obs2 o
        join catnode cn on cn.categoria = o.categoria
        join tot_con t on t.categoria = o.categoria
        group by cn.cat_node_id, o.marca, t.tot
    """, params)

    return rollup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--snapshot", type=int, help="id de snapshot; por defecto el ultimo 'completo'.")
    ap.add_argument("--cliente", type=int, help="id_cliente; por defecto todos los que tengan taxonomia.")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    if args.snapshot:
        cur.execute("select id, snapshot_date from an_snapshot where id=%s", (args.snapshot,))
    else:
        cur.execute("select id, snapshot_date from an_snapshot where estado='completo' "
                    "order by snapshot_date desc, id desc limit 1")
    row = cur.fetchone()
    if not row:
        print("No hay snapshot disponible.")
        conn.close()
        return
    snap_id, snap_date = row

    if args.cliente:
        clientes = [args.cliente]
    else:
        cur.execute("select distinct id_cliente from an_canonical_category where activa")
        clientes = [r[0] for r in cur.fetchall()]
    if not clientes:
        print("No hay clientes con taxonomia canonica. Corre primero bootstrap_taxonomia_cliente.py")
        conn.close()
        return

    print(f"Materializando share del snapshot {snap_id} ({snap_date}) para clientes {clientes}")
    for cli in clientes:
        try:
            rollup = materializar_cliente(cur, snap_id, snap_date, cli)
            conn.commit()
            print(f"  cliente {cli}: OK ({rollup} filas de rollup)")
        except Exception as e:
            conn.rollback()
            print(f"  cliente {cli}: ERROR -> {e}")

    conn.close()
    print("Listo.")


if __name__ == "__main__":
    main()
