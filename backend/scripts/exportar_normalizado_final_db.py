import sys
import os
import yaml
import pandas as pd
from pathlib import Path
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
out_path = os.path.join(ROOT_DIR, "outputs", "capturas_normalizadas_final_db.csv")

query = """
SELECT
    cp.fecha_captura,
    cp.hora_captura,
    pf.retailer,
    pf.categoria_original AS categoria,
    pf.subcategoria_original AS subcategoria,
    pf.nombre_original AS nombre_producto_original,
    pf.nombre_original AS nombre_producto_limpio,
    pf.marca_original AS marca,
    pf.tipo_marca,
    pf.marca_original AS marca_original_fuente,
    pf.ean_detectado AS ean,
    NULL AS contenido,
    NULL AS unidad_medida,
    NULL AS formato,
    cp.precio_actual,
    cp.precio_regular,
    cp.precio_oferta,
    cp.precio_por_unidad,
    cp.unidad_precio,
    cp.tipo_promocion,
    cp.texto_promocion,
    cp.disponibilidad,
    pf.url_producto,
    pf.url_imagen,
    cp.score_confianza_dato,
    cp.estado_captura,
    cp.hash_captura
FROM productos_fuente pf
LEFT JOIN capturas_precio cp
    ON cp.id_producto_fuente = pf.id_producto_fuente
"""

conn = db._get_connection()
df = pd.read_sql_query(query, conn)
conn.close()

outputs_dir = os.path.join(ROOT_DIR, "outputs")
Path(outputs_dir).mkdir(exist_ok=True)

# Ordenar para quedarnos con la última captura disponible por producto.
df = df.sort_values(["retailer", "nombre_producto_original", "fecha_captura", "hora_captura"])

# Clave conservadora para evitar duplicados del CSV final.
# Si hay URL, manda URL. Si no, usamos EAN. Si no, nombre + categoría.
df["clave_export"] = (
    df["retailer"].fillna("").astype(str)
    + "|"
    + df["url_producto"].fillna("").astype(str)
    + "|"
    + df["ean"].fillna("").astype(str)
    + "|"
    + df["nombre_producto_original"].fillna("").astype(str)
    + "|"
    + df["categoria"].fillna("").astype(str)
)

df = df.drop_duplicates(subset=["clave_export"], keep="last")
df = df.drop(columns=["clave_export"])

df.to_csv(out_path, index=False, encoding="utf-8-sig")

print("CSV final limpio generado:", out_path)
print("Total filas:", len(df))

print("\nPor retailer:")
print(df["retailer"].value_counts())

print("\nCon precio por retailer:")
print(df[df["precio_actual"].notna()]["retailer"].value_counts())

print("\nSin stock por retailer:")
print(df[df["disponibilidad"].fillna(1).astype(int) == 0]["retailer"].value_counts())
