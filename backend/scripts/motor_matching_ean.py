import pandas as pd
import numpy as np
from pathlib import Path

INPUT = "outputs/capturas_normalizadas_final_db.csv"
OUTPUT = "outputs/matching_ean_competitivo.csv"
RESUMEN = "outputs/resumen_matching_ean.csv"

# Deteccion de bug de escala (VTEX x100: precio devuelto en centavos).
# Una captura se marca sospechosa si su precio / 100 cae cerca (< TOL) de
# otro precio del MISMO EAN que sea al menos 10x menor. Esto detecta el
# inflado real sin castigar al precio correcto (a diferencia de usar la
# mediana del grupo, que falla cuando la mayoria del grupo esta corrupta).
TOL_ESCALA = 0.30


def detectar_escala_x100(g):
    vals = g["precio_comparacion"].values
    out = []
    for v in vals:
        es_x100 = any(
            abs((v / 100) - w) / w < TOL_ESCALA
            for w in vals
            if w > 0 and w != v and w < v / 10
        )
        out.append(int(es_x100))
    return pd.Series(out, index=g.index)


def main():
    df = pd.read_csv(INPUT, low_memory=False)

    # Precio de comparacion = precio regular (regla #3); fallback a actual.
    df["precio_actual"] = pd.to_numeric(df.get("precio_actual"), errors="coerce")
    df["precio_regular"] = pd.to_numeric(df.get("precio_regular"), errors="coerce")
    df["precio_oferta"] = pd.to_numeric(df.get("precio_oferta"), errors="coerce")
    df["precio_comparacion"] = df["precio_regular"].where(
        df["precio_regular"] > 0, df["precio_actual"]
    )

    # Filtro base util: precio comparacion valido + disponible.
    if "disponibilidad" in df.columns:
        disp = df["disponibilidad"].astype(str).str.lower().str.strip()
        df = df[
            df["precio_comparacion"].notna()
            & (df["precio_comparacion"] > 0)
            & (
                disp.isin(["1", "true", "disponible", "si", "si", "ok"])
                | df["disponibilidad"].eq(1)
                | df["disponibilidad"].eq(True)
            )
        ].copy()
    else:
        df = df[df["precio_comparacion"].notna() & (df["precio_comparacion"] > 0)].copy()

    print(f"Base util filtrada para matching: {len(df)} filas")
    print("Retailers en base util:")
    print(df["retailer"].value_counts())

    df["ean_norm"] = (
        df["ean"].fillna("").astype(str).str.replace(".0", "", regex=False).str.strip()
    )
    df = df[
        (df["ean_norm"] != "")
        & (df["ean_norm"].str.lower() != "nan")
        & (df["precio_comparacion"].notna())
    ].copy()

    df = df.sort_values(["ean_norm", "retailer", "precio_comparacion"])
    df = df.drop_duplicates(subset=["ean_norm", "retailer"], keep="first")

    retailers_por_ean = (
        df.groupby("ean_norm")["retailer"].nunique().reset_index()
        .rename(columns={"retailer": "cantidad_retailers"})
    )
    eans_competitivos = retailers_por_ean[
        retailers_por_ean["cantidad_retailers"] >= 2
    ]["ean_norm"]
    match = df[df["ean_norm"].isin(eans_competitivos)].copy()

    # Guarda anti-outlier (bug de escala x100), dirigida y robusta.
    match["precio_sospechoso"] = (
        match.groupby("ean_norm", group_keys=False)
        .apply(detectar_escala_x100, include_groups=False)
        .astype(int)
    )

    limpio = match[match["precio_sospechoso"] == 0].copy()

    metricas = limpio.groupby("ean_norm").agg(
        cantidad_retailers=("retailer", "nunique"),
        precio_minimo=("precio_comparacion", "min"),
        precio_maximo=("precio_comparacion", "max"),
        precio_promedio=("precio_comparacion", "mean"),
    ).reset_index()

    ofertas = limpio[limpio["precio_oferta"] > 0]
    if not ofertas.empty:
        metricas_oferta = ofertas.groupby("ean_norm").agg(
            precio_oferta_minimo=("precio_oferta", "min"),
            precio_oferta_promedio=("precio_oferta", "mean"),
        ).reset_index()
    else:
        metricas_oferta = pd.DataFrame(
            columns=["ean_norm", "precio_oferta_minimo", "precio_oferta_promedio"]
        )

    match = match.merge(metricas, on="ean_norm", how="left")
    match = match.merge(metricas_oferta, on="ean_norm", how="left")

    match["brecha_vs_minimo_$"] = (
        match["precio_comparacion"] - match["precio_minimo"]
    ).round(2)
    match["brecha_vs_minimo_%"] = (
        (match["precio_comparacion"] / match["precio_minimo"] - 1) * 100
    ).round(2)
    match["brecha_vs_promedio_%"] = (
        (match["precio_comparacion"] / match["precio_promedio"] - 1) * 100
    ).round(2)

    match["_precio_rank"] = match["precio_comparacion"].where(
        match["precio_sospechoso"] == 0, np.inf
    )
    match["ranking_precio"] = match.groupby("ean_norm")["_precio_rank"].rank(
        method="dense", ascending=True
    ).astype(int)
    match = match.drop(columns=["_precio_rank"])

    def clasificar_posicion(row):
        if row["precio_sospechoso"] == 1:
            return "DATO SOSPECHOSO"
        brecha = row["brecha_vs_minimo_%"]
        if pd.isna(brecha):
            return "SIN DATO"
        if brecha <= 0:
            return "LIDER PRECIO"
        if brecha <= 5:
            return "COMPETITIVO"
        if brecha <= 15:
            return "INTERMEDIO"
        return "MAS CARO"

    match["posicion_competitiva"] = match.apply(clasificar_posicion, axis=1)

    base_nombre = match[match["precio_sospechoso"] == 0]
    if base_nombre.empty:
        base_nombre = match
    nombre_ref = (
        base_nombre.sort_values(["ean_norm", "precio_comparacion"])
        .groupby("ean_norm")["nombre_producto_original"].first()
        .reset_index()
        .rename(columns={"nombre_producto_original": "producto_referencia"})
    )
    match = match.merge(nombre_ref, on="ean_norm", how="left")

    match["precio_actual"] = match["precio_comparacion"]

    columnas = [
        "ean_norm", "producto_referencia", "retailer", "categoria",
        "nombre_producto_original", "marca",
        "precio_actual", "precio_comparacion", "precio_regular", "precio_oferta",
        "tipo_promocion", "cantidad_retailers",
        "precio_minimo", "precio_maximo", "precio_promedio",
        "precio_oferta_minimo", "precio_oferta_promedio",
        "brecha_vs_minimo_$", "brecha_vs_minimo_%", "brecha_vs_promedio_%",
        "ranking_precio", "posicion_competitiva", "precio_sospechoso", "url_producto",
    ]
    columnas = [c for c in columnas if c in match.columns]
    match = match[columnas].sort_values(["ean_norm", "ranking_precio", "retailer"])

    Path("outputs").mkdir(exist_ok=True)
    match.to_csv(OUTPUT, index=False, encoding="utf-8-sig")

    resumen = {
        "productos_utiles_con_ean": len(df),
        "eans_unicos_utiles": df["ean_norm"].nunique(),
        "eans_en_2_o_mas_retailers": match["ean_norm"].nunique(),
        "filas_matching_competitivo": len(match),
        "retailers_en_matching": match["retailer"].nunique(),
        "capturas_sospechosas": int(match["precio_sospechoso"].sum()),
    }
    pd.DataFrame([resumen]).to_csv(RESUMEN, index=False, encoding="utf-8-sig")

    print("Matching EAN generado:", OUTPUT)
    print(pd.DataFrame([resumen]).to_string(index=False))
    print("Capturas sospechosas:", int(match["precio_sospechoso"].sum()))


if __name__ == "__main__":
    main()
