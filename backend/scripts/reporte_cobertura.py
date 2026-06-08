"""Genera outputs/reporte_cobertura_universal.csv desde la DB."""

import os
import sys
import yaml
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from db.database import Database

with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

db = Database(config["db"])
db.inicializar("db/schema.sql")
df = db.exportar_capturas_df()
os.makedirs("outputs", exist_ok=True)

if df.empty:
    print("No hay capturas en la base.")
    raise SystemExit(0)

resumen = df.groupby(["retailer", "categoria"], dropna=False).agg(
    productos_capturados=("nombre_producto_original", "count"),
    productos_con_precio=("precio_actual", lambda s: int(s.notna().sum())),
    productos_con_ean=("ean", lambda s: int(s.notna().sum())),
    productos_con_marca=("marca", lambda s: int(s.notna().sum())),
    productos_marca_propia=("tipo_marca", lambda s: int((s == "marca_propia").sum())),
    productos_con_oferta=("tipo_promocion", lambda s: int((s == "OFERTA").sum())),
    productos_sin_stock=("tipo_promocion", lambda s: int((s == "SIN_STOCK").sum())),
    errores=("estado_captura", lambda s: int((s == "error").sum())),
    score_promedio=("score_confianza_dato", "mean"),
).reset_index()

resumen["score_promedio"] = resumen["score_promedio"].round(3)
ruta = "outputs/reporte_cobertura_universal.csv"
resumen.to_csv(ruta, index=False, encoding="utf-8-sig")
print(f"Reporte generado: {ruta}")
print(resumen.to_string(index=False))
