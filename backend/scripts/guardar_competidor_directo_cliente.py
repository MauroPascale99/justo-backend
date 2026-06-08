"""
Guardar competidor directo seleccionado por el cliente.

IMPORTANTE:
Esta versión es base/local.
La evolución correcta para JUSTO Pricing 360 debe guardar competidores agrupados por EAN,
no productos sueltos por retailer.

Regla SaaS:
- No hardcodear Ecovita.
- No hardcodear retailers.
- Siempre validar id_cliente, plan y límites.
"""

import argparse
import json
import sqlite3

DB_PATH = "local_data/justo_pricing_local_reference.db"


def json_response(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Guardar competidor directo para un producto cliente.")
    parser.add_argument("--id-cliente", type=int, required=True)
    parser.add_argument("--id-producto-cliente", type=int, required=True)
    parser.add_argument("--id-producto-competidor-fuente", type=int, required=True)
    parser.add_argument("--rol-competidor", default="COMPETIDOR_DIRECTO")
    parser.add_argument("--brecha-minima", type=float, default=None)
    parser.add_argument("--brecha-maxima", type=float, default=None)
    parser.add_argument("--margen-esperado", type=float, default=None)
    parser.add_argument("--comentario", default="")
    parser.add_argument("--modo-json", action="store_true")

    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id_cliente, nombre_cliente
        FROM clientes
        WHERE id_cliente = ?
          AND estado = 'activo'
    """, (args.id_cliente,))
    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        payload = {"ok": False, "error": f"No existe cliente activo con id_cliente={args.id_cliente}"}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    cur.execute("""
        SELECT id_producto_cliente, ean, nombre_producto, marca, categoria
        FROM productos_cliente
        WHERE id_cliente = ?
          AND id_producto_cliente = ?
          AND activo = 1
    """, (args.id_cliente, args.id_producto_cliente))
    producto = cur.fetchone()

    if not producto:
        conn.close()
        payload = {"ok": False, "error": "No existe producto propio activo para ese cliente."}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    cur.execute("""
        SELECT p.codigo_plan, p.nombre_plan, p.max_competidores_por_producto
        FROM suscripciones_cliente sc
        JOIN planes p ON p.id_plan = sc.id_plan
        WHERE sc.id_cliente = ?
          AND sc.estado = 'activa'
        ORDER BY sc.id_suscripcion DESC
        LIMIT 1
    """, (args.id_cliente,))
    plan = cur.fetchone()

    if not plan:
        conn.close()
        payload = {"ok": False, "error": "El cliente no tiene suscripción activa."}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    codigo_plan, nombre_plan, max_competidores = plan

    cur.execute("""
        SELECT COUNT(*)
        FROM mapa_competitivo_cliente
        WHERE id_cliente = ?
          AND id_producto_cliente = ?
          AND activo = 1
    """, (args.id_cliente, args.id_producto_cliente))
    competidores_actuales = cur.fetchone()[0]

    if competidores_actuales >= max_competidores:
        conn.close()
        payload = {
            "ok": False,
            "error": f"El producto ya alcanzó el máximo de competidores del plan {nombre_plan}: {max_competidores}."
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    cur.execute("""
        SELECT id_producto_fuente, retailer, ean_detectado, nombre_original, marca_original, categoria_original
        FROM productos_fuente
        WHERE id_producto_fuente = ?
    """, (args.id_producto_competidor_fuente,))
    competidor = cur.fetchone()

    if not competidor:
        conn.close()
        payload = {"ok": False, "error": "No existe producto competidor en productos_fuente."}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    (
        id_producto_competidor_fuente,
        retailer_competidor,
        ean_competidor,
        nombre_competidor,
        marca_competidor,
        categoria_competidor
    ) = competidor

    cur.execute("""
        SELECT COUNT(*)
        FROM mapa_competitivo_cliente
        WHERE id_cliente = ?
          AND id_producto_cliente = ?
          AND id_producto_competidor_fuente = ?
          AND activo = 1
    """, (args.id_cliente, args.id_producto_cliente, id_producto_competidor_fuente))

    if cur.fetchone()[0] > 0:
        conn.close()
        payload = {"ok": False, "error": "Este competidor ya está configurado para el producto."}
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    cur.execute("""
        INSERT INTO mapa_competitivo_cliente (
            id_cliente,
            id_producto_cliente,
            id_producto_competidor_fuente,
            ean_competidor,
            nombre_competidor,
            marca_competidor,
            retailer_competidor,
            categoria_competidor,
            rol_competidor,
            activo,
            margen_esperado_pct,
            brecha_minima_pct,
            brecha_maxima_pct,
            comentario_estrategia
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
    """, (
        args.id_cliente,
        args.id_producto_cliente,
        id_producto_competidor_fuente,
        ean_competidor,
        nombre_competidor,
        marca_competidor,
        retailer_competidor,
        categoria_competidor,
        args.rol_competidor,
        args.margen_esperado,
        args.brecha_minima,
        args.brecha_maxima,
        args.comentario
    ))

    id_mapa = cur.lastrowid

    cur.execute("""
        UPDATE onboarding_cliente
        SET paso_actual = 'CONFIGURACION_PRICING',
            competidores_configurados = 1,
            actualizado_en = CURRENT_TIMESTAMP
        WHERE id_cliente = ?
    """, (args.id_cliente,))

    conn.commit()
    conn.close()

    payload = {
        "ok": True,
        "id_cliente": args.id_cliente,
        "cliente": cliente[1],
        "id_mapa": id_mapa,
        "competidor_guardado": {
            "id_producto_competidor_fuente": id_producto_competidor_fuente,
            "ean_competidor": ean_competidor,
            "nombre_competidor": nombre_competidor,
            "marca_competidor": marca_competidor,
            "retailer_competidor": retailer_competidor
        },
        "siguiente_paso": "CONFIGURACION_PRICING",
        "nota": "Versión base. Evolucionar a competidor agrupado por EAN."
    }

    if args.modo_json:
        json_response(payload)
    else:
        print("\nCOMPETIDOR DIRECTO GUARDADO")
        print("=" * 100)
        print(f"Cliente: {cliente[1]}")
        print(f"Competidor: {nombre_competidor}")
        print(f"Retailer: {retailer_competidor}")
        print(f"id_mapa: {id_mapa}")
        print("Siguiente paso: CONFIGURACION_PRICING")


if __name__ == "__main__":
    main()
