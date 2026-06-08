import argparse
import sqlite3
from pathlib import Path
import pandas as pd

DB_PATH = "db/justo_pricing.db"

def export_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Generado: {path} ({len(df)} filas)")

def read_sql(conn, sql, params=None):
    return pd.read_sql_query(sql, conn, params=params or {})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id-cliente", type=int, required=True)
    args = parser.parse_args()

    id_cliente = args.id_cliente
    out_dir = Path(f"outputs/clientes/{id_cliente}")
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    cliente = read_sql(conn, """
        SELECT *
        FROM clientes
        WHERE id_cliente = :id_cliente
          AND estado = 'activo'
    """, {"id_cliente": id_cliente})

    if cliente.empty:
        conn.close()
        raise SystemExit(f"No existe cliente activo con id_cliente={id_cliente}")

    plan = read_sql(conn, """
        SELECT sc.id_suscripcion, sc.estado AS estado_suscripcion, p.*
        FROM suscripciones_cliente sc
        JOIN planes p ON p.id_plan = sc.id_plan
        WHERE sc.id_cliente = :id_cliente
          AND sc.estado = 'activa'
        ORDER BY sc.id_suscripcion DESC
        LIMIT 1
    """, {"id_cliente": id_cliente})

    onboarding = read_sql(conn, """
        SELECT *
        FROM onboarding_cliente
        WHERE id_cliente = :id_cliente
        ORDER BY id_onboarding DESC
        LIMIT 1
    """, {"id_cliente": id_cliente})

    productos = read_sql(conn, """
        SELECT pc.*, pf.url_producto, pf.url_imagen
        FROM productos_cliente pc
        LEFT JOIN productos_fuente pf
          ON pf.id_producto_fuente = pc.id_producto_fuente
        WHERE pc.id_cliente = :id_cliente
          AND pc.activo = 1
        ORDER BY pc.fecha_alta DESC
    """, {"id_cliente": id_cliente})

    competidores = read_sql(conn, """
        SELECT mc.*, pc.nombre_producto AS producto_propio, pc.ean AS ean_propio,
               pc.marca AS marca_propia, pc.categoria AS categoria_propia
        FROM mapa_competitivo_cliente mc
        JOIN productos_cliente pc
          ON pc.id_producto_cliente = mc.id_producto_cliente
        WHERE mc.id_cliente = :id_cliente
          AND mc.activo = 1
        ORDER BY mc.fecha_alta DESC
    """, {"id_cliente": id_cliente})

    configuracion = read_sql(conn, """
        SELECT cfg.*, pc.nombre_producto, pc.ean, pc.marca, pc.categoria
        FROM configuracion_pricing_cliente cfg
        JOIN productos_cliente pc
          ON pc.id_producto_cliente = cfg.id_producto_cliente
        WHERE cfg.id_cliente = :id_cliente
        ORDER BY cfg.actualizado_en DESC
    """, {"id_cliente": id_cliente})

    categorias = read_sql(conn, """
        SELECT DISTINCT id_cliente, categoria, activa
        FROM categorias_cliente
        WHERE id_cliente = :id_cliente
          AND activa = 1
        ORDER BY categoria
    """, {"id_cliente": id_cliente})

    retailers = read_sql(conn, """
        SELECT *
        FROM retailers_cliente
        WHERE id_cliente = :id_cliente
          AND activo = 1
        ORDER BY retailer
    """, {"id_cliente": id_cliente})

    conn.close()

    opp_path = Path("outputs/dashboard_oportunidades_vs_competidor_actual.csv")
    if opp_path.exists():
        oportunidades = pd.read_csv(opp_path, low_memory=False)
        if "id_cliente" in oportunidades.columns:
            oportunidades = oportunidades[oportunidades["id_cliente"].astype(str) == str(id_cliente)].copy()
    else:
        oportunidades = pd.DataFrame()

    c = cliente.iloc[0]
    p = plan.iloc[0] if not plan.empty else None
    ob = onboarding.iloc[0] if not onboarding.empty else None

    total_productos = len(productos)
    total_competidores = len(competidores)
    total_configuracion = len(configuracion)
    total_oportunidades = len(oportunidades)

    if total_productos == 0:
        paso_recomendado = "MIS_PRODUCTOS"
        mensaje_frontend = "Todavía no configuraste tus productos propios. Empezá seleccionando los productos que querés monitorear."
    elif total_competidores == 0:
        paso_recomendado = "COMPETIDORES"
        mensaje_frontend = "Ya tenés productos propios configurados. Ahora seleccioná competidores directos."
    elif total_configuracion == 0:
        paso_recomendado = "CONFIGURACION_PRICING"
        mensaje_frontend = "Ya tenés competidores configurados. Ahora cargá PVP, margen y brechas objetivo."
    else:
        paso_recomendado = "DASHBOARD"
        mensaje_frontend = "Dashboard privado activo. Ya podés analizar oportunidades según tu configuración."

    estado = pd.DataFrame([{
        "id_cliente": id_cliente,
        "nombre_cliente": c.get("nombre_cliente", ""),
        "razon_social": c.get("razon_social", ""),
        "rubro": c.get("rubro", ""),
        "codigo_plan": p.get("codigo_plan", "") if p is not None else "",
        "nombre_plan": p.get("nombre_plan", "") if p is not None else "",
        "paso_actual_db": ob.get("paso_actual", "") if ob is not None else "",
        "paso_recomendado": paso_recomendado,
        "total_productos": total_productos,
        "total_competidores": total_competidores,
        "total_configuracion_pricing": total_configuracion,
        "total_oportunidades_vs_competidor": total_oportunidades,
        "total_categorias_habilitadas": categorias["categoria"].nunique() if not categorias.empty else 0,
        "total_retailers_habilitados": len(retailers),
        "mensaje_frontend": mensaje_frontend,
    }])

    resumen = pd.DataFrame([
        {"bloque": "cliente", "metrica": "nombre_cliente", "valor": c.get("nombre_cliente", "")},
        {"bloque": "cliente", "metrica": "plan", "valor": p.get("nombre_plan", "") if p is not None else ""},
        {"bloque": "cliente", "metrica": "paso_recomendado", "valor": paso_recomendado},
        {"bloque": "configuracion", "metrica": "productos_propios", "valor": total_productos},
        {"bloque": "configuracion", "metrica": "competidores_directos", "valor": total_competidores},
        {"bloque": "configuracion", "metrica": "configuraciones_pricing", "valor": total_configuracion},
        {"bloque": "configuracion", "metrica": "categorias_habilitadas", "valor": categorias["categoria"].nunique() if not categorias.empty else 0},
        {"bloque": "configuracion", "metrica": "retailers_habilitados", "valor": len(retailers)},
        {"bloque": "oportunidades", "metrica": "oportunidades_vs_competidor", "valor": total_oportunidades},
    ])

    export_csv(estado, out_dir / "dashboard_privado_estado.csv")
    export_csv(resumen, out_dir / "dashboard_privado_resumen.csv")
    export_csv(productos, out_dir / "dashboard_privado_productos.csv")
    export_csv(competidores, out_dir / "dashboard_privado_competidores.csv")
    export_csv(configuracion, out_dir / "dashboard_privado_configuracion.csv")
    export_csv(categorias, out_dir / "dashboard_privado_categorias.csv")
    export_csv(retailers, out_dir / "dashboard_privado_retailers.csv")
    export_csv(oportunidades, out_dir / "dashboard_privado_oportunidades_vs_competidor.csv")

    print("")
    print("RESUMEN DASHBOARD PRIVADO")
    print("=" * 80)
    print(f"Cliente: {c.get('nombre_cliente', '')} | id_cliente={id_cliente}")
    print(f"Plan: {p.get('nombre_plan', '') if p is not None else 'Sin plan'}")
    print(f"Paso recomendado: {paso_recomendado}")
    print(f"Productos propios: {total_productos}")
    print(f"Competidores directos: {total_competidores}")
    print(f"Configuraciones pricing: {total_configuracion}")
    print(f"Oportunidades vs competidor: {total_oportunidades}")
    print(f"Mensaje frontend: {mensaje_frontend}")
    print("=" * 80)

if __name__ == "__main__":
    main()
