#!/usr/bin/env python3
"""
Analytics - Bootstrap de taxonomia canonica POR CLIENTE.
=========================================================
Siembra an_canonical_category + an_category_map para un cliente a partir de SUS
productos (productos_cliente): busca en que categorias crudas (categoria_original)
de cada retailer aparecen los EAN del cliente y crea un DRAFT que el cliente puede
ajustar despues.

Por cada categoria detectada crea:
  - un nodo de CATEGORIA (subcategoria NULL)            -> share a nivel categoria
  - un nodo de SUBCATEGORIA (si el path tiene nivel 2)  -> share a nivel subcategoria
  - el mapeo (retailer, categoria_original) -> nodo mas profundo disponible

Normalizacion: un diccionario de sinonimos colapsa los nombres distintos que usa
cada retail (ej. "Limpieza", "Limpieza de Bano", "Pisos Y Muebles") en una sola
categoria canonica. Editar SINONIMOS_CATEGORIA para curar.

Por defecto mapea SOLO las categorias crudas donde el cliente ya tiene productos
(denominador preciso por subcategoria). Para ampliar el denominador a toda una
rama de nivel-1, usar --expandir (mapea tambien las categorias hermanas).

Idempotente (ON CONFLICT DO NOTHING / activa=true). No toca tablas existentes.

Uso:
    python bootstrap_taxonomia_cliente.py --cliente 1 --dry-run
    python bootstrap_taxonomia_cliente.py --cliente 1
    python bootstrap_taxonomia_cliente.py --cliente 1 --expandir
"""
import argparse
import os
import re
import unicodedata

import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Sinonimos de nivel-1 (normalizado) -> etiqueta de categoria canonica.
# Crecer/editar segun el cliente. Si un nivel-1 no esta aca, se usa tal cual (Title Case).
SINONIMOS_CATEGORIA = {
    "limpieza": "Limpieza y cuidado del hogar",
    "limpieza de bano": "Limpieza y cuidado del hogar",
    "pisos y muebles": "Limpieza y cuidado del hogar",
    "lavado de ropa": "Limpieza y cuidado del hogar",
    "ropa": "Limpieza y cuidado del hogar",
    "perfumeria y farmacia": "Perfumería y cuidado personal",
    "perfumeria": "Perfumería y cuidado personal",
}

# Sinonimos de TIPO de producto (nivel-3 del path, normalizado) -> subcategoria
# canonica. El nivel-3 del retail ES el tipo de producto (detergente, suavizante,
# limpiador, etc.), que es el eje util para share. Si un nivel-3 no esta aca, se
# usa tal cual (Title Case). Si no hay nivel-3, el producto queda solo a nivel
# categoria (sin subcategoria).
SINONIMOS_TIPO = {
    # Ropa
    "detergente para ropa": "Detergente para ropa",
    "lavado a mano": "Detergente para ropa",
    "lavado a maquina": "Detergente para ropa",
    "suavizantes": "Suavizantes",
    "suavizantes para la ropa": "Suavizantes",
    "jabones para la ropa": "Jabón para ropa",
    "jabon liquido": "Jabón para ropa",
    "aprestos y blanqueadores": "Aprestos y blanqueadores",
    "aprestos": "Aprestos y blanqueadores",
    "aprestos y perfumes": "Aprestos y blanqueadores",
    # Cocina
    "detergentes": "Lavavajillas",
    "detergentes de mano": "Lavavajillas",
    "limpiadores": "Limpiadores",
    "limpiadores liquidos": "Limpiadores",
    "limpiadores de cocina": "Limpiadores",
    "multiusos": "Limpiadores",
    "repuestos desinfectantes y multiuso": "Limpiadores",
    "limpiavidrios": "Limpiavidrios",
    "limpia vidrios": "Limpiavidrios",
    # Bano
    "desinfectantes": "Limpieza de baño",
    "limpiadores de bano": "Limpieza de baño",
    # Pisos y muebles
    "lustramuebles": "Lustramuebles",
    # Perfumeria / cuidado personal
    "jabones liquidos": "Jabón de tocador",
}


def norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def canonica_de(lvl1: str) -> str:
    return SINONIMOS_CATEGORIA.get(norm(lvl1), (lvl1 or "Otros").strip().title())


def subcat_de(lvl3):
    """Tipo de producto canonico desde el nivel-3 del path. None si no hay nivel-3."""
    if not lvl3:
        return None
    return SINONIMOS_TIPO.get(norm(lvl3), lvl3.strip().title())


def slugify(*parts) -> str:
    base = "-".join(norm(p).replace(" ", "-") for p in parts if p)
    return re.sub(r"[^a-z0-9\-]", "", base) or "cat"


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL no encontrada en el .env")
    conn = psycopg2.connect(url)
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '120s'")
        c.execute("SET lock_timeout = '10s'")
        c.execute("SET idle_in_transaction_session_timeout = '60s'")
    conn.commit()
    return conn


def categorias_del_cliente(cur, id_cliente: int, expandir: bool):
    """(retailer, categoria_original) crudas relevantes para el cliente."""
    cur.execute(
        """
        select distinct pf.retailer, pf.categoria_original
        from productos_cliente pc
        join productos_fuente pf on pf.ean_detectado = pc.ean
        where pc.id_cliente = %s
          and coalesce(pc.activo, true)
          and pc.ean is not null
          and pf.categoria_original <> ''
        """,
        (id_cliente,),
    )
    base = cur.fetchall()
    if not expandir:
        return base

    # Ampliar a todas las categorias hermanas bajo el mismo nivel-1 por retailer.
    nivel1_por_retailer = {}
    for retailer, raw in base:
        lvl1 = (raw.split("/")[0] or "").strip()
        nivel1_por_retailer.setdefault(retailer, set()).add(lvl1)

    ampliadas = set(base)
    for retailer, lvl1s in nivel1_por_retailer.items():
        for lvl1 in lvl1s:
            cur.execute(
                """
                select distinct retailer, categoria_original
                from productos_fuente
                where retailer = %s
                  and categoria_original <> ''
                  and split_part(categoria_original, '/', 1) = %s
                """,
                (retailer, lvl1),
            )
            ampliadas.update(cur.fetchall())
    return sorted(ampliadas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cliente", type=int, required=True)
    ap.add_argument("--expandir", action="store_true",
                    help="Mapea tambien las categorias hermanas del mismo nivel-1.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = get_conn()
    cur = conn.cursor()

    raws = categorias_del_cliente(cur, args.cliente, args.expandir)
    print(f"Categorias crudas relevantes para cliente {args.cliente}: {len(raws)}")

    # Construir nodos canonicos (categoria + subcategoria) y mapeos.
    nodos = set()                      # (categoria, subcategoria|None)
    mapeos = []                        # (retailer, raw, categoria, subcategoria|None)
    for retailer, raw in raws:
        partes = [p.strip() for p in raw.split("/") if p.strip()]
        lvl1 = partes[0] if partes else raw
        lvl3 = partes[2] if len(partes) > 2 else None
        categoria = canonica_de(lvl1)
        subcat = subcat_de(lvl3)   # subcategoria = tipo de producto (nivel-3)
        nodos.add((categoria, None))           # nodo categoria SIEMPRE
        if subcat:
            nodos.add((categoria, subcat))     # nodo subcategoria
        mapeos.append((retailer, raw, categoria, subcat))

    print(f"  -> {len(nodos)} nodos canonicos, {len(mapeos)} mapeos")
    for categoria, subcat in sorted(nodos, key=lambda x: (x[0], x[1] or "")):
        print(f"     [{categoria}] / {subcat or '(categoria)'}")

    if args.dry_run:
        print("\nDRY-RUN: no se escribio nada.")
        conn.close()
        return

    # Insertar nodos canonicos
    id_nodo = {}
    for categoria, subcat in nodos:
        cur.execute(
            """
            insert into an_canonical_category (id_cliente, categoria, subcategoria, slug)
            values (%s, %s, %s, %s)
            on conflict (id_cliente, categoria, subcategoria) do update set activa = true
            returning id
            """,
            (args.cliente, categoria, subcat, slugify(categoria, subcat or "")),
        )
        id_nodo[(categoria, subcat)] = cur.fetchone()[0]

    # Insertar mapeos hacia el nodo mas profundo disponible
    nuevos = 0
    for retailer, raw, categoria, subcat in mapeos:
        nodo_id = id_nodo.get((categoria, subcat)) or id_nodo[(categoria, None)]
        cur.execute(
            """
            insert into an_category_map (id_cliente, retailer, categoria_original, canonical_category_id)
            values (%s, %s, %s, %s)
            on conflict (id_cliente, retailer, categoria_original) do nothing
            """,
            (args.cliente, retailer, raw, nodo_id),
        )
        nuevos += cur.rowcount

    conn.commit()
    print(f"\nListo: {len(id_nodo)} nodos canonicos, {nuevos} mapeos nuevos para cliente {args.cliente}.")
    conn.close()


if __name__ == "__main__":
    main()
