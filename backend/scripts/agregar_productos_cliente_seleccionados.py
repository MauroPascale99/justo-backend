import argparse
import json
import sqlite3
from pathlib import Path

DB_PATH = "db/justo_pricing.db"


def json_response(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def obtener_plan_y_limites(cur, id_cliente):
    cur.execute("""
        SELECT
            p.codigo_plan,
            p.nombre_plan,
            p.max_productos
        FROM suscripciones_cliente sc
        JOIN planes p
          ON p.id_plan = sc.id_plan
        WHERE sc.id_cliente = ?
          AND sc.estado = 'activa'
        ORDER BY sc.id_suscripcion DESC
        LIMIT 1
    """, (id_cliente,))
    return cur.fetchone()


def main():
    parser = argparse.ArgumentParser(
        description="Agregar productos seleccionados por el cliente a productos_cliente."
    )

    parser.add_argument("--id-cliente", type=int, required=True)
    parser.add_argument(
        "--ids-producto-fuente",
        required=True,
        help="IDs separados por coma. Ej: 123,456,789"
    )
    parser.add_argument("--sku-prefix", default="", help="Prefijo opcional para SKU interno.")
    parser.add_argument("--modo-json", action="store_true", help="Salida JSON para frontend/API.")

    args = parser.parse_args()

    ids = []
    for x in args.ids_producto_fuente.split(","):
        x = x.strip()
        if x:
            try:
                ids.append(int(x))
            except Exception:
                pass

    ids = list(dict.fromkeys(ids))

    if not ids:
        payload = {
            "ok": False,
            "error": "No se recibieron IDs válidos.",
            "insertados": [],
            "rechazados": [],
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Validar cliente
    cur.execute("""
        SELECT id_cliente, nombre_cliente
        FROM clientes
        WHERE id_cliente = ?
          AND estado = 'activo'
    """, (args.id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        payload = {
            "ok": False,
            "error": f"No existe cliente activo con id_cliente={args.id_cliente}",
            "insertados": [],
            "rechazados": [],
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    # Validar plan
    plan = obtener_plan_y_limites(cur, args.id_cliente)

    if not plan:
        conn.close()
        payload = {
            "ok": False,
            "error": "El cliente no tiene suscripción activa.",
            "insertados": [],
            "rechazados": [],
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    codigo_plan, nombre_plan, max_productos = plan

    # Productos actuales
    cur.execute("""
        SELECT COUNT(*)
        FROM productos_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))

    productos_actuales = cur.fetchone()[0]

    cupo_disponible = max_productos - productos_actuales

    if cupo_disponible <= 0:
        conn.close()
        payload = {
            "ok": False,
            "error": f"El cliente ya alcanzó el máximo de productos del plan {nombre_plan}: {max_productos}.",
            "insertados": [],
            "rechazados": ids,
            "plan": {
                "codigo_plan": codigo_plan,
                "nombre_plan": nombre_plan,
                "max_productos": max_productos,
                "productos_actuales": productos_actuales,
            }
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    # Retailers habilitados
    cur.execute("""
        SELECT retailer
        FROM retailers_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))

    retailers_habilitados = {
        str(r[0]).lower().strip()
        for r in cur.fetchall()
    }

    # Categorías habilitadas
    cur.execute("""
        SELECT DISTINCT categoria
        FROM categorias_cliente
        WHERE id_cliente = ?
          AND activa = 1
    """, (args.id_cliente,))

    categorias_habilitadas = {
        str(r[0]).lower().strip()
        for r in cur.fetchall()
    }

    insertados = []
    rechazados = []

    for id_producto_fuente in ids:
        if len(insertados) >= cupo_disponible:
            rechazados.append({
                "id_producto_fuente": id_producto_fuente,
                "motivo": "Sin cupo disponible según el plan.",
            })
            continue

        cur.execute("""
            SELECT
                id_producto_fuente,
                retailer,
                ean_detectado,
                nombre_original,
                marca_original,
                categoria_original
            FROM productos_fuente
            WHERE id_producto_fuente = ?
        """, (id_producto_fuente,))

        prod = cur.fetchone()

        if not prod:
            rechazados.append({
                "id_producto_fuente": id_producto_fuente,
                "motivo": "No existe producto fuente.",
            })
            continue

        (
            id_pf,
            retailer,
            ean,
            nombre,
            marca,
            categoria,
        ) = prod

        retailer_norm = str(retailer or "").lower().strip()
        categoria_norm = str(categoria or "").lower().strip()

        if retailer_norm not in retailers_habilitados:
            rechazados.append({
                "id_producto_fuente": id_producto_fuente,
                "producto": nombre,
                "retailer": retailer,
                "motivo": "Retailer no habilitado para el cliente.",
            })
            continue

        categoria_ok = any(
            c in categoria_norm or categoria_norm in c
            for c in categorias_habilitadas
        )

        if not categoria_ok:
            rechazados.append({
                "id_producto_fuente": id_producto_fuente,
                "producto": nombre,
                "categoria": categoria,
                "motivo": "Categoría no habilitada para el cliente.",
            })
            continue

        # Evitar duplicados por id_producto_fuente o EAN
        cur.execute("""
            SELECT COUNT(*)
            FROM productos_cliente
            WHERE id_cliente = ?
              AND activo = 1
              AND (
                    id_producto_fuente = ?
                    OR (
                        ean IS NOT NULL
                        AND ean != ''
                        AND ean = ?
                    )
              )
        """, (
            args.id_cliente,
            id_pf,
            ean,
        ))

        if cur.fetchone()[0] > 0:
            rechazados.append({
                "id_producto_fuente": id_producto_fuente,
                "producto": nombre,
                "ean": ean,
                "motivo": "Producto ya registrado para este cliente.",
            })
            continue

        sku_cliente = ""
        if args.sku_prefix:
            sku_cliente = f"{args.sku_prefix}-{id_pf}"

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
                activo
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PRODUCTO_PROPIO', 1)
        """, (
            args.id_cliente,
            id_pf,
            sku_cliente,
            ean,
            nombre,
            marca,
            categoria,
            retailer,
        ))

        id_producto_cliente = cur.lastrowid

        insertados.append({
            "id_producto_cliente": id_producto_cliente,
            "id_producto_fuente": id_pf,
            "ean": ean,
            "producto": nombre,
            "marca": marca,
            "categoria": categoria,
            "retailer": retailer,
        })

    # Actualizar onboarding si se insertó al menos uno
    if insertados:
        cur.execute("""
            UPDATE onboarding_cliente
            SET
                paso_actual = 'COMPETIDORES',
                productos_configurados = 1,
                actualizado_en = CURRENT_TIMESTAMP
            WHERE id_cliente = ?
        """, (args.id_cliente,))

    conn.commit()

    # Estado final
    cur.execute("""
        SELECT COUNT(*)
        FROM productos_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))
    productos_finales = cur.fetchone()[0]

    conn.close()

    payload = {
        "ok": True,
        "id_cliente": args.id_cliente,
        "cliente": cliente[1],
        "plan": {
            "codigo_plan": codigo_plan,
            "nombre_plan": nombre_plan,
            "max_productos": max_productos,
            "productos_antes": productos_actuales,
            "productos_despues": productos_finales,
            "cupo_restante": max_productos - productos_finales,
        },
        "insertados": insertados,
        "rechazados": rechazados,
        "siguiente_paso": "COMPETIDORES" if insertados else "MIS_PRODUCTOS",
    }

    if args.modo_json:
        json_response(payload)
    else:
        print("\nAGREGAR PRODUCTOS A MIS PRODUCTOS")
        print("=" * 100)
        print(f"Cliente: {cliente[1]} | id_cliente={args.id_cliente}")
        print(f"Plan: {nombre_plan} ({codigo_plan})")
        print(f"Productos antes: {productos_actuales} / {max_productos}")
        print(f"Productos después: {productos_finales} / {max_productos}")
        print("-" * 100)

        print("\nINSERTADOS")
        for p in insertados:
            print(f"- id_producto_cliente={p['id_producto_cliente']} | {p['producto']} | {p['retailer']} | EAN {p['ean']}")

        print("\nRECHAZADOS")
        if rechazados:
            for r in rechazados:
                print(f"- {r}")
        else:
            print("Sin rechazados.")

        print("\nSiguiente paso:", payload["siguiente_paso"])


if __name__ == "__main__":
    main()
