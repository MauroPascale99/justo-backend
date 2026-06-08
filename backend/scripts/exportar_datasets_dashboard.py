import sqlite3
from pathlib import Path

import pandas as pd

DB_PATH = "db/justo_pricing.db"
OUT_DIR = Path("outputs")
OUT_DIR.mkdir(exist_ok=True)

OUT_RESUMEN = OUT_DIR / "dashboard_resumen_actual.csv"
OUT_OPP_ACTUAL = OUT_DIR / "dashboard_oportunidades_actuales.csv"
OUT_EVOL_PRECIOS = OUT_DIR / "dashboard_evolucion_precios.csv"
OUT_EVOL_ALERTAS = OUT_DIR / "dashboard_evolucion_alertas.csv"
OUT_KPIS_RETAILER = OUT_DIR / "dashboard_kpis_retailer_actual.csv"


def read_sql(conn, sql, params=None):
    return pd.read_sql_query(sql, conn, params=params or {})


def main():
    import sys
    import os
    import yaml
    
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
    
    config_path = os.path.join(BACKEND_DIR, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    db_type = config.get("db", {}).get("tipo", "sqlite")
    if db_type == "postgres":
        print("Base de datos configurada como Postgres (Supabase).")
        print("El frontend Next.js consume los datos directamente desde la base de datos en tiempo real.")
        print("Se saltea la exportación de datasets estáticos CSV para el dashboard local.")
        return

    conn = sqlite3.connect(DB_PATH)

    # ==========================================================
    # 1. Última corrida de oportunidades
    # ==========================================================
    ultima_corrida = read_sql(conn, """
        SELECT id_corrida, fecha_captura, hora_captura, COUNT(*) AS oportunidades
        FROM oportunidades_historicas
        GROUP BY id_corrida, fecha_captura, hora_captura
        ORDER BY fecha_captura DESC, hora_captura DESC, id_corrida DESC
        LIMIT 1
    """)

    if ultima_corrida.empty:
        raise RuntimeError("No hay datos en oportunidades_historicas.")

    id_corrida = ultima_corrida.iloc[0]["id_corrida"]
    fecha_actual = ultima_corrida.iloc[0]["fecha_captura"]
    hora_actual = ultima_corrida.iloc[0]["hora_captura"]

    print("Última corrida detectada:")
    print(ultima_corrida.to_string(index=False))

    # ==========================================================
    # 2. Oportunidades actuales para dashboard
    # ==========================================================
    opp_actual = read_sql(conn, """
        SELECT
            fecha_captura,
            hora_captura,
            id_corrida,
            ean_norm,
            producto_referencia,
            retailer,
            categoria,
            marca,
            nombre_producto_original,
            precio_actual,
            precio_minimo,
            precio_maximo,
            precio_promedio,
            brecha_vs_minimo_pesos,
            brecha_vs_minimo_pct,
            brecha_vs_promedio_pct,
            cantidad_retailers,
            ranking_precio,
            posicion_competitiva,
            alerta_pricing,
            prioridad,
            accion_sugerida,
            tipo_promocion,
            url_producto
        FROM oportunidades_historicas
        WHERE id_corrida = :id_corrida
    """, {"id_corrida": id_corrida})

    prioridad_orden = {
        "ALTA": 1,
        "MEDIA": 2,
        "BAJA": 3,
    }

    alerta_orden = {
        "SOBREPRECIO FUERTE": 1,
        "SOBREPRECIO MODERADO": 2,
        "SOBREPRECIO LEVE": 3,
        "COMPETITIVO": 4,
        "LIDER PRECIO": 5,
    }

    opp_actual["orden_prioridad"] = opp_actual["prioridad"].map(prioridad_orden).fillna(9)
    opp_actual["orden_alerta"] = opp_actual["alerta_pricing"].map(alerta_orden).fillna(9)

    opp_actual = opp_actual.sort_values(
        by=[
            "orden_prioridad",
            "orden_alerta",
            "brecha_vs_minimo_pct",
            "brecha_vs_minimo_pesos",
        ],
        ascending=[True, True, False, False],
    ).drop(columns=["orden_prioridad", "orden_alerta"])

    opp_actual.to_csv(OUT_OPP_ACTUAL, index=False, encoding="utf-8-sig")
    print(f"Generado: {OUT_OPP_ACTUAL} ({len(opp_actual)} filas)")

    # ==========================================================
    # 3. Resumen actual ejecutivo
    # ==========================================================
    total_oportunidades = len(opp_actual)
    total_eans = opp_actual["ean_norm"].nunique()
    total_retailers = opp_actual["retailer"].nunique()

    resumen_alertas = (
        opp_actual
        .groupby("alerta_pricing", dropna=False)
        .size()
        .reset_index(name="cantidad")
    )

    resumen_prioridad = (
        opp_actual
        .groupby("prioridad", dropna=False)
        .size()
        .reset_index(name="cantidad")
    )

    resumen_retailer = (
        opp_actual
        .groupby("retailer", dropna=False)
        .agg(
            oportunidades=("ean_norm", "count"),
            eans_unicos=("ean_norm", "nunique"),
            precio_promedio=("precio_actual", "mean"),
            brecha_promedio_pct=("brecha_vs_minimo_pct", "mean"),
            sobreprecio_fuerte=("alerta_pricing", lambda s: (s == "SOBREPRECIO FUERTE").sum()),
            lider_precio=("alerta_pricing", lambda s: (s == "LIDER PRECIO").sum()),
            competitivos=("alerta_pricing", lambda s: (s == "COMPETITIVO").sum()),
        )
        .reset_index()
    )

    filas_resumen = []

    filas_resumen.append({
        "bloque": "general",
        "metrica": "fecha_actual",
        "valor": fecha_actual,
    })
    filas_resumen.append({
        "bloque": "general",
        "metrica": "hora_actual",
        "valor": hora_actual,
    })
    filas_resumen.append({
        "bloque": "general",
        "metrica": "id_corrida",
        "valor": id_corrida,
    })
    filas_resumen.append({
        "bloque": "general",
        "metrica": "total_oportunidades",
        "valor": total_oportunidades,
    })
    filas_resumen.append({
        "bloque": "general",
        "metrica": "total_eans_con_alerta",
        "valor": total_eans,
    })
    filas_resumen.append({
        "bloque": "general",
        "metrica": "total_retailers",
        "valor": total_retailers,
    })

    for _, r in resumen_alertas.iterrows():
        filas_resumen.append({
            "bloque": "alerta_pricing",
            "metrica": str(r["alerta_pricing"]),
            "valor": int(r["cantidad"]),
        })

    for _, r in resumen_prioridad.iterrows():
        filas_resumen.append({
            "bloque": "prioridad",
            "metrica": str(r["prioridad"]),
            "valor": int(r["cantidad"]),
        })

    resumen_actual = pd.DataFrame(filas_resumen)
    resumen_actual.to_csv(OUT_RESUMEN, index=False, encoding="utf-8-sig")
    print(f"Generado: {OUT_RESUMEN} ({len(resumen_actual)} filas)")

    resumen_retailer.to_csv(OUT_KPIS_RETAILER, index=False, encoding="utf-8-sig")
    print(f"Generado: {OUT_KPIS_RETAILER} ({len(resumen_retailer)} filas)")

    # ==========================================================
    # 4. Evolución de alertas
    # ==========================================================
    evolucion_alertas = read_sql(conn, """
        SELECT
            fecha_captura,
            hora_captura,
            id_corrida,
            retailer,
            alerta_pricing,
            prioridad,
            COUNT(*) AS cantidad_oportunidades,
            COUNT(DISTINCT ean_norm) AS eans_unicos,
            AVG(precio_actual) AS precio_actual_promedio,
            AVG(brecha_vs_minimo_pct) AS brecha_vs_minimo_pct_promedio,
            AVG(brecha_vs_promedio_pct) AS brecha_vs_promedio_pct_promedio
        FROM oportunidades_historicas
        GROUP BY
            fecha_captura,
            hora_captura,
            id_corrida,
            retailer,
            alerta_pricing,
            prioridad
        ORDER BY
            fecha_captura,
            hora_captura,
            retailer,
            alerta_pricing
    """)

    evolucion_alertas.to_csv(OUT_EVOL_ALERTAS, index=False, encoding="utf-8-sig")
    print(f"Generado: {OUT_EVOL_ALERTAS} ({len(evolucion_alertas)} filas)")

    # ==========================================================
    # 5. Evolución histórica de precios
    # ==========================================================
    evolucion_precios = read_sql(conn, """
        SELECT
            c.fecha_captura,
            c.hora_captura,
            pf.retailer,
            pf.ean_detectado AS ean_norm,
            pf.nombre_original AS nombre_producto,
            pf.marca_original AS marca,
            pf.categoria_original AS categoria,
            c.precio_actual,
            c.precio_regular,
            c.precio_oferta,
            c.precio_por_unidad,
            c.unidad_precio,
            c.tipo_promocion,
            c.texto_promocion,
            c.disponibilidad,
            c.es_cambio_precio,
            pf.url_producto,
            pf.url_imagen
        FROM capturas_precio c
        JOIN productos_fuente pf
          ON pf.id_producto_fuente = c.id_producto_fuente
        WHERE c.precio_actual IS NOT NULL
        ORDER BY
            c.fecha_captura,
            c.hora_captura,
            pf.retailer,
            pf.ean_detectado
    """)

    # Métricas útiles para frontend
    evolucion_precios["fecha_hora_captura"] = (
        evolucion_precios["fecha_captura"].astype(str)
        + " "
        + evolucion_precios["hora_captura"].astype(str)
    )

    evolucion_precios.to_csv(OUT_EVOL_PRECIOS, index=False, encoding="utf-8-sig")
    print(f"Generado: {OUT_EVOL_PRECIOS} ({len(evolucion_precios)} filas)")

    # ==========================================================
    # Resumen final
    # ==========================================================
    print("\nRESUMEN DATASETS DASHBOARD")
    print("-" * 80)
    print(f"Última corrida: {id_corrida} | {fecha_actual} {hora_actual}")
    print(f"Oportunidades actuales: {len(opp_actual)}")
    print(f"EANs únicos actuales: {total_eans}")
    print(f"Retailers actuales: {total_retailers}")
    print(f"Evolución alertas: {len(evolucion_alertas)} filas")
    print(f"Evolución precios: {len(evolucion_precios)} filas")

    print("\nKPIs por retailer:")
    print(resumen_retailer.to_string(index=False))

    conn.close()


if __name__ == "__main__":
    main()
