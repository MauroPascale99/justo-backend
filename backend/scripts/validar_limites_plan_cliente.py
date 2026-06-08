import argparse
import sqlite3

DB_PATH = "db/justo_pricing.db"


def obtener_plan_cliente(cur, id_cliente):
    cur.execute("""
        SELECT
            p.id_plan,
            p.codigo_plan,
            p.nombre_plan,
            p.max_productos,
            p.max_competidores_por_producto,
            p.max_categorias,
            p.max_usuarios,
            p.max_retailers,
            p.frecuencia_horas,
            p.historico_dias,
            p.permite_oportunidades_vs_competidor,
            p.permite_exportar,
            p.permite_alertas_avanzadas,
            p.permite_historico
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
    parser = argparse.ArgumentParser(description="Validar límites SaaS del cliente según su plan.")
    parser.add_argument("--id-cliente", type=int, required=True)

    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT id_cliente, nombre_cliente FROM clientes WHERE id_cliente = ?", (args.id_cliente,))
    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        raise SystemExit(f"No existe cliente con id_cliente={args.id_cliente}")

    plan = obtener_plan_cliente(cur, args.id_cliente)

    if not plan:
        conn.close()
        raise SystemExit("El cliente no tiene suscripción activa.")

    (
        id_plan,
        codigo_plan,
        nombre_plan,
        max_productos,
        max_competidores_por_producto,
        max_categorias,
        max_usuarios,
        max_retailers,
        frecuencia_horas,
        historico_dias,
        permite_oportunidades_vs_competidor,
        permite_exportar,
        permite_alertas_avanzadas,
        permite_historico,
    ) = plan

    cur.execute("""
        SELECT COUNT(*)
        FROM productos_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))
    productos_actuales = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(DISTINCT categoria)
        FROM categorias_cliente
        WHERE id_cliente = ?
          AND activa = 1
    """, (args.id_cliente,))
    categorias_actuales = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM retailers_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))
    retailers_actuales = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*)
        FROM usuarios_cliente
        WHERE id_cliente = ?
          AND estado = 'activo'
    """, (args.id_cliente,))
    usuarios_actuales = cur.fetchone()[0]

    print("\nLÍMITES DEL CLIENTE")
    print("=" * 80)
    print(f"Cliente: {cliente[1]} | id_cliente={cliente[0]}")
    print(f"Plan: {nombre_plan} ({codigo_plan})")
    print("-" * 80)
    print(f"Productos: {productos_actuales} / {max_productos}")
    print(f"Categorías: {categorias_actuales} / {max_categorias}")
    print(f"Retailers: {retailers_actuales} / {max_retailers}")
    print(f"Usuarios: {usuarios_actuales} / {max_usuarios}")
    print(f"Competidores por producto: máximo {max_competidores_por_producto}")
    print(f"Frecuencia scraping: cada {frecuencia_horas} hs")
    print(f"Histórico: {historico_dias} días")
    print("-" * 80)
    print(f"Oportunidades vs competidor: {'SÍ' if permite_oportunidades_vs_competidor else 'NO'}")
    print(f"Exportar: {'SÍ' if permite_exportar else 'NO'}")
    print(f"Alertas avanzadas: {'SÍ' if permite_alertas_avanzadas else 'NO'}")
    print(f"Histórico habilitado: {'SÍ' if permite_historico else 'NO'}")

    print("\nESTADO")
    print("-" * 80)
    print("Puede agregar producto:", "SÍ" if productos_actuales < max_productos else "NO")
    print("Puede agregar categoría:", "SÍ" if categorias_actuales < max_categorias else "NO")
    print("Puede agregar retailer:", "SÍ" if retailers_actuales < max_retailers else "NO")
    print("Puede agregar usuario:", "SÍ" if usuarios_actuales < max_usuarios else "NO")

    conn.close()


if __name__ == "__main__":
    main()
