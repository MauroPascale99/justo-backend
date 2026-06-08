import argparse
from pathlib import Path
import pandas as pd

def normalizar_ean(x):
    if pd.isna(x):
        return ""
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s

def precio_valido(x):
    try:
        n = float(str(x).replace(",", "."))
        return n if n > 0 else None
    except Exception:
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id-cliente", type=int, required=True)
    args = parser.parse_args()

    base_dir = Path(f"outputs/clientes/{args.id_cliente}")

    input_path = base_dir / "ultima_busqueda_mis_productos.csv"
    output_path = base_dir / "ultima_busqueda_mis_productos_agrupada.csv"
    detalle_path = base_dir / "ultima_busqueda_mis_productos_detalle_retailers.csv"

    if not input_path.exists():
        raise SystemExit(f"No existe {input_path}")

    df = pd.read_csv(input_path, low_memory=False)

    if df.empty:
        pd.DataFrame().to_csv(output_path, index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(detalle_path, index=False, encoding="utf-8-sig")
        print("Búsqueda vacía. Se generaron archivos vacíos.")
        return

    for col in [
        "ean", "retailer", "nombre_producto", "marca", "categoria",
        "precio_actual", "precio_regular", "precio_oferta",
        "disponibilidad", "url_producto", "url_imagen", "id_producto_fuente"
    ]:
        if col not in df.columns:
            df[col] = ""

    df["ean_norm"] = df["ean"].apply(normalizar_ean)
    df["precio_actual_num"] = df["precio_actual"].apply(precio_valido)
    df["precio_regular_num"] = df["precio_regular"].apply(precio_valido)
    df["precio_oferta_num"] = df["precio_oferta"].apply(precio_valido)

    # Si precio_regular viene vacío, usamos precio_actual como fallback.
    df["precio_regular_final"] = df["precio_regular_num"]
    df.loc[df["precio_regular_final"].isna(), "precio_regular_final"] = df["precio_actual_num"]

    df["clave_producto"] = df["ean_norm"]
    sin_ean = df["clave_producto"].eq("") | df["clave_producto"].isna()
    df.loc[sin_ean, "clave_producto"] = (
        df.loc[sin_ean, "marca"].astype(str).str.lower().str.strip()
        + " | "
        + df.loc[sin_ean, "nombre_producto"].astype(str).str.lower().str.strip()
    )

    detalle = df.copy()
    detalle.to_csv(detalle_path, index=False, encoding="utf-8-sig")

    registros = []

    for clave, g in df.groupby("clave_producto", dropna=False):
        g = g.copy()

        nombres = (
            g["nombre_producto"]
            .dropna()
            .astype(str)
            .drop_duplicates()
            .sort_values(key=lambda s: s.str.len())
            .tolist()
        )
        nombre_principal = nombres[0] if nombres else ""

        marcas = g["marca"].dropna().astype(str).drop_duplicates().tolist()
        marca_principal = marcas[0] if marcas else ""

        categorias = g["categoria"].dropna().astype(str).drop_duplicates().tolist()
        categoria_principal = categorias[0] if categorias else ""

        eans = g["ean_norm"].dropna().astype(str)
        eans = [e for e in eans.drop_duplicates().tolist() if e]
        ean_principal = eans[0] if eans else ""

        retailers = sorted(g["retailer"].dropna().astype(str).str.lower().drop_duplicates().tolist())

        precios_regulares = g.dropna(subset=["precio_regular_final"]).copy()

        precio_regular_min = precios_regulares["precio_regular_final"].min() if not precios_regulares.empty else None
        precio_regular_max = precios_regulares["precio_regular_final"].max() if not precios_regulares.empty else None
        precio_regular_promedio = precios_regulares["precio_regular_final"].mean() if not precios_regulares.empty else None

        retailer_regular_min = ""
        retailer_regular_max = ""

        if precio_regular_min is not None:
            row_min = precios_regulares.sort_values("precio_regular_final", ascending=True).iloc[0]
            retailer_regular_min = row_min["retailer"]

        if precio_regular_max is not None:
            row_max = precios_regulares.sort_values("precio_regular_final", ascending=False).iloc[0]
            retailer_regular_max = row_max["retailer"]

        disponibles = g[
            g["disponibilidad"].astype(str).str.lower().isin(["disponible", "1", "true", "si", "sí"])
        ]

        id_fuentes = g["id_producto_fuente"].dropna().astype(str).drop_duplicates().tolist()

        columnas_retailer = {}

        for retailer, gr in g.groupby(g["retailer"].astype(str).str.lower()):
            gr = gr.copy()

            gr_regular = gr.dropna(subset=["precio_regular_final"])
            gr_actual = gr.dropna(subset=["precio_actual_num"])
            gr_oferta = gr.dropna(subset=["precio_oferta_num"])

            precio_regular = gr_regular.sort_values("precio_regular_final", ascending=True).iloc[0]["precio_regular_final"] if not gr_regular.empty else None
            precio_actual = gr_actual.sort_values("precio_actual_num", ascending=True).iloc[0]["precio_actual_num"] if not gr_actual.empty else None
            precio_oferta = gr_oferta.sort_values("precio_oferta_num", ascending=True).iloc[0]["precio_oferta_num"] if not gr_oferta.empty else None

            disp = ", ".join(gr["disponibilidad"].dropna().astype(str).drop_duplicates().tolist())
            ids = ", ".join(gr["id_producto_fuente"].dropna().astype(str).drop_duplicates().tolist())

            columnas_retailer[f"precio_regular_{retailer}"] = precio_regular
            columnas_retailer[f"precio_actual_{retailer}"] = precio_actual
            columnas_retailer[f"precio_oferta_{retailer}"] = precio_oferta
            columnas_retailer[f"disponibilidad_{retailer}"] = disp
            columnas_retailer[f"ids_fuente_{retailer}"] = ids

        registros.append({
            "clave_producto": clave,
            "ean": ean_principal,
            "nombre_producto": nombre_principal,
            "marca": marca_principal,
            "categoria_principal": categoria_principal,
            "retailers_detectados": ", ".join(retailers),
            "cantidad_retailers": len(retailers),
            "cantidad_registros_detalle": len(g),
            "cantidad_disponibles": len(disponibles),

            # Métricas principales, siempre regulares.
            "precio_regular_min": precio_regular_min,
            "retailer_precio_regular_min": retailer_regular_min,
            "precio_regular_max": precio_regular_max,
            "retailer_precio_regular_max": retailer_regular_max,
            "precio_regular_promedio": precio_regular_promedio,

            # Compatibilidad con dashboards anteriores.
            "precio_min": precio_regular_min,
            "retailer_precio_min": retailer_regular_min,
            "precio_max": precio_regular_max,
            "retailer_precio_max": retailer_regular_max,
            "precio_promedio": precio_regular_promedio,

            "ids_producto_fuente": ", ".join(id_fuentes),
            **columnas_retailer,
        })

    out = pd.DataFrame(registros)

    if not out.empty:
        out = out.sort_values(
            by=["cantidad_disponibles", "cantidad_retailers", "nombre_producto"],
            ascending=[False, False, True]
        )

    out.to_csv(output_path, index=False, encoding="utf-8-sig")

    print("AGRUPACIÓN MIS PRODUCTOS — PRECIO REGULAR")
    print("=" * 100)
    print(f"Entrada detalle: {input_path} ({len(df)} filas)")
    print(f"Productos únicos agrupados: {len(out)}")
    print(f"Generado agrupado: {output_path}")
    print(f"Generado detalle: {detalle_path}")
    print("=" * 100)

    if not out.empty:
        cols = [
            "ean", "nombre_producto", "retailers_detectados",
            "precio_regular_min", "retailer_precio_regular_min",
            "precio_regular_max", "retailer_precio_regular_max"
        ]
        print(out[cols].head(20).to_string(index=False))

if __name__ == "__main__":
    main()
