import argparse
import sqlite3

DB_PATH = "db/justo_pricing.db"


def main():
    parser = argparse.ArgumentParser(description="Verificar estado de onboarding de un cliente.")
    parser.add_argument("--id-cliente", type=int, required=True)

    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id_cliente,
            nombre_cliente,
            razon_social,
            cuit,
            rubro,
            estado,
            email_contacto,
            nombre_responsable,
            plan_comercial
        FROM clientes
        WHERE id_cliente = ?
    """, (args.id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        raise SystemExit(f"No existe cliente con id_cliente={args.id_cliente}")

    cur.execute("""
        SELECT
            id_onboarding,
            paso_actual,
            registro_completo,
            productos_configurados,
            competidores_configurados,
            pricing_configurado,
            dashboard_activo,
            fecha_inicio,
            actualizado_en
        FROM onboarding_cliente
        WHERE id_cliente = ?
        ORDER BY id_onboarding DESC
        LIMIT 1
    """, (args.id_cliente,))

    onboarding = cur.fetchone()

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

    # Determinar paso recomendado
    if total_productos == 0:
        paso_recomendado = "MIS_PRODUCTOS"
        mensaje = "El cliente debe seleccionar sus productos propios."
    elif total_competidores == 0:
        paso_recomendado = "COMPETIDORES"
        mensaje = "El cliente debe seleccionar competidores directos."
    elif total_config_pricing == 0:
        paso_recomendado = "CONFIGURACION_PRICING"
        mensaje = "El cliente debe cargar brechas, márgenes y PVP sugerido."
    else:
        paso_recomendado = "DASHBOARD"
        mensaje = "El cliente ya puede ver oportunidades reales."

    print("\nESTADO CLIENTE JUSTO")
    print("=" * 80)
    print("Cliente:")
    print(cliente)

    print("\nOnboarding:")
    print(onboarding if onboarding else "Sin onboarding registrado.")

    print("\nConfiguración:")
    print(f"productos_configurados: {total_productos}")
    print(f"competidores_configurados: {total_competidores}")
    print(f"configuraciones_pricing: {total_config_pricing}")

    print("\nPaso recomendado:")
    print(f"{paso_recomendado} — {mensaje}")

    # Actualizar onboarding con el estado real calculado
    if onboarding:
        productos_ok = 1 if total_productos > 0 else 0
        competidores_ok = 1 if total_competidores > 0 else 0
        pricing_ok = 1 if total_config_pricing > 0 else 0
        dashboard_ok = 1 if paso_recomendado == "DASHBOARD" else 0

        cur.execute("""
            UPDATE onboarding_cliente
            SET
                paso_actual = ?,
                productos_configurados = ?,
                competidores_configurados = ?,
                pricing_configurado = ?,
                dashboard_activo = ?,
                actualizado_en = CURRENT_TIMESTAMP
            WHERE id_onboarding = ?
        """, (
            paso_recomendado,
            productos_ok,
            competidores_ok,
            pricing_ok,
            dashboard_ok,
            onboarding[0],
        ))

        conn.commit()
        print("\nOnboarding actualizado con estado calculado.")

    conn.close()


if __name__ == "__main__":
    main()
