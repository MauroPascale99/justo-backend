import pandas as pd
from pathlib import Path

INPUT = "outputs/capturas_normalizadas_final_db.csv"
OUTPUT = "outputs/reporte_calidad_fuentes.csv"

df = pd.read_csv(INPUT, low_memory=False)

# Normalización básica de campos esperados
df["precio_valido"] = df["precio_actual"].notna()
df["disponible"] = df["disponibilidad"].fillna(0).astype(int) == 1
df["producto_util_pricing"] = df["precio_valido"] & df["disponible"]

df["ean_valido"] = (
    df["ean"].notna()
    & (df["ean"].astype(str).str.strip() != "")
    & (df["ean"].astype(str).str.lower() != "nan")
)

df["marca_valida"] = (
    df["marca"].notna()
    & (df["marca"].astype(str).str.strip() != "")
    & (df["marca"].astype(str).str.lower() != "nan")
)

registros = []

for retailer, g in df.groupby("retailer"):
    total = len(g)
    con_precio = int(g["precio_valido"].sum())
    disponibles = int(g["disponible"].sum())
    utiles = int(g["producto_util_pricing"].sum())
    sin_stock = int((~g["disponible"]).sum())
    con_ean = int(g["ean_valido"].sum())
    con_marca = int(g["marca_valida"].sum())

    pct_precio = con_precio / total if total else 0
    pct_disponible = disponibles / total if total else 0
    pct_util = utiles / total if total else 0
    pct_sin_stock = sin_stock / total if total else 0
    pct_ean = con_ean / total if total else 0
    pct_marca = con_marca / total if total else 0

    # Regla simple de estado
    if pct_util >= 0.80 and pct_precio >= 0.90:
        estado = "OK"
    elif pct_util >= 0.25:
        estado = "REVISAR / USAR SOLO DISPONIBLES"
    else:
        estado = "NO CONFIABLE"

    # Lectura ejecutiva
    if retailer == "coto":
        comentario = "Fuente muy sólida: catálogo completo con precio y disponibilidad."
    elif retailer == "dia":
        comentario = "Fuente sólida: buena cobertura útil, con diferencia razonable por productos sin stock."
    elif retailer == "changomas":
        comentario = "Fuente técnicamente válida, pero con mucho catálogo no disponible. Usar solo base útil para pricing."
    else:
        comentario = "Fuente pendiente de evaluación."

    registros.append({
        "retailer": retailer,
        "productos_totales": total,
        "productos_con_precio": con_precio,
        "productos_disponibles": disponibles,
        "productos_utiles_pricing": utiles,
        "productos_sin_stock": sin_stock,
        "productos_con_ean": con_ean,
        "productos_con_marca": con_marca,
        "%_con_precio": round(pct_precio * 100, 2),
        "%_disponible": round(pct_disponible * 100, 2),
        "%_util_pricing": round(pct_util * 100, 2),
        "%_sin_stock": round(pct_sin_stock * 100, 2),
        "%_con_ean": round(pct_ean * 100, 2),
        "%_con_marca": round(pct_marca * 100, 2),
        "estado_fuente": estado,
        "comentario": comentario,
    })

reporte = pd.DataFrame(registros)

# Agregar fila total
total = len(df)
fila_total = {
    "retailer": "TOTAL",
    "productos_totales": total,
    "productos_con_precio": int(df["precio_valido"].sum()),
    "productos_disponibles": int(df["disponible"].sum()),
    "productos_utiles_pricing": int(df["producto_util_pricing"].sum()),
    "productos_sin_stock": int((~df["disponible"]).sum()),
    "productos_con_ean": int(df["ean_valido"].sum()),
    "productos_con_marca": int(df["marca_valida"].sum()),
    "%_con_precio": round(df["precio_valido"].mean() * 100, 2),
    "%_disponible": round(df["disponible"].mean() * 100, 2),
    "%_util_pricing": round(df["producto_util_pricing"].mean() * 100, 2),
    "%_sin_stock": round((~df["disponible"]).mean() * 100, 2),
    "%_con_ean": round(df["ean_valido"].mean() * 100, 2),
    "%_con_marca": round(df["marca_valida"].mean() * 100, 2),
    "estado_fuente": "RESUMEN",
    "comentario": "Resumen consolidado de todas las fuentes.",
}

reporte = pd.concat([reporte, pd.DataFrame([fila_total])], ignore_index=True)

Path("outputs").mkdir(exist_ok=True)
reporte.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

print("Reporte generado:", OUTPUT)
print()
print(reporte.to_string(index=False))
