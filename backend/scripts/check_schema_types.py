import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()  # toma el .env del entorno/cwd del backend (sin ruta fija)
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

for table in ["productos_cliente", "alertas_cliente", "mapa_competitivo_cliente"]:
    print(f"\n=== Schema of {table} ===")
    cur.execute(f"""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = '{table}'
    """)
    for r in cur.fetchall():
        print(f"  {r[0]}: {r[1]}")

cur.close()
conn.close()
