import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = "local_data/justo_pricing_local_reference.db"


def json_response(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def normalizar_ean(x):
    if x is None:
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def main():
    parser = argparse.ArgumentParser(
        description="Agregar a Mis Productos un producto normalizado por EAN agrupado."
    )

    parser.add_argument("--id-cliente", type=int, required=True)
    parser.add_argument("--ean", required=True)
    parser.add_argument("--modo-json", action="store_true")

    args = parser.parse_args()

    id_cliente = args.id_cliente
    ean = normalizar_ean(args.ean)

    base_dir = Path(f"local_data/outputs/clientes/{id_cliente}")
    agrupado_path = base_dir / "ultima_busqueda_mis_productos_agrupada.csv"

    if not agrupado_path.exists():
        payload = {
            "ok": False,
            "error": f"No existe búsqueda agrupada: {agrupado_path}."
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    df = pd.read_csv(agrupado_path, low_memory=False)

    if df.empty:
        payload = {"ok": False, "error": "La búsqueda agrupada está vacía."}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    df["ean_norm"] = df["ean"].apply(normalizar_ean)
    row = df[df["ean_norm"] == ean]

    if row.empty:
        payload = {"ok": False, "error": f"No encontré el EAN {ean} en la búsqueda agrupada."}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    p = row.iloc[0]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id_cliente, nombre_cliente
        FROM clientes
        WHERE id_cliente = ?
          AND estado = 'activo'
    """, (id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        payload = {"ok": False, "error": f"No existe cliente activo con id_cliente={id_cliente}"}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    cur.execute("""
        SELECT p.codigo_plan, p.nombre_plan, p.max_productos
        FROM suscripciones_cliente sc
        JOIN planes p ON p.id_plan = sc.id_plan
        WHERE sc.id_cliente = ?
          AND sc.estado = 'activa'
        ORDER BY sc.id_suscripcion DESC
        LIMIT 1
    """, (id_cliente,))

    plan = cur.fetchone()

    if not plan:
        conn.close()
        payload = {"ok": False, "error": "El cliente no tiene suscripción activa."}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    codigo_plan, nombre_plan, max_productos = plan

    cur.execute("""
        SELECT COUNT(*)
        FROM productos_cliente
        WHERE id_cliente = ?
          AND activo = 1
          AND rol = 'PRODUCTO_PROPIO'
    """, (id_cliente,))

    productos_actuales = cur.fetchone()[0]

    if productos_actuales >= max_productos:
        conn.close()
        payload = {
            "ok": False,
            "error": f"El cliente ya alcanzó el máximo de productos del plan {nombre_plan}: {max_productos}."
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    cur.execute("""
        SELECT id_producto_cliente
        FROM productos_cliente
        WHERE id_cliente = ?
          AND activo = 1
          AND ean = ?
        LIMIT 1
    """, (id_cliente, ean))

    existente = cur.fetchone()

    if existente:
        conn.close()
        payload = {
            "ok": False,
            "error": "Este producto/EAN ya está agregado a Mis Productos.",
            "id_producto_cliente": existente[0]
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    def get_str(col):
        return str(p.get(col, "") or "")

    def get_num(col):
        try:
            v = p.get(col, None)
            if pd.isna(v):
                return None
            return float(v)
        except Exception:
            return None

    nombre_producto = get_str("nombre_producto")
    marca = get_str("marca")
    categoria = get_str("categoria_principal")
    ids_relacionados = get_str("ids_producto_fuente")
    retailers_detectados = get_str("retailers_detectados")

    try:
        cantidad_retailers = int(float(p.get("cantidad_retailers", 0) or 0))
    except Exception:
        cantidad_retailers = 0

    precio_regular_promedio = get_num("precio_regular_promedio")
    precio_regular_min = get_num("precio_regular_min")
    precio_regular_max = get_num("precio_regular_max")
    retailer_precio_regular_min = get_str("retailer_precio_regular_min")
    retailer_precio_regular_max = get_str("retailer_precio_regular_max")

    primer_id_fuente = None
    if ids_relacionados:
        try:
            primer_id_fuente = int(str(ids_relacionados).split(",")[0].strip())
        except Exception:
            primer_id_fuente = None

    cur.execute("""
        INSERT INTO productos_cliente (
            id_cliente,
            id_producto_fuente,
            sku_cliente,
            ean,
            nombre_producto,
            marca,
            categoria,
            retailer,
            rol,
            activo,
            clave_producto,
            ids_producto_fuente_relacionados,
            retailers_detectados,
            cantidad_retailers,
            precio_regular_promedio,
            precio_regular_min,
            precio_regular_max,
            retailer_precio_regular_min,
            retailer_precio_regular_max,
            origen_alta
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PRODUCTO_PROPIO', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        id_cliente,
        primer_id_fuente,
        "",
        ean,
        nombre_producto,
        marca,
        categoria,
        "MULTI_RETAILER",
        ean,
        ids_relacionados,
        retailers_detectados,
        cantidad_retailers,
        precio_regular_promedio,
        precio_regular_min,
        precio_regular_max,
        retailer_precio_regular_min,
        retailer_precio_regular_max,
        "MIS_PRODUCTOS_AGRUPADO_EAN"
    ))

    id_producto_cliente = cur.lastrowid

    cur.execute("""
        UPDATE onboarding_cliente
        SET paso_actual = 'COMPETIDORES',
            productos_configurados = 1,
            actualizado_en = CURRENT_TIMESTAMP
        WHERE id_cliente = ?
    """, (id_cliente,))

    conn.commit()
    conn.close()

    payload = {
        "ok": True,
        "id_cliente": id_cliente,
        "cliente": cliente[1],
        "id_producto_cliente": id_producto_cliente,
        "producto": {
            "ean": ean,
            "nombre_producto": nombre_producto,
            "marca": marca,
            "categoria": categoria,
            "retailers_detectados": retailers_detectados,
            "cantidad_retailers": cantidad_retailers,
            "precio_regular_promedio": precio_regular_promedio,
            "precio_regular_min": precio_regular_min,
            "precio_regular_max": precio_regular_max,
            "retailer_precio_regular_min": retailer_precio_regular_min,
            "retailer_precio_regular_max": retailer_precio_regular_max,
            "ids_producto_fuente_relacionados": ids_relacionados
        },
        "plan": {
            "codigo_plan": codigo_plan,
            "nombre_plan": nombre_plan,
            "productos_antes": productos_actuales,
            "productos_despues": productos_actuales + 1,
            "max_productos": max_productos
        },
        "siguiente_paso": "COMPETIDORES"
    }

    if args.modo_json:
        json_response(payload)
    else:
        print("\nPRODUCTO AGRUPADO AGREGADO A MIS PRODUCTOS")
        print("=" * 100)
        print(f"Cliente: {cliente[1]} | id_cliente={id_cliente}")
        print(f"id_producto_cliente: {id_producto_cliente}")
        print(f"EAN: {ean}")
        print(f"Producto: {nombre_producto}")
        print(f"Marca: {marca}")
        print(f"Retailers detectados: {retailers_detectados}")
        print(f"Precio regular promedio: {precio_regular_promedio}")
        print(f"Precio regular min: {precio_regular_min} | {retailer_precio_regular_min}")
        print(f"Precio regular max: {precio_regular_max} | {retailer_precio_regular_max}")
        print("-" * 100)
        print(f"Productos plan: {productos_actuales + 1} / {max_productos}")
        print("Siguiente paso: COMPETIDORES")


if __name__ == "__main__":
    main()
