#!/usr/bin/env python3
"""
Analytics - Refresca SOLO la disponibilidad de las categorias mapeadas.
=======================================================================
En vez de scrapear todo el catalogo (~1M productos, horas), recorre unicamente
las categorias que algun cliente tiene mapeadas en an_category_map, en las
cadenas VTEX, y actualiza productos_fuente.disponible. Asi se puede ver el share
in-stock en minutos.

Reusa las funciones ya probadas de capturar_catalogo_vtex_completo.py
(arbol de categorias, paginado, normalizacion).

Despues de correr esto:
    python backend/analytics/crear_snapshot_semanal.py --force
    python backend/analytics/materializar_share.py

Uso (desde la raiz del repo):
    python backend/analytics/capturar_disponibilidad_categorias.py
    python backend/analytics/capturar_disponibilidad_categorias.py --retailer jumbo
"""
import argparse
import os
import sys
import time

# Reusar el scraper VTEX existente
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import capturar_catalogo_vtex_completo as cat  # noqa: E402
from psycopg2.extras import execute_values      # noqa: E402


def name_path_por_idpath(categorias: list[dict]) -> dict:
    """Reconstruye, para cada nodo del arbol, su path de NOMBRES (que es lo que
    guarda productos_fuente.categoria_original)."""
    by_id = {str(c["id"]): c for c in categorias}
    out = {}
    for c in categorias:
        nombres = []
        for cid in c["path"].split("/"):
            node = by_id.get(cid)
            nombres.append(node["nombre"] if node else cid)
        out[c["path"]] = "/".join(nombres)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--retailer", help="Solo una cadena VTEX (carrefour, jumbo, disco, vea, changomas).")
    ap.add_argument("--max-por-categoria", type=int, default=0,
                    help="Limite de productos por categoria (0 = sin limite).")
    args = ap.parse_args()

    conn = cat.get_pg_conn()
    cur = conn.cursor()

    retailers = [args.retailer] if args.retailer else list(cat.RETAILERS_VTEX.keys())
    total_act = 0

    for retailer in retailers:
        if retailer not in cat.RETAILERS_VTEX:
            print(f"  {retailer}: no es VTEX, salteo")
            continue
        cfg = cat.RETAILERS_VTEX[retailer]
        base = cfg["base_url"]

        cur.execute(
            "select distinct categoria_original from an_category_map where activo and retailer = %s",
            (retailer,),
        )
        mapeadas = {r[0] for r in cur.fetchall()}
        if not mapeadas:
            print(f"  {retailer}: sin categorias mapeadas, salteo")
            continue

        print(f"\n=== {cfg['nombre']} ({retailer}) - {len(mapeadas)} categorias mapeadas ===")
        arbol = cat.obtener_categorias(base)
        if not arbol:
            print(f"  no pude obtener el arbol de {retailer}, salteo")
            continue

        npaths = name_path_por_idpath(arbol)
        objetivo = [idp for idp, namep in npaths.items() if namep in mapeadas]
        print(f"  {len(objetivo)} nodos del arbol coinciden con lo mapeado")

        updates = {}  # url -> disponible (bool|None)
        for i, idp in enumerate(objetivo):
            prods = cat.obtener_productos_categoria(base, idp, max_productos=args.max_por_categoria)
            for p in prods:
                norm = cat.normalizar_producto(p, retailer)
                url = norm["url_producto"] or f"sin-url-{norm['id_externo']}"
                disp = norm["disponibilidad"]
                updates[url] = (True if disp == "disponible"
                                else False if disp == "sin_stock" else None)
            print(f"    [{i+1}/{len(objetivo)}] {len(prods)} productos")
            time.sleep(cat.PAUSA_ENTRE_CATS)

        if not updates:
            print(f"  {retailer}: sin productos")
            continue

        rows = [(retailer, url, disp) for url, disp in updates.items()]
        execute_values(cur, """
            update productos_fuente pf
               set disponible = v.disp
              from (values %s) as v(retailer, url, disp)
             where pf.retailer = v.retailer
               and pf.url_producto = v.url
        """, rows, template="(%s, %s, %s::boolean)", page_size=500)
        conn.commit()
        print(f"  {retailer}: {len(rows)} productos actualizados (disponible)")
        total_act += len(rows)

    conn.close()
    print(f"\nListo: {total_act} productos con disponibilidad fresca.")
    print("Ahora corre:")
    print("  python backend/analytics/crear_snapshot_semanal.py --force")
    print("  python backend/analytics/materializar_share.py")


if __name__ == "__main__":
    main()
