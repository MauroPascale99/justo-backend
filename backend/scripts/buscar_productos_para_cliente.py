import argparse
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = "db/justo_pricing.db"


def normalizar_texto(x):
    if x is None:
        return ""
    return str(x).lower().strip()


def exportar_vacio(path, columnas):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=columnas).to_csv(path, index=False, encoding="utf-8-sig")


def main():
    parser = argparse.ArgumentParser(description="Buscar productos para Mis Productos por cliente.")
    parser.add_argument("--id-cliente", type=int, required=True)
    parser.add_argument("--q", required=True, help="Texto a buscar: marca, nombre, EAN, URL o cualquier campo.")
    parser.add_argument("--retailer", default=None, help="Filtrar por retailer opcional.")
    parser.add_argument("--limit", type=int, default=30)

    args = parser.parse_args()

    out = Path(f"outputs/clientes/{args.id_cliente}/ultima_busqueda_mis_productos.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    columnas_salida = [
        "id_producto_fuente",
        "retailer",
        "ean",
        "nombre_producto",
        "marca",
        "categoria",
        "precio_actual",
        "precio_regular",
        "precio_oferta",
        "tipo_promocion",
        "disponibilidad",
        "url_producto",
        "url_imagen",
        "fecha_captura",
        "hora_captura",
    ]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ==========================================================
    # Cliente activo
    # ==========================================================
    cur.execute("""
        SELECT id_cliente, nombre_cliente
        FROM clientes
        WHERE id_cliente = ?
          AND estado = 'activo'
    """, (args.id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        raise SystemExit(f"No existe cliente activo con id_cliente={args.id_cliente}")

    # ==========================================================
    # Retailers habilitados
    # ==========================================================
    cur.execute("""
        SELECT retailer
        FROM retailers_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))

    retailers_habilitados = [
        normalizar_texto(r[0])
        for r in cur.fetchall()
    ]

    if not retailers_habilitados:
        conn.close()
        raise SystemExit("El cliente no tiene retailers habilitados.")

    # Categorías solo informativas, NO se usan para filtrar.
    cur.execute("""
        SELECT DISTINCT categoria
        FROM categorias_cliente
        WHERE id_cliente = ?
          AND activa = 1
    """, (args.id_cliente,))

    categorias_informativas = [
        normalizar_texto(r[0])
        for r in cur.fetchall()
    ]

    print("\nCONTEXTO CLIENTE")
    print("=" * 120)
    print(f"Cliente: {cliente[1]} | id_cliente={cliente[0]}")
    print(f"Retailers habilitados: {', '.join(retailers_habilitados)}")
    print(f"Categorías informativas NO usadas como filtro: {', '.join(categorias_informativas) if categorias_informativas else 'sin categorías'}")
    print("=" * 120)

    # ==========================================================
    # Catálogo con última captura por producto
    # ==========================================================
    sql = """
        SELECT
            pf.id_producto_fuente,
            pf.retailer,
            pf.ean_detectado AS ean,
            pf.nombre_original AS nombre_producto,
            pf.marca_original AS marca,
            pf.categoria_original AS categoria,
            pf.url_producto,
            pf.url_imagen,
            c.fecha_captura,
            c.hora_captura,
            c.precio_actual,
            c.precio_regular,
            c.precio_oferta,
            c.tipo_promocion,
            c.disponibilidad
        FROM productos_fuente pf
        LEFT JOIN capturas_precio c
          ON c.id_producto_fuente = pf.id_producto_fuente
         AND c.id_captura = (
                SELECT MAX(c2.id_captura)
                FROM capturas_precio c2
                WHERE c2.id_producto_fuente = pf.id_producto_fuente
         )
    """

    df = pd.read_sql_query(sql, conn)
    conn.close()

    if df.empty:
        exportar_vacio(out, columnas_salida)
        print("No hay productos fuente disponibles.")
        return

    # ==========================================================
    # Filtro real SaaS: SOLO retailers habilitados
    # ==========================================================
    df["retailer_norm"] = df["retailer"].astype(str).str.lower().str.strip()

    df = df[
        df["retailer_norm"].isin(retailers_habilitados)
    ].copy()

    if args.retailer:
        retailer_arg = normalizar_texto(args.retailer)

        if retailer_arg not in retailers_habilitados:
            exportar_vacio(out, columnas_salida)
            raise SystemExit(f"El retailer '{args.retailer}' no está habilitado para este cliente.")

        df = df[df["retailer_norm"] == retailer_arg].copy()

    if df.empty:
        exportar_vacio(out, columnas_salida)
        print("No hay productos dentro de los retailers habilitados.")
        return

    # ==========================================================
    # Búsqueda amplia en todos los campos relevantes
    # NO FILTRA POR CATEGORÍA
    # ==========================================================
    q = normalizar_texto(args.q)

    columnas_busqueda = [
        "id_producto_fuente",
        "retailer",
        "ean",
        "nombre_producto",
        "marca",
        "categoria",
        "url_producto",
        "url_imagen",
        "precio_actual",
        "precio_regular",
        "precio_oferta",
        "tipo_promocion",
        "disponibilidad",
        "fecha_captura",
        "hora_captura",
    ]

    columnas_busqueda = [c for c in columnas_busqueda if c in df.columns]

    texto_busqueda = (
        df[columnas_busqueda]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.lower()
    )

    res = df[texto_busqueda.str.contains(q, na=False, regex=False)].copy()

    # Orden simple: productos con precio primero, después por retailer/nombre
    if "precio_actual" in res.columns:
        res["tiene_precio"] = res["precio_actual"].notna()
        res = res.sort_values(
            by=["tiene_precio", "retailer", "nombre_producto"],
            ascending=[False, True, True]
        )
    else:
        res = res.sort_values(by=["retailer", "nombre_producto"], ascending=[True, True])

    res = res.head(args.limit).copy()

    # Asegurar columnas de salida
    for col in columnas_salida:
        if col not in res.columns:
            res[col] = None

    res = res[columnas_salida]

    res.to_csv(out, index=False, encoding="utf-8-sig")

    if res.empty:
        print(f"No se encontraron productos para: {args.q}")
        print(f"CSV generado vacío: {out}")
        return

    print(f"Resultados encontrados: {len(res)}")
    print(f"CSV generado: {out}")
    print("-" * 120)

    for _, r in res.iterrows():
        print(f"ID FUENTE: {r.get('id_producto_fuente')}")
        print(f"Retailer: {r.get('retailer')}")
        print(f"EAN: {r.get('ean')}")
        print(f"Producto: {r.get('nombre_producto')}")
        print(f"Marca: {r.get('marca')}")
        print(f"Categoría informativa: {r.get('categoria')}")
        print(f"Precio actual: {r.get('precio_actual')}")
        print(f"Disponibilidad: {r.get('disponibilidad')}")
        print("-" * 120)


if __name__ == "__main__":
    main()
