import os
import pandas as pd
from pathlib import Path

# Resolve directories
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(BACKEND_DIR)

INPUT = os.path.join(ROOT_DIR, "outputs", "matching_ean_competitivo.csv")
OUTPUT = os.path.join(ROOT_DIR, "outputs", "oportunidades_pricing_ean_accionables.csv")
RESUMEN = os.path.join(ROOT_DIR, "outputs", "resumen_oportunidades_pricing_ean_accionables.csv")


df = pd.read_csv(INPUT, low_memory=False)

df["precio_actual"] = pd.to_numeric(df["precio_actual"], errors="coerce")
df["precio_minimo"] = pd.to_numeric(df["precio_minimo"], errors="coerce")
df["precio_promedio"] = pd.to_numeric(df["precio_promedio"], errors="coerce")
df["brecha_vs_minimo_%"] = pd.to_numeric(df["brecha_vs_minimo_%"], errors="coerce")
df["brecha_vs_promedio_%"] = pd.to_numeric(df["brecha_vs_promedio_%"], errors="coerce")

# Excluir capturas con bug de escala (x100) detectadas en el matching:
# son errores de dato, no situaciones reales de precio. Si entran, saturan
# las alertas como "SOBREPRECIO FUERTE / ALTA" falsos.
if "precio_sospechoso" in df.columns:
    df["precio_sospechoso"] = pd.to_numeric(df["precio_sospechoso"], errors="coerce").fillna(0)
    n_susp = int((df["precio_sospechoso"] == 1).sum())
    df = df[df["precio_sospechoso"] == 0].copy()
    print(f"Capturas sospechosas (bug escala) excluidas de oportunidades: {n_susp}")


def clasificar_alerta(row):
    brecha = row["brecha_vs_minimo_%"]

    if pd.isna(brecha):
        return "SIN_DATO"

    if brecha == 0:
        return "LIDER PRECIO"

    if brecha <= 5:
        return "COMPETITIVO"

    if brecha <= 15:
        return "SOBREPRECIO LEVE"

    if brecha <= 30:
        return "SOBREPRECIO MODERADO"

    return "SOBREPRECIO FUERTE"


def accion_sugerida(row):
    alerta = row["alerta_pricing"]

    if alerta == "LIDER PRECIO":
        return "Mantener posicion. Monitorear margen y reaccion competitiva."

    if alerta == "COMPETITIVO":
        return "No requiere accion inmediata. Mantener seguimiento."

    if alerta == "SOBREPRECIO LEVE":
        return "Revisar si la diferencia responde a promo, margen o posicionamiento."

    if alerta == "SOBREPRECIO MODERADO":
        return "Analizar ajuste de precio o accion promocional selectiva."

    if alerta == "SOBREPRECIO FUERTE":
        return "Prioridad alta: revisar precio, promo o estrategia frente al competidor mas barato."

    return "Revisar dato."


df["alerta_pricing"] = df.apply(clasificar_alerta, axis=1)
df["accion_sugerida"] = df.apply(accion_sugerida, axis=1)

# Brecha en pesos contra el minimo
df["brecha_vs_minimo_$"] = pd.to_numeric(df["brecha_vs_minimo_$"], errors="coerce")


# Prioridad ejecutiva
def prioridad(row):
    alerta = row["alerta_pricing"]

    if alerta == "SOBREPRECIO FUERTE":
        return "ALTA"
    if alerta == "SOBREPRECIO MODERADO":
        return "MEDIA"
    if alerta == "SOBREPRECIO LEVE":
        return "BAJA"
    if alerta == "LIDER PRECIO":
        return "OPORTUNIDAD DEFENSIVA"
    return "MONITOREO"


df["prioridad"] = df.apply(prioridad, axis=1)

# Orden ejecutivo: primero problemas mas fuertes
orden_alerta = {
    "SOBREPRECIO FUERTE": 1,
    "SOBREPRECIO MODERADO": 2,
    "SOBREPRECIO LEVE": 3,
    "COMPETITIVO": 4,
    "LIDER PRECIO": 5,
    "SIN_DATO": 6,
}

df["orden_alerta"] = df["alerta_pricing"].map(orden_alerta).fillna(99)

columnas = [
    "ean_norm",
    "producto_referencia",
    "retailer",
    "categoria",
    "marca",
    "nombre_producto_original",
    "precio_actual",
    "precio_minimo",
    "precio_maximo",
    "precio_promedio",
    "brecha_vs_minimo_$",
    "brecha_vs_minimo_%",
    "brecha_vs_promedio_%",
    "cantidad_retailers",
    "ranking_precio",
    "posicion_competitiva",
    "alerta_pricing",
    "prioridad",
    "accion_sugerida",
    "tipo_promocion",
    "url_producto",
]

columnas = [c for c in columnas if c in df.columns]

salida = df[columnas + ["orden_alerta"]].copy()
salida = salida.sort_values(
    ["orden_alerta", "brecha_vs_minimo_%", "brecha_vs_minimo_$"],
    ascending=[True, False, False]
).drop(columns=["orden_alerta"])

Path(os.path.join(ROOT_DIR, "outputs")).mkdir(exist_ok=True)
salida.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

# Resumen ejecutivo
resumen_alertas = (
    salida.groupby(["retailer", "alerta_pricing"])
    .size()
    .reset_index(name="cantidad")
    .sort_values(["retailer", "cantidad"], ascending=[True, False])
)

resumen_alertas.to_csv(RESUMEN, index=False, encoding="utf-8-sig")

print("Oportunidades generadas:", OUTPUT)
print("Resumen generado:", RESUMEN)
print()
print("RESUMEN POR RETAILER Y ALERTA")
print(resumen_alertas.to_string(index=False))
print()
print("TOP 30 OPORTUNIDADES / SOBREPRECIOS FUERTES")
top = salida[salida["alerta_pricing"] == "SOBREPRECIO FUERTE"].head(30)
print(top.to_string(index=False))
