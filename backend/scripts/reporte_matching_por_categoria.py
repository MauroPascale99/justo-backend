import os
import sys
import pandas as pd
from pathlib import Path

# Resolve directories
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(BACKEND_DIR)

BASE = os.path.join(ROOT_DIR, "outputs", "capturas_normalizadas_final_db.csv")
MATCH = os.path.join(ROOT_DIR, "outputs", "matching_ean_competitivo.csv")

OUT_CAT = os.path.join(ROOT_DIR, "outputs", "cobertura_matching_ean_por_categoria.csv")
OUT_CAT_RET = os.path.join(ROOT_DIR, "outputs", "cobertura_matching_ean_por_categoria_retailer.csv")
OUT_CORE = os.path.join(ROOT_DIR, "outputs", "cobertura_matching_ean_categorias_core.csv")

# Read files
df = pd.read_csv(BASE, low_memory=False)

if os.path.exists(MATCH):
    match_df = pd.read_csv(MATCH, low_memory=False)
    matched_eans = set(match_df["ean_norm"].dropna().astype(str).unique())
else:
    matched_eans = set()

# Normalize EAN and determine validity and matching status
df["ean_norm"] = (
    df["ean"]
    .fillna("")
    .astype(str)
    .str.replace(".0", "", regex=False)
    .str.strip()
)

df["ean_valido"] = (df["ean_norm"] != "") & (df["ean_norm"].str.lower() != "nan")
df["matcheado_ean"] = df["ean_norm"].isin(matched_eans)

# Normalizar categoría
df["categoria_norm"] = (
    df["categoria"]
    .fillna("SIN_CATEGORIA")
    .astype(str)
    .str.strip()
)

# Categorías core comerciales para pricing
categorias_core_keywords = [
    "almacen",
    "aceites",
    "arroz",
    "caldos",
    "condimentos",
    "conservas",
    "desayuno",
    "harinas",
    "kiosco",
    "snacks",
    "bebidas",
    "jugos",
    "fernet",
    "lacteos",
    "quesos",
    "frescos",
    "congelados",
    "limpieza",
    "perfumeria",
    "cuidado",
    "proteccion",
    "mascotas",
    "bebes",
    "ninos",
]

def es_core(categoria):
    c = str(categoria).lower()
    c = (
        c.replace("á", "a")
         .replace("é", "e")
         .replace("í", "i")
         .replace("ó", "o")
         .replace("ú", "u")
         .replace("ñ", "n")
     )
    return any(k in c for k in categorias_core_keywords)

df["categoria_core"] = df["categoria_norm"].apply(es_core)

# 1) Resumen por categoría total
cat = df.groupby("categoria_norm").agg(
    productos_utiles=("categoria_norm", "count"),
    productos_con_ean=("ean_valido", "sum"),
    productos_matcheados_ean=("matcheado_ean", "sum"),
    retailers_distintos=("retailer", "nunique"),
).reset_index()

cat["productos_no_matcheados_ean"] = (
    cat["productos_utiles"] - cat["productos_matcheados_ean"]
)

cat["%_con_ean"] = (
    cat["productos_con_ean"] / cat["productos_utiles"] * 100
).round(2)

cat["%_matcheado_sobre_total"] = (
    cat["productos_matcheados_ean"] / cat["productos_utiles"] * 100
).round(2)

cat["%_matcheado_sobre_con_ean"] = (
    cat["productos_matcheados_ean"] / cat["productos_con_ean"].replace(0, float('nan')) * 100
).round(2)

cat["categoria_core"] = cat["categoria_norm"].apply(es_core)

cat = cat.sort_values(
    ["categoria_core", "%_matcheado_sobre_total", "productos_utiles"],
    ascending=[False, False, False]
)

# 2) Resumen por categoría + retailer
cat_ret = df.groupby(["categoria_norm", "retailer"]).agg(
    productos_utiles=("retailer", "count"),
    productos_con_ean=("ean_valido", "sum"),
    productos_matcheados_ean=("matcheado_ean", "sum"),
).reset_index()

cat_ret["productos_no_matcheados_ean"] = (
    cat_ret["productos_utiles"] - cat_ret["productos_matcheados_ean"]
)

cat_ret["%_matcheado_sobre_total"] = (
    cat_ret["productos_matcheados_ean"] / cat_ret["productos_utiles"] * 100
).round(2)

cat_ret["categoria_core"] = cat_ret["categoria_norm"].apply(es_core)

cat_ret = cat_ret.sort_values(
    ["categoria_core", "categoria_norm", "%_matcheado_sobre_total"],
    ascending=[False, True, False]
)

# 3) Resumen solo categorías core
core = df[df["categoria_core"]].copy()

core_resumen = core.groupby("retailer").agg(
    productos_utiles_core=("retailer", "count"),
    productos_con_ean_core=("ean_valido", "sum"),
    productos_matcheados_ean_core=("matcheado_ean", "sum"),
).reset_index()

core_resumen["productos_no_matcheados_ean_core"] = (
    core_resumen["productos_utiles_core"] - core_resumen["productos_matcheados_ean_core"]
)

core_resumen["%_matcheado_core"] = (
    core_resumen["productos_matcheados_ean_core"] / core_resumen["productos_utiles_core"] * 100
).round(2)

total_core = pd.DataFrame([{
    "retailer": "TOTAL",
    "productos_utiles_core": len(core),
    "productos_con_ean_core": int(core["ean_valido"].sum()),
    "productos_matcheados_ean_core": int(core["matcheado_ean"].sum()),
    "productos_no_matcheados_ean_core": int((~core["matcheado_ean"]).sum()),
    "%_matcheado_core": round(core["matcheado_ean"].mean() * 100, 2)
}])

core_resumen = pd.concat([core_resumen, total_core], ignore_index=True)

Path(os.path.join(ROOT_DIR, "outputs")).mkdir(exist_ok=True)

cat.to_csv(OUT_CAT, index=False, encoding="utf-8-sig")
cat_ret.to_csv(OUT_CAT_RET, index=False, encoding="utf-8-sig")
core_resumen.to_csv(OUT_CORE, index=False, encoding="utf-8-sig")

print("Reporte por categoría generado:", OUT_CAT)
print("Reporte por categoría/retailer generado:", OUT_CAT_RET)
print("Reporte categorías core generado:", OUT_CORE)

print()
print("RESUMEN CATEGORÍAS CORE")
print(core_resumen.to_string(index=False))

print()
print("TOP 20 CATEGORÍAS CORE CON MAYOR COBERTURA")
print(cat[cat["categoria_core"]].head(20).to_string(index=False))

print()
print("TOP 20 CATEGORÍAS CON MENOR COBERTURA Y MAYOR VOLUMEN")
baja = cat[
    (cat["productos_utiles"] >= 100) &
    (cat["%_matcheado_sobre_total"] < 20)
].copy()
print(baja.head(20).to_string(index=False))
