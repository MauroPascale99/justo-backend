#!/usr/bin/env python3
"""
Descubrimiento comercial: altas nuevas de competencia + candidatos a competidor
===============================================================================
Corre a diario despues del scrape. Dos deteciones:

1) SKU NUEVO de la competencia (first-seen real, inmune a la purga):
   Usa el registro persistente intel_sku_conocido. Un id_producto_fuente que
   aparece y NO estaba en el registro = alta real. Se filtra a las subcategorias
   donde el cliente juega y a marcas competidoras. Marca si entra mas barato que
   el producto propio de esa subcategoria.

2) CANDIDATOS a competidor (standing):
   SKUs de marca competidora, disponibles, en la misma subcategoria canonica que
   un producto propio, que todavia no estan en el mapa competitivo. Se resume por
   subcategoria (no satura) para que el cliente los mapee.

Escribe en alertas_cliente (tipos 'sku_nuevo' y 'candidato'), deduplicado.
Aditivo: no toca ninguna tabla existente salvo insertar alertas.

Primera corrida: si el registro esta vacio, solo siembra (sin alertas).

Uso:
    python detectar_descubrimientos.py
    python detectar_descubrimientos.py --cliente 1
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


def clientes_activos(cur):
    cur.execute("select distinct id_cliente from productos_cliente where coalesce(activo, true)")
    return [r[0] for r in cur.fetchall()]


# SKUs nuevos de competencia en subcategorias del cliente, recien agregados al registro hoy.
SQL_NUEVOS = """
with own_ean as (select distinct ean from productos_cliente where id_cliente=%(cli)s and ean is not null),
own_marca as (select distinct lower(marca) m from productos_cliente where id_cliente=%(cli)s and marca is not null),
own_subcats as (
  select distinct cc.id, cc.categoria, cc.subcategoria
  from productos_cliente pc
  join productos_fuente pf on pf.ean_detectado = pc.ean
  join an_category_map m on m.id_cliente=%(cli)s and m.activo and m.retailer=pf.retailer and m.categoria_original=pf.categoria_original
  join an_canonical_category cc on cc.id=m.canonical_category_id and cc.id_cliente=%(cli)s
  where pc.id_cliente=%(cli)s and coalesce(pc.activo,true) and pc.ean is not null and cc.subcategoria is not null
)
select pf.retailer, coalesce(nullif(trim(pf.marca_original),''),'(s/m)') marca,
       pf.nombre_original, pf.ean_detectado, cc.categoria, cc.subcategoria
from intel_sku_conocido k
join productos_fuente pf on pf.id_producto_fuente = k.id_producto_fuente
join an_category_map m on m.id_cliente=%(cli)s and m.activo and m.retailer=pf.retailer and m.categoria_original=pf.categoria_original
join an_canonical_category cc on cc.id=m.canonical_category_id and cc.id_cliente=%(cli)s
where k.primera_vez = current_date
  and cc.id in (select id from own_subcats)
  and coalesce(pf.disponible,true) is not false
  and (pf.ean_detectado is null or pf.ean_detectado not in (select ean from own_ean))
  and lower(coalesce(pf.marca_original,'')) not in (select m from own_marca)
limit 50
"""

# Candidatos: resumen por subcategoria de competidores sin mapear.
SQL_CANDIDATOS = """
with own_ean as (select distinct ean from productos_cliente where id_cliente=%(cli)s and ean is not null),
own_marca as (select distinct lower(marca) m from productos_cliente where id_cliente=%(cli)s and marca is not null),
mapeados as (select distinct ean_competidor from mapa_competitivo_cliente where id_cliente=%(cli)s and activo and ean_competidor is not null),
own_subcats as (
  select distinct cc.id
  from productos_cliente pc
  join productos_fuente pf on pf.ean_detectado = pc.ean
  join an_category_map m on m.id_cliente=%(cli)s and m.activo and m.retailer=pf.retailer and m.categoria_original=pf.categoria_original
  join an_canonical_category cc on cc.id=m.canonical_category_id and cc.id_cliente=%(cli)s
  where pc.id_cliente=%(cli)s and coalesce(pc.activo,true) and pc.ean is not null and cc.subcategoria is not null
),
cand as (
  select distinct on (pf.ean_detectado) pf.ean_detectado, cc.subcategoria
  from productos_fuente pf
  join an_category_map m on m.id_cliente=%(cli)s and m.activo and m.retailer=pf.retailer and m.categoria_original=pf.categoria_original
  join an_canonical_category cc on cc.id=m.canonical_category_id and cc.id_cliente=%(cli)s
  where cc.id in (select id from own_subcats)
    and pf.ultima_vez_visto >= now()-interval '8 days'
    and coalesce(pf.disponible,true) is not false
    and pf.ean_detectado is not null
    and pf.ean_detectado not in (select ean from own_ean)
    and pf.ean_detectado not in (select ean_competidor from mapeados)
    and lower(coalesce(pf.marca_original,'')) not in (select m from own_marca)
)
select subcategoria, count(*) n from cand group by subcategoria order by n desc
"""


def insertar_alerta(cur, cli, tipo, mensaje):
    # dedup: no repetir la misma alerta no leida
    cur.execute(
        "select 1 from alertas_cliente where id_cliente=%s and tipo=%s and mensaje=%s and leida=false limit 1",
        (cli, tipo, mensaje),
    )
    if cur.fetchone():
        return False
    cur.execute(
        "insert into alertas_cliente (id_cliente, tipo, mensaje, leida, fecha) values (%s,%s,%s,false,now())",
        (cli, tipo, mensaje),
    )
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cliente", type=int, default=None)
    args = ap.parse_args()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("select count(*) from intel_sku_conocido")
            registro_n = cur.fetchone()[0]

            # 1) Actualizar registro con los SKUs vistos que aun no estan
            cur.execute("""
                insert into intel_sku_conocido (id_producto_fuente, retailer, ean, primera_vez)
                select pf.id_producto_fuente, pf.retailer, pf.ean_detectado, current_date
                from productos_fuente pf
                where pf.ultima_vez_visto >= now() - interval '3 days'
                  and not exists (select 1 from intel_sku_conocido k where k.id_producto_fuente = pf.id_producto_fuente)
                on conflict (id_producto_fuente) do nothing
            """)
            nuevos_registro = cur.rowcount
            print(f"  registro: +{nuevos_registro} SKUs (tenia {registro_n})")

            if registro_n == 0:
                conn.commit()
                print("OK - registro sembrado (primera corrida, sin alertas)")
                return

            ids = [args.cliente] if args.cliente else clientes_activos(cur)
            total_alertas = 0
            for cli in ids:
                # SKU nuevo de competencia
                cur.execute(SQL_NUEVOS, {"cli": cli})
                for retailer, marca, nombre, ean, cat, subcat in cur.fetchall():
                    msg = (f"Alta nueva de competencia en {subcat or cat}: {marca} - "
                           f"{(nombre or '')[:70]} ({retailer}). Evaluá si compite con tu producto.")
                    if insertar_alerta(cur, cli, "sku_nuevo", msg):
                        total_alertas += 1

                # Candidatos a competidor (resumen por subcategoria)
                cur.execute(SQL_CANDIDATOS, {"cli": cli})
                filas = cur.fetchall()
                total_cand = sum(n for _, n in filas)
                if total_cand > 0:
                    top = ", ".join(f"{s} ({n})" for s, n in filas[:4])
                    msg = (f"Hay {total_cand} SKUs de la competencia sin vigilar en tus subcategorías: "
                           f"{top}. Mapealos para no perderlos de vista.")
                    if insertar_alerta(cur, cli, "candidato", msg):
                        total_alertas += 1

            conn.commit()
            print(f"OK - descubrimiento: {total_alertas} alertas nuevas")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
