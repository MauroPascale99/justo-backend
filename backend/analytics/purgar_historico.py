#!/usr/bin/env python3
"""
Mantenimiento - Purga de historico para acotar el tamano de la base.
====================================================================
Dos retenciones, seguras para el dashboard/alertas:

1. capturas_precio: conserva
     - todas las capturas que son CAMBIO de precio (es_cambio_precio=true)
     - la ultima captura por producto (estado actual que lee el panel)
     - lo de los ultimos N dias (colchon para deteccion de cambios)
   y borra el resto (las "sin cambio" viejas, que eran ~99% de la tabla).

2. oportunidades_historicas: conserva los ultimos M dias.

La primera corrida limpia el backlog; corriendola a diario (paso en
correr_robots.sh) la base queda acotada. NO toca tablas de otra cosa.

Uso:
    python purgar_historico.py                       # capturas 2d, oportunidades 60d
    python purgar_historico.py --dias-capturas 2 --dias-oportunidades 30
    python purgar_historico.py --dry-run
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias-capturas", type=int, default=2,
                    help="Colchon de dias de capturas sin cambio a conservar.")
    ap.add_argument("--dias-oportunidades", type=int, default=60,
                    help="Dias de oportunidades_historicas a conservar.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    # ---- 1) capturas_precio: borrar "sin cambio" viejas, salvo la ultima por producto
    sql_cap = """
        delete from capturas_precio cp
        using (
            select id_producto_fuente, max(id_captura) as ult
            from capturas_precio
            group by id_producto_fuente
        ) u
        where cp.id_producto_fuente = u.id_producto_fuente
          and cp.es_cambio_precio is not true
          and cp.id_captura <> u.ult
          and cp.fecha_captura < current_date - %s
    """
    # ---- 2) oportunidades_historicas: retencion por fecha
    sql_op = "delete from oportunidades_historicas where fecha_deteccion < current_date - %s"
    # dedup: deja solo la fila mas reciente por oportunidad (estado actual). Asi,
    # aunque el motor re-inserte la misma oportunidad cada dia, la tabla no crece.
    sql_op_dedup = """
        with ranked as (
            select id_oportunidad,
                   row_number() over (
                       partition by id_cliente, ean, retailer_propio, retailer_competidor, tipo_oportunidad
                       order by fecha_deteccion desc, creado_en desc nulls last
                   ) as rn
            from oportunidades_historicas
        )
        delete from oportunidades_historicas o
        using ranked r
        where o.id_oportunidad = r.id_oportunidad and r.rn > 1
    """

    if args.dry_run:
        cur.execute("select count(*) from capturas_precio where es_cambio_precio is not true and fecha_captura < current_date - %s",
                    (args.dias_capturas,))
        cap_est = cur.fetchone()[0]
        cur.execute("select count(*) from oportunidades_historicas where fecha_deteccion < current_date - %s",
                    (args.dias_oportunidades,))
        op_est = cur.fetchone()[0]
        print(f"DRY-RUN: borraria hasta ~{cap_est} capturas y {op_est} oportunidades. Nada borrado.")
        conn.close()
        return

    cur.execute(sql_cap, (args.dias_capturas,))
    cap_del = cur.rowcount
    cur.execute(sql_op, (args.dias_oportunidades,))
    op_del = cur.rowcount
    cur.execute(sql_op_dedup)
    op_dedup = cur.rowcount
    conn.commit()
    print(f"Purga OK: -{cap_del} capturas_precio, "
          f"-{op_del} oportunidades por fecha, -{op_dedup} oportunidades duplicadas.")
    conn.close()


if __name__ == "__main__":
    main()
