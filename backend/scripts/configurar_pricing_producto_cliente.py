import argparse
import json
import sqlite3

DB_PATH = "db/justo_pricing.db"


def json_response(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Configurar pricing estratégico de un producto propio del cliente."
    )

    parser.add_argument("--id-cliente", type=int, required=True)
    parser.add_argument("--id-producto-cliente", type=int, required=True)

    parser.add_argument("--precio-sugerido", type=float, default=None)
    parser.add_argument("--precio-minimo", type=float, default=None)
    parser.add_argument("--precio-maximo", type=float, default=None)
    parser.add_argument("--margen-objetivo", type=float, default=None)

    parser.add_argument("--brecha-max-vs-competidor", type=float, default=10)
    parser.add_argument("--brecha-max-vs-lider", type=float, default=15)
    parser.add_argument("--brecha-min-vs-marca-propia", type=float, default=20)

    parser.add_argument("--modo-json", action="store_true")

    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ==========================================================
    # 1. Validar cliente
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
        payload = {
            "ok": False,
            "error": f"No existe cliente activo con id_cliente={args.id_cliente}",
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    # ==========================================================
    # 2. Validar producto propio
    # ==========================================================
    cur.execute("""
        SELECT
            id_producto_cliente,
            id_cliente,
            id_producto_fuente,
            ean,
            nombre_producto,
            marca,
            categoria,
            retailer
        FROM productos_cliente
        WHERE id_cliente = ?
          AND id_producto_cliente = ?
          AND activo = 1
    """, (
        args.id_cliente,
        args.id_producto_cliente,
    ))

    producto = cur.fetchone()

    if not producto:
        conn.close()
        payload = {
            "ok": False,
            "error": "No existe producto propio activo para ese cliente.",
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    (
        id_producto_cliente,
        _id_cliente,
        id_producto_fuente,
        ean,
        nombre_producto,
        marca,
        categoria,
        retailer,
    ) = producto

    # ==========================================================
    # 3. Validar plan
    # ==========================================================
    cur.execute("""
        SELECT
            p.codigo_plan,
            p.nombre_plan,
            p.permite_oportunidades_vs_competidor,
            p.permite_alertas_avanzadas
        FROM suscripciones_cliente sc
        JOIN planes p
          ON p.id_plan = sc.id_plan
        WHERE sc.id_cliente = ?
          AND sc.estado = 'activa'
        ORDER BY sc.id_suscripcion DESC
        LIMIT 1
    """, (args.id_cliente,))

    plan = cur.fetchone()

    if not plan:
        conn.close()
        payload = {
            "ok": False,
            "error": "El cliente no tiene suscripción activa.",
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    (
        codigo_plan,
        nombre_plan,
        permite_oportunidades_vs_competidor,
        permite_alertas_avanzadas,
    ) = plan

    # ==========================================================
    # 4. Validaciones comerciales simples
    # ==========================================================
    errores = []

    if args.precio_sugerido is not None and args.precio_sugerido <= 0:
        errores.append("El precio sugerido debe ser mayor a cero.")

    if args.precio_minimo is not None and args.precio_minimo <= 0:
        errores.append("El precio mínimo objetivo debe ser mayor a cero.")

    if args.precio_maximo is not None and args.precio_maximo <= 0:
        errores.append("El precio máximo objetivo debe ser mayor a cero.")

    if (
        args.precio_minimo is not None
        and args.precio_maximo is not None
        and args.precio_minimo > args.precio_maximo
    ):
        errores.append("El precio mínimo objetivo no puede ser mayor al precio máximo objetivo.")

    if (
        args.precio_sugerido is not None
        and args.precio_minimo is not None
        and args.precio_sugerido < args.precio_minimo
    ):
        errores.append("El precio sugerido proveedor está por debajo del precio mínimo objetivo.")

    if (
        args.precio_sugerido is not None
        and args.precio_maximo is not None
        and args.precio_sugerido > args.precio_maximo
    ):
        errores.append("El precio sugerido proveedor está por encima del precio máximo objetivo.")

    if args.margen_objetivo is not None and args.margen_objetivo < 0:
        errores.append("El margen objetivo no puede ser negativo.")

    if errores:
        conn.close()
        payload = {
            "ok": False,
            "error": "Validación de pricing fallida.",
            "errores": errores,
        }
        json_response(payload) if args.modo_json else print(payload["error"], errores)
        return

    # ==========================================================
    # 5. Insertar o actualizar configuración pricing
    # ==========================================================
    cur.execute("""
        SELECT id_config_pricing
        FROM configuracion_pricing_cliente
        WHERE id_cliente = ?
          AND id_producto_cliente = ?
        ORDER BY id_config_pricing DESC
        LIMIT 1
    """, (
        args.id_cliente,
        args.id_producto_cliente,
    ))

    existente = cur.fetchone()

    if existente:
        id_config_pricing = existente[0]

        cur.execute("""
            UPDATE configuracion_pricing_cliente
            SET
                precio_sugerido = ?,
                precio_minimo_objetivo = ?,
                precio_maximo_objetivo = ?,
                margen_objetivo = ?,
                brecha_max_vs_competidor = ?,
                brecha_max_vs_lider = ?,
                brecha_min_vs_marca_propia = ?,
                actualizado_en = CURRENT_TIMESTAMP
            WHERE id_config_pricing = ?
        """, (
            args.precio_sugerido,
            args.precio_minimo,
            args.precio_maximo,
            args.margen_objetivo,
            args.brecha_max_vs_competidor,
            args.brecha_max_vs_lider,
            args.brecha_min_vs_marca_propia,
            id_config_pricing,
        ))

        accion = "actualizada"

    else:
        cur.execute("""
            INSERT INTO configuracion_pricing_cliente (
                id_cliente,
                id_producto_cliente,
                precio_sugerido,
                precio_minimo_objetivo,
                precio_maximo_objetivo,
                margen_objetivo,
                brecha_max_vs_competidor,
                brecha_max_vs_lider,
                brecha_min_vs_marca_propia
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            args.id_cliente,
            args.id_producto_cliente,
            args.precio_sugerido,
            args.precio_minimo,
            args.precio_maximo,
            args.margen_objetivo,
            args.brecha_max_vs_competidor,
            args.brecha_max_vs_lider,
            args.brecha_min_vs_marca_propia,
        ))

        id_config_pricing = cur.lastrowid
        accion = "creada"

    # ==========================================================
    # 6. Verificar si el cliente ya puede activar dashboard
    # ==========================================================
    cur.execute("""
        SELECT COUNT(*)
        FROM productos_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))
    total_productos = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM mapa_competitivo_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))
    total_competidores = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM configuracion_pricing_cliente
        WHERE id_cliente = ?
    """, (args.id_cliente,))
    total_config_pricing = cur.fetchone()[0]

    dashboard_activo = 1 if (
        total_productos > 0
        and total_competidores > 0
        and total_config_pricing > 0
    ) else 0

    paso_actual = "DASHBOARD" if dashboard_activo else "CONFIGURACION_PRICING"

    cur.execute("""
        UPDATE onboarding_cliente
        SET
            paso_actual = ?,
            pricing_configurado = 1,
            dashboard_activo = ?,
            actualizado_en = CURRENT_TIMESTAMP
        WHERE id_cliente = ?
    """, (
        paso_actual,
        dashboard_activo,
        args.id_cliente,
    ))

    conn.commit()

    conn.close()

    payload = {
        "ok": True,
        "accion": accion,
        "id_cliente": args.id_cliente,
        "cliente": cliente[1],
        "producto": {
            "id_producto_cliente": id_producto_cliente,
            "id_producto_fuente": id_producto_fuente,
            "ean": ean,
            "nombre_producto": nombre_producto,
            "marca": marca,
            "categoria": categoria,
            "retailer_origen": retailer,
        },
        "configuracion_pricing": {
            "id_config_pricing": id_config_pricing,
            "precio_sugerido": args.precio_sugerido,
            "precio_minimo_objetivo": args.precio_minimo,
            "precio_maximo_objetivo": args.precio_maximo,
            "margen_objetivo": args.margen_objetivo,
            "brecha_max_vs_competidor": args.brecha_max_vs_competidor,
            "brecha_max_vs_lider": args.brecha_max_vs_lider,
            "brecha_min_vs_marca_propia": args.brecha_min_vs_marca_propia,
        },
        "plan": {
            "codigo_plan": codigo_plan,
            "nombre_plan": nombre_plan,
            "permite_oportunidades_vs_competidor": bool(permite_oportunidades_vs_competidor),
            "permite_alertas_avanzadas": bool(permite_alertas_avanzadas),
        },
        "estado_onboarding": {
            "productos_configurados": total_productos,
            "competidores_configurados": total_competidores,
            "pricing_configurado": total_config_pricing,
            "dashboard_activo": bool(dashboard_activo),
            "paso_actual": paso_actual,
        },
        "siguiente_paso": paso_actual,
    }

    if args.modo_json:
        json_response(payload)
    else:
        print("\nCONFIGURACIÓN PRICING GUARDADA")
        print("=" * 100)
        print(f"Cliente: {cliente[1]} | id_cliente={args.id_cliente}")
        print(f"Producto: {nombre_producto}")
        print(f"Marca: {marca}")
        print(f"Categoría: {categoria}")
        print("-" * 100)
        print(f"Configuración {accion}: id_config_pricing={id_config_pricing}")
        print(f"PVP sugerido proveedor: {args.precio_sugerido}")
        print(f"Precio mínimo objetivo: {args.precio_minimo}")
        print(f"Precio máximo objetivo: {args.precio_maximo}")
        print(f"Margen objetivo: {args.margen_objetivo}")
        print(f"Brecha max vs competidor: {args.brecha_max_vs_competidor}")
        print(f"Brecha max vs líder: {args.brecha_max_vs_lider}")
        print(f"Brecha min vs marca propia: {args.brecha_min_vs_marca_propia}")
        print("-" * 100)
        print(f"Paso actual: {paso_actual}")
        print(f"Dashboard activo: {'SÍ' if dashboard_activo else 'NO'}")

        if not permite_oportunidades_vs_competidor:
            print("\nNota comercial:")
            print("El plan actual puede guardar la configuración, pero el módulo avanzado")
            print("de oportunidades vs competidor directo puede requerir upgrade a Pro.")


if __name__ == "__main__":
    main()
