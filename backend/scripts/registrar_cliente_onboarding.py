import argparse
import hashlib
import sqlite3
from getpass import getpass

DB_PATH = "db/justo_pricing.db"


def hash_password(password: str) -> str:
    # Hash simple para entorno local/dev.
    # Más adelante, para producción, conviene bcrypt/argon2.
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser(
        description="Registrar cliente/proveedor y crear onboarding inicial de JUSTO Pricing."
    )

    parser.add_argument("--nombre-empresa", required=True, help="Nombre comercial de la empresa.")
    parser.add_argument("--razon-social", default="", help="Razón social.")
    parser.add_argument("--cuit", default="", help="CUIT o identificación fiscal.")
    parser.add_argument("--rubro", default="", help="Rubro del cliente.")
    parser.add_argument("--descripcion", default="", help="Descripción de la empresa.")
    parser.add_argument("--responsable", required=True, help="Nombre del responsable/usuario admin.")
    parser.add_argument("--email", required=True, help="Email de acceso del usuario admin.")
    parser.add_argument("--telefono", default="", help="Teléfono de contacto.")
    parser.add_argument("--plan", default="starter", help="Código del plan: starter, pro o business.")
    parser.add_argument("--categorias", default="", help="Categorías separadas por coma. Ej: Limpieza,Detergentes")
    parser.add_argument("--retailers", default="", help="Retailers separados por coma. Ej: coto,dia,carrefour")
    parser.add_argument("--password", default=None, help="Contraseña inicial. Si no se pasa, la pide por consola.")

    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass("Contraseña inicial: ")

    if not password or len(password) < 6:
        raise SystemExit("La contraseña debe tener al menos 6 caracteres.")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Validar email único
    cur.execute("SELECT COUNT(*) FROM usuarios_cliente WHERE email = ?", (args.email,))
    if cur.fetchone()[0] > 0:
        conn.close()
        raise SystemExit(f"Ya existe un usuario registrado con email: {args.email}")

    # Validar CUIT si se cargó
    if args.cuit:
        cur.execute("SELECT COUNT(*) FROM clientes WHERE cuit = ?", (args.cuit,))
        if cur.fetchone()[0] > 0:
            conn.close()
            raise SystemExit(f"Ya existe un cliente registrado con CUIT: {args.cuit}")

    # Validar plan
    cur.execute("""
        SELECT
            id_plan,
            codigo_plan,
            nombre_plan,
            max_categorias,
            max_retailers
        FROM planes
        WHERE codigo_plan = ?
          AND activo = 1
    """, (args.plan,))

    plan = cur.fetchone()

    if not plan:
        conn.close()
        raise SystemExit(f"No existe plan activo con código: {args.plan}. Ejecutá migrar_saas_planes.py primero.")

    id_plan, codigo_plan, nombre_plan, max_categorias, max_retailers = plan

    categorias = [c.strip() for c in args.categorias.split(",") if c.strip()]
    retailers = [r.strip().lower() for r in args.retailers.split(",") if r.strip()]

    if len(categorias) > max_categorias:
        conn.close()
        raise SystemExit(f"El plan {nombre_plan} permite máximo {max_categorias} categorías. Recibidas: {len(categorias)}")

    if len(retailers) > max_retailers:
        conn.close()
        raise SystemExit(f"El plan {nombre_plan} permite máximo {max_retailers} retailers. Recibidos: {len(retailers)}")

    # Crear cliente
    cur.execute("""
        INSERT INTO clientes (
            nombre_cliente,
            razon_social,
            cuit,
            rubro,
            descripcion,
            email_contacto,
            telefono_contacto,
            nombre_responsable,
            plan_comercial,
            origen_registro,
            estado
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'onboarding', 'activo')
    """, (
        args.nombre_empresa,
        args.razon_social,
        args.cuit,
        args.rubro,
        args.descripcion,
        args.email,
        args.telefono,
        args.responsable,
        args.plan,
    ))

    id_cliente = cur.lastrowid

    # Crear usuario admin
    cur.execute("""
        INSERT INTO usuarios_cliente (
            id_cliente,
            nombre_usuario,
            email,
            password_hash,
            rol,
            estado
        )
        VALUES (?, ?, ?, ?, 'ADMIN_CLIENTE', 'activo')
    """, (
        id_cliente,
        args.responsable,
        args.email,
        hash_password(password),
    ))

    id_usuario = cur.lastrowid

    # Crear suscripción activa
    cur.execute("""
        INSERT INTO suscripciones_cliente (
            id_cliente,
            id_plan,
            estado,
            renovacion_automatica
        )
        VALUES (?, ?, 'activa', 1)
    """, (
        id_cliente,
        id_plan,
    ))

    id_suscripcion = cur.lastrowid

    # Crear retailers habilitados
    for retailer in retailers:
        cur.execute("""
            INSERT INTO retailers_cliente (
                id_cliente,
                retailer,
                activo
            )
            VALUES (?, ?, 1)
        """, (
            id_cliente,
            retailer,
        ))

    # Crear categorías habilitadas.
    # En esta base categorias_cliente exige retailer, entonces guardamos
    # cada combinación categoría + retailer habilitado.
    if categorias and retailers:
        for categoria in categorias:
            for retailer in retailers:
                cur.execute("""
                    INSERT INTO categorias_cliente (
                        id_cliente,
                        categoria,
                        retailer,
                        activa
                    )
                    VALUES (?, ?, ?, 1)
                """, (
                    id_cliente,
                    categoria,
                    retailer,
                ))
    elif categorias:
        # Fallback para bases donde retailer sea obligatorio:
        # si no se pasaron retailers, usamos 'todos'.
        for categoria in categorias:
            cur.execute("""
                INSERT INTO categorias_cliente (
                    id_cliente,
                    categoria,
                    retailer,
                    activa
                )
                VALUES (?, ?, 'todos', 1)
            """, (
                id_cliente,
                categoria,
            ))

    # Crear onboarding
    cur.execute("""
        INSERT INTO onboarding_cliente (
            id_cliente,
            paso_actual,
            registro_completo,
            productos_configurados,
            competidores_configurados,
            pricing_configurado,
            dashboard_activo
        )
        VALUES (?, 'MIS_PRODUCTOS_PENDIENTE', 1, 0, 0, 0, 0)
    """, (id_cliente,))

    id_onboarding = cur.lastrowid

    # Crear configuración inicial scraping
    cur.execute("""
        INSERT INTO configuracion_scraping_cliente (
            id_cliente,
            modo_captura,
            frecuencia_horas,
            scraping_universal_periodico,
            frecuencia_universal_dias,
            solo_categorias_relevantes,
            activo
        )
        VALUES (?, 'categorias_relevantes', 24, 1, 7, 1, 1)
    """, (id_cliente,))

    id_config_scraping = cur.lastrowid

    conn.commit()

    print("\nCliente registrado correctamente en JUSTO Pricing.")
    print("=" * 80)
    print(f"id_cliente: {id_cliente}")
    print(f"id_usuario_admin: {id_usuario}")
    print(f"id_suscripcion: {id_suscripcion}")
    print(f"id_onboarding: {id_onboarding}")
    print(f"id_config_scraping: {id_config_scraping}")
    print(f"plan: {nombre_plan} ({codigo_plan})")
    print(f"categorias: {', '.join(categorias) if categorias else 'sin categorías iniciales'}")
    print(f"retailers: {', '.join(retailers) if retailers else 'sin retailers iniciales'}")
    print(f"empresa: {args.nombre_empresa}")
    print(f"responsable: {args.responsable}")
    print(f"email: {args.email}")
    print(f"paso_actual: MIS_PRODUCTOS_PENDIENTE")
    print("=" * 80)

    conn.close()


if __name__ == "__main__":
    main()
