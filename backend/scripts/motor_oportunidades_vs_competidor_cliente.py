import sys
import os
import yaml
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

# Resolve directories
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(BACKEND_DIR)

# Load environment variables
load_dotenv(dotenv_path=os.path.join(ROOT_DIR, ".env"))

# Insert backend directory in sys.path
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from db.database import Database

# Load config
config_path = os.path.join(BACKEND_DIR, "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

db = Database(config["db"])
OUT = Path(os.path.join(ROOT_DIR, "outputs", "dashboard_oportunidades_vs_competidor_actual.csv"))
OUT.parent.mkdir(exist_ok=True)

COLUMNAS = [
    "id_cliente",
    "nombre_cliente",
    "id_producto_cliente",
    "ean_propio",
    "producto_propio",
    "marca_propia",
    "categoria",
    "precio_sugerido_proveedor",
    "precio_promedio_propio",
    "precio_minimo_propio",
    "precio_maximo_propio",
    "cantidad_retailers_propio",
    "id_mapa",
    "ean_competidor",
    "competidor_directo",
    "marca_competidor",
    "rol_competidor",
    "precio_promedio_competidor_actual",
    "precio_promedio_competidor_anterior",
    "variacion_competidor_pct",
    "brecha_actual_vs_competidor_pct",
    "brecha_objetivo_pct",
    "precio_objetivo_justo",
    "oportunidad_suba_pct",
    "oportunidad_suba_pesos",
    "alerta_oportunidad",
    "prioridad",
    "accion_sugerida",
    "retailers_propio",
    "retailers_competidor",
]

def empty_output(motivo):
    df = pd.DataFrame(columns=COLUMNAS)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"Generado vacío: {OUT}")
    print(f"Motivo: {motivo}")

def main():
    conn = db._get_connection()

    clientes = pd.read_sql_query("SELECT * FROM clientes WHERE estado = 'activo'", conn)
    # Usar activo = true para compatibilidad con Postgres y SQLite
    productos = pd.read_sql_query("SELECT * FROM productos_cliente WHERE activo = true", conn)
    mapa = pd.read_sql_query("SELECT * FROM mapa_competitivo_cliente WHERE activo = true", conn)
    config = pd.read_sql_query("SELECT * FROM configuracion_pricing_cliente", conn)

    if clientes.empty:
        conn.close()
        empty_output("No hay clientes cargados.")
        return

    if productos.empty:
        conn.close()
        empty_output("No hay productos propios cargados.")
        return

    if mapa.empty:
        conn.close()
        empty_output("No hay mapa competitivo cargado.")
        return

    # Capturas históricas enriquecidas con producto fuente.
    capturas = pd.read_sql_query("""
        SELECT
            c.fecha_captura,
            c.hora_captura,
            c.precio_actual,
            c.disponibilidad,
            pf.id_producto_fuente,
            pf.retailer,
            pf.ean_detectado,
            pf.nombre_original,
            pf.marca_original,
            pf.categoria_original
        FROM capturas_precio c
        JOIN productos_fuente pf
          ON pf.id_producto_fuente = c.id_producto_fuente
        WHERE c.precio_actual IS NOT NULL
          AND c.precio_actual > 0
    """, conn)

    conn.close()

    if capturas.empty:
        empty_output("No hay capturas de precio disponibles.")
        return

    # Normalización básica de EAN.
    capturas["ean_norm"] = capturas["ean_detectado"].astype(str).str.strip()
    productos["ean_norm"] = productos["ean"].astype(str).str.strip()
    mapa["ean_competidor_norm"] = mapa["ean_competidor"].astype(str).str.strip()

    # Última fecha disponible.
    ultima_fecha = capturas["fecha_captura"].max()
    fechas = sorted(capturas["fecha_captura"].dropna().unique())
    fecha_anterior = fechas[-2] if len(fechas) >= 2 else None

    actual = capturas[capturas["fecha_captura"] == ultima_fecha].copy()
    anterior = capturas[capturas["fecha_captura"] == fecha_anterior].copy() if fecha_anterior else pd.DataFrame(columns=capturas.columns)

    rows = []

    for _, prod in productos.iterrows():
        id_cliente = prod["id_cliente"]
        id_producto_cliente = prod["id_producto_cliente"]
        ean_propio = str(prod.get("ean_norm", "")).strip()

        mapas_prod = mapa[
            (mapa["id_cliente"] == id_cliente)
            & (mapa["id_producto_cliente"] == id_producto_cliente)
        ].copy()

        if mapas_prod.empty:
            continue

        cap_propio = actual[actual["ean_norm"] == ean_propio].copy()

        if cap_propio.empty:
            continue

        precio_promedio_propio = cap_propio["precio_actual"].mean()
        precio_minimo_propio = cap_propio["precio_actual"].min()
        precio_maximo_propio = cap_propio["precio_actual"].max()
        retailers_propio = ", ".join(sorted(cap_propio["retailer"].dropna().astype(str).unique()))
        cantidad_retailers_propio = cap_propio["retailer"].nunique()

        cfg = config[
            (config["id_cliente"] == id_cliente)
            & (config["id_producto_cliente"] == id_producto_cliente)
        ]

        precio_sugerido_proveedor = None
        brecha_default = -5.0

        if not cfg.empty:
            precio_sugerido_proveedor = cfg.iloc[0].get("precio_sugerido")
            # Interpretación: si el proveedor carga brecha_max_vs_competidor = 10,
            # lo usamos como tolerancia máxima. Para oportunidad de suba queremos
            # una brecha objetivo configurable. Por default dejamos -5%.
            if pd.notna(cfg.iloc[0].get("brecha_max_vs_competidor")):
                brecha_default = -abs(float(cfg.iloc[0].get("brecha_max_vs_competidor")))

        for _, mp in mapas_prod.iterrows():
            ean_comp = str(mp.get("ean_competidor_norm", "")).strip()

            if not ean_comp:
                continue

            cap_comp_actual = actual[actual["ean_norm"] == ean_comp].copy()
            cap_comp_anterior = anterior[anterior["ean_norm"] == ean_comp].copy() if not anterior.empty else pd.DataFrame()

            if cap_comp_actual.empty:
                continue

            precio_comp_actual = cap_comp_actual["precio_actual"].mean()
            precio_comp_anterior = cap_comp_anterior["precio_actual"].mean() if not cap_comp_anterior.empty else None

            if precio_comp_anterior and precio_comp_anterior > 0:
                variacion_comp_pct = ((precio_comp_actual - precio_comp_anterior) / precio_comp_anterior) * 100
            else:
                variacion_comp_pct = None

            if precio_comp_actual and precio_comp_actual > 0:
                brecha_actual = ((precio_promedio_propio - precio_comp_actual) / precio_comp_actual) * 100
            else:
                brecha_actual = None

            # Prioridad: brecha del mapa si existe. Si no, config. Si no, -5%.
            brecha_objetivo = mp.get("brecha_maxima_pct")
            if pd.isna(brecha_objetivo):
                brecha_objetivo = mp.get("brecha_minima_pct")
            if pd.isna(brecha_objetivo):
                brecha_objetivo = brecha_default

            brecha_objetivo = float(brecha_objetivo)

            precio_objetivo = precio_comp_actual * (1 + brecha_objetivo / 100)

            oportunidad_pesos = precio_objetivo - precio_promedio_propio
            oportunidad_pct = (oportunidad_pesos / precio_promedio_propio) * 100 if precio_promedio_propio else 0

            competidor_subio = variacion_comp_pct is not None and variacion_comp_pct > 0
            hay_espacio = oportunidad_pesos > 0

            if competidor_subio and hay_espacio and oportunidad_pct >= 3:
                alerta = "OPORTUNIDAD DE AUMENTO"
                prioridad = "ALTA" if oportunidad_pct >= 8 else "MEDIA"
                accion = (
                    f"El competidor directo subió {variacion_comp_pct:.1f}% y la brecha permite subir "
                    f"hasta ${precio_objetivo:,.0f} manteniendo objetivo {brecha_objetivo:.1f}%."
                )
            elif hay_espacio and oportunidad_pct >= 3:
                alerta = "ESPACIO DE PRECIO"
                prioridad = "MEDIA"
                accion = (
                    f"Hay espacio para aumentar hasta ${precio_objetivo:,.0f} manteniendo la brecha objetivo "
                    f"{brecha_objetivo:.1f}% vs competidor."
                )
            elif brecha_actual is not None and brecha_actual > brecha_objetivo:
                alerta = "REVISAR SOBREPRECIO VS COMPETIDOR"
                prioridad = "ALTA"
                accion = "El producto quedó por encima de la brecha objetivo frente al competidor directo."
            else:
                alerta = "SIN OPORTUNIDAD DIRECTA"
                prioridad = "BAJA"
                accion = "No se detecta oportunidad de aumento según la brecha objetivo configurada."

            retailers_comp = ", ".join(sorted(cap_comp_actual["retailer"].dropna().astype(str).unique()))

            cli = clientes[clientes["id_cliente"] == id_cliente]
            nombre_cliente = cli.iloc[0]["nombre_cliente"] if not cli.empty else ""

            rows.append({
                "id_cliente": id_cliente,
                "nombre_cliente": nombre_cliente,
                "id_producto_cliente": id_producto_cliente,
                "ean_propio": ean_propio,
                "producto_propio": prod.get("nombre_producto"),
                "marca_propia": prod.get("marca"),
                "categoria": prod.get("categoria"),
                "precio_sugerido_proveedor": precio_sugerido_proveedor,
                "precio_promedio_propio": precio_promedio_propio,
                "precio_minimo_propio": precio_minimo_propio,
                "precio_maximo_propio": precio_maximo_propio,
                "cantidad_retailers_propio": cantidad_retailers_propio,
                "id_mapa": mp.get("id_mapa"),
                "ean_competidor": ean_comp,
                "competidor_directo": mp.get("nombre_competidor"),
                "marca_competidor": mp.get("marca_competidor"),
                "rol_competidor": mp.get("rol_competidor"),
                "precio_promedio_competidor_actual": precio_comp_actual,
                "precio_promedio_competidor_anterior": precio_comp_anterior,
                "variacion_competidor_pct": variacion_comp_pct,
                "brecha_actual_vs_competidor_pct": brecha_actual,
                "brecha_objetivo_pct": brecha_objetivo,
                "precio_objetivo_justo": precio_objetivo,
                "oportunidad_suba_pct": oportunidad_pct,
                "oportunidad_suba_pesos": oportunidad_pesos,
                "alerta_oportunidad": alerta,
                "prioridad": prioridad,
                "accion_sugerida": accion,
                "retailers_propio": retailers_propio,
                "retailers_competidor": retailers_comp,
            })

    df = pd.DataFrame(rows, columns=COLUMNAS)

    if not df.empty:
        df = df.sort_values(
            by=["prioridad", "oportunidad_suba_pct"],
            ascending=[True, False]
        )

    df.to_csv(OUT, index=False, encoding="utf-8-sig")

    print(f"Generado: {OUT}")
    print(f"Filas: {len(df)}")

    if df.empty:
        print("Sin oportunidades porque todavía no hay productos/competidores configurados o no hubo match.")
    else:
        print(df[[
            "producto_propio",
            "competidor_directo",
            "precio_promedio_propio",
            "precio_promedio_competidor_actual",
            "brecha_actual_vs_competidor_pct",
            "brecha_objetivo_pct",
            "oportunidad_suba_pct",
            "alerta_oportunidad",
            "prioridad",
        ]].head(20).to_string(index=False))

if __name__ == "__main__":
    main()
