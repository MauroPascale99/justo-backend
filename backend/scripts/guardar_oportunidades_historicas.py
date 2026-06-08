import sys
import os
import yaml
import hashlib
import uuid
from datetime import datetime
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
INPUT = os.path.join(ROOT_DIR, "outputs", "oportunidades_pricing_ean_accionables.csv")

def limpiar_columna(col):
    return str(col).strip()

def valor(row, col, default=None):
    return row[col] if col in row.index else default

def to_float(x):
    try:
        if pd.isna(x):
            return None
        return float(x)
    except Exception:
        return None

def to_int(x):
    try:
        if pd.isna(x):
            return None
        return int(float(x))
    except Exception:
        return None

def crear_hash(row, fecha_captura, hora_captura):
    partes = [
        fecha_captura,
        hora_captura,
        str(valor(row, "ean_norm", "")),
        str(valor(row, "retailer", "")),
        str(valor(row, "precio_actual", "")),
        str(valor(row, "alerta_pricing", "")),
        str(valor(row, "ranking_precio", "")),
    ]
    raw = "|".join(partes)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def main():
    path = Path(INPUT)

    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo de oportunidades: {INPUT}")

    df = pd.read_csv(path, low_memory=False)
    df.columns = [limpiar_columna(c) for c in df.columns]

    ahora = datetime.now()
    fecha_captura = ahora.strftime("%Y-%m-%d")
    hora_captura = ahora.strftime("%H:%M:%S")
    id_corrida = ahora.strftime("%Y%m%d_%H%M%S")

    print(f"Guardando oportunidades históricas desde: {INPUT}")
    print(f"Filas origen: {len(df)}")
    print(f"Fecha captura: {fecha_captura}")
    print(f"Hora captura: {hora_captura}")
    print(f"ID corrida: {id_corrida}")

    conn = db._get_connection()
    cur = db.get_cursor_for_connection(conn)

    insertados = 0

    if db.db_type == "postgres":
        from psycopg2.extras import execute_values

        # 1. Map EANs to id_producto_cliente for id_cliente = 1
        cur.execute("SELECT id_producto_cliente, ean FROM productos_cliente WHERE id_cliente = 1")
        ean_to_product = {}
        for r in cur.fetchall():
            ean_to_product[str(r["ean"]).strip()] = r["id_producto_cliente"]

        # 2. Get cheapest retailer for each EAN in current run
        cheapest_df = df[df["ranking_precio"] == 1].drop_duplicates(subset=["ean_norm"])
        cheapest_retailers = dict(zip(cheapest_df["ean_norm"].astype(str), cheapest_df["retailer"].astype(str)))

        # 3. Prepare data for bulk insert
        data_to_insert = []
        for _, row in df.iterrows():
            ean_str = str(valor(row, "ean_norm", "")).strip()
            id_prod_cli = ean_to_product.get(ean_str)
            
            ret_propio = valor(row, "retailer")
            ret_comp_cheapest = cheapest_retailers.get(ean_str)
            ret_competidor = None if ret_propio == ret_comp_cheapest else ret_comp_cheapest

            id_oportunidad = str(uuid.uuid4())
            data_to_insert.append((
                id_oportunidad,
                1, # id_cliente = 1 (default)
                id_prod_cli,
                ean_str,
                ret_propio,
                ret_competidor,
                to_float(valor(row, "precio_actual")),
                to_float(valor(row, "precio_minimo")),
                to_float(valor(row, "brecha_vs_minimo_%")),
                valor(row, "alerta_pricing"),
                fecha_captura,
                False
            ))

        # 4. Bulk insert into Supabase
        execute_values(cur, """
            INSERT INTO oportunidades_historicas (
                id_oportunidad,
                id_cliente,
                id_producto_cliente,
                ean,
                retailer_propio,
                retailer_competidor,
                precio_propio,
                precio_competidor,
                brecha_pct,
                tipo_oportunidad,
                fecha_deteccion,
                procesada
            )
            VALUES %s
        """, data_to_insert)
        insertados = len(data_to_insert)

    else:
        # SQLite
        cur.execute("""
        CREATE TABLE IF NOT EXISTS oportunidades_historicas (
            id_oportunidad_historica INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_captura TEXT NOT NULL,
            hora_captura TEXT NOT NULL,
            id_corrida TEXT,
            ean_norm TEXT,
            producto_referencia TEXT,
            retailer TEXT,
            categoria TEXT,
            marca TEXT,
            nombre_producto_original TEXT,
            precio_actual REAL,
            precio_minimo REAL,
            precio_maximo REAL,
            precio_promedio REAL,
            brecha_vs_minimo_pesos REAL,
            brecha_vs_minimo_pct REAL,
            brecha_vs_promedio_pct REAL,
            cantidad_retailers INTEGER,
            ranking_precio INTEGER,
            posicion_competitiva TEXT,
            alerta_pricing TEXT,
            prioridad TEXT,
            accion_sugerida TEXT,
            tipo_promocion TEXT,
            url_producto TEXT,
            hash_oportunidad TEXT,
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        for _, row in df.iterrows():
            hash_oportunidad = crear_hash(row, fecha_captura, hora_captura)

            cur.execute("""
                INSERT INTO oportunidades_historicas (
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
                    url_producto,
                    hash_oportunidad
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                fecha_captura,
                hora_captura,
                id_corrida,
                str(valor(row, "ean_norm", "")),
                valor(row, "producto_referencia", None),
                valor(row, "retailer", None),
                valor(row, "categoria", None),
                valor(row, "marca", None),
                valor(row, "nombre_producto_original", None),
                to_float(valor(row, "precio_actual", None)),
                to_float(valor(row, "precio_minimo", None)),
                to_float(valor(row, "precio_maximo", None)),
                to_float(valor(row, "precio_promedio", None)),
                to_float(valor(row, "brecha_vs_minimo_$", None)),
                to_float(valor(row, "brecha_vs_minimo_%", None)),
                to_float(valor(row, "brecha_vs_promedio_%", None)),
                to_int(valor(row, "cantidad_retailers", None)),
                to_int(valor(row, "ranking_precio", None)),
                valor(row, "posicion_competitiva", None),
                valor(row, "alerta_pricing", None),
                valor(row, "prioridad", None),
                valor(row, "accion_sugerida", None),
                valor(row, "tipo_promocion", None),
                valor(row, "url_producto", None),
                hash_oportunidad,
            ))
            insertados += 1

    conn.commit()
    conn.close()

    print(f"Oportunidades históricas insertadas: {insertados}")

if __name__ == "__main__":
    main()
