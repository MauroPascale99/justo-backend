import os
import sys
import shutil
import json
import psycopg2
import pandas as pd
import statistics
from datetime import datetime
from dotenv import load_dotenv

# Resolver directorios
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(BACKEND_DIR)

# Cargar variables de entorno. Probamos .env del root y .env.local del frontend
# (ahi suele vivir ANTHROPIC_API_KEY).
load_dotenv(dotenv_path=os.path.join(ROOT_DIR, ".env"))
for extra_env in (
    os.path.join(ROOT_DIR, ".env.local"),
    os.path.join(ROOT_DIR, "justo-frontend", ".env.local"),
    os.path.join(ROOT_DIR, "frontend", ".env.local"),
):
    if os.path.exists(extra_env):
        load_dotenv(dotenv_path=extra_env, override=False)

ID_CLIENTE = int(os.getenv("ID_CLIENTE", "1"))


# ---------------------------------------------------------------------------
# 1. CONSULTAS A SUPABASE
# ---------------------------------------------------------------------------

QUERY_PRECIOS = """
WITH latest AS (
    SELECT DISTINCT ON (id_producto_fuente)
        id_producto_fuente,
        COALESCE(precio_regular, precio_actual) AS precio_regular,
        precio_oferta,
        precio_actual,
        disponibilidad,
        fecha_captura,
        tipo_promocion
    FROM capturas_precio
    ORDER BY id_producto_fuente, disponibilidad DESC NULLS LAST, fecha_captura DESC, id_captura DESC
)
SELECT DISTINCT ON (pc.id_producto_cliente, pf.retailer)
    pc.nombre_producto              AS "Producto",
    pc.ean                          AS "EAN",
    pc.marca                        AS "Marca",
    pc.categoria_comercial          AS "Categoria",
    pf.retailer                     AS "Retailer",
    l.precio_regular                AS "Precio Regular ($)",
    l.precio_oferta                 AS "Precio Oferta ($)",
    CASE WHEN l.disponibilidad = true THEN 'En Gondola'
         WHEN l.disponibilidad = false THEN 'Sin Stock'
         ELSE 'Sin Dato' END        AS "Disponibilidad",
    l.tipo_promocion                AS "Promocion",
    l.fecha_captura                 AS "Ultima Captura",
    pf.url_producto                 AS "Evidencia Web"
FROM productos_cliente pc
JOIN productos_fuente pf  ON pf.ean_detectado = pc.ean
JOIN latest l             ON l.id_producto_fuente = pf.id_producto_fuente
WHERE pc.id_cliente = %s AND pc.activo = true
ORDER BY pc.id_producto_cliente, pf.retailer,
         l.disponibilidad DESC NULLS LAST, l.fecha_captura DESC
"""

QUERY_VERSUS = """
WITH latest AS (
    SELECT DISTINCT ON (id_producto_fuente)
        id_producto_fuente,
        COALESCE(precio_regular, precio_actual) AS precio_regular,
        precio_oferta,
        precio_actual,
        disponibilidad,
        fecha_captura
    FROM capturas_precio
    ORDER BY id_producto_fuente, disponibilidad DESC NULLS LAST, fecha_captura DESC, id_captura DESC
)
SELECT
    pc.nombre_producto              AS "Tu Producto",
    pc.ean                          AS "Tu EAN",
    tu.precio_regular               AS "Tu Precio Regular ($)",
    tu.precio_oferta                AS "Tu Precio Oferta ($)",
    m.nombre_competidor             AS "Producto Competidor",
    m.ean_competidor                AS "EAN Competidor",
    m.retailer_competidor           AS "Retailer",
    co.precio_regular               AS "Precio Competidor Regular ($)",
    co.precio_oferta                AS "Precio Competidor Oferta ($)",
    CASE WHEN co.disponibilidad = true THEN 'En Gondola'
         WHEN co.disponibilidad = false THEN 'Sin Stock'
         ELSE 'Sin Dato' END        AS "Disponibilidad Competidor",
    co.fecha_captura                AS "Ultima Captura",
    co_pf.url_producto              AS "Evidencia Web"
FROM mapa_competitivo_cliente m
JOIN productos_cliente pc ON pc.id_producto_cliente = m.id_producto_cliente
LEFT JOIN LATERAL (
    SELECT l.precio_regular, l.precio_oferta, l.disponibilidad, l.fecha_captura
    FROM productos_fuente pf
    JOIN latest l ON l.id_producto_fuente = pf.id_producto_fuente
    WHERE pf.ean_detectado = pc.ean AND pf.retailer = m.retailer_competidor
    ORDER BY l.disponibilidad DESC NULLS LAST, l.fecha_captura DESC
    LIMIT 1
) tu ON true
LEFT JOIN LATERAL (
    SELECT pf.id_producto_fuente, pf.url_producto,
           l.precio_regular, l.precio_oferta, l.disponibilidad, l.fecha_captura
    FROM productos_fuente pf
    JOIN latest l ON l.id_producto_fuente = pf.id_producto_fuente
    WHERE pf.ean_detectado = m.ean_competidor AND pf.retailer = m.retailer_competidor
    ORDER BY l.disponibilidad DESC NULLS LAST, l.fecha_captura DESC
    LIMIT 1
) co ON true
LEFT JOIN productos_fuente co_pf ON co_pf.id_producto_fuente = co.id_producto_fuente
WHERE m.id_cliente = %s AND m.activo = true AND pc.activo = true
ORDER BY pc.nombre_producto, m.retailer_competidor
"""


# Mismo criterio que la app (/api/price-index): un mismo EAN deberia tener
# precios parecidos entre cadenas. Si una cadena supera K veces la mediana de las
# OTRAS, se considera error de scrapeo (pack/caja, seller inflado) y se anula.
# Universal: aplica a cualquier producto/cliente.
OUTLIER_K = 6

def _idx_outliers(grupo_precios):
    """Devuelve el set de indices cuyos precios son outliers inflados (leave-one-out)."""
    vals = [(i, float(v)) for i, v in grupo_precios.items() if pd.notna(v) and float(v) > 0]
    out = set()
    if len(vals) < 2:
        return out
    for i, v in vals:
        otros = [vv for j, vv in vals if j != i]
        med = statistics.median(otros)
        if med > 0 and v > med * OUTLIER_K:
            out.add(i)
    return out

def _anular_outliers(df, key_col, precio_col, oferta_col=None, disp_col=None, disp_val="Sin Dato"):
    if df.empty or key_col not in df.columns or precio_col not in df.columns:
        return df
    for _, grp in df.groupby(key_col):
        for idx in _idx_outliers(grp[precio_col]):
            df.loc[idx, precio_col] = pd.NA
            if oferta_col and oferta_col in df.columns:
                df.loc[idx, oferta_col] = pd.NA
            if disp_col and disp_col in df.columns:
                df.loc[idx, disp_col] = disp_val
    return df

def cargar_datos(conn):
    df_precios = pd.read_sql_query(QUERY_PRECIOS, conn, params=(ID_CLIENTE,))
    df_versus = pd.read_sql_query(QUERY_VERSUS, conn, params=(ID_CLIENTE,))
    for df in (df_precios, df_versus):
        if "Ultima Captura" in df.columns and not df.empty:
            df["Ultima Captura"] = pd.to_datetime(
                df["Ultima Captura"], errors="coerce"
            ).dt.tz_localize(None)

    # Filtro de outliers (consistente con la app)
    df_precios = _anular_outliers(
        df_precios, "EAN", "Precio Regular ($)", "Precio Oferta ($)",
        "Disponibilidad", "Sin Dato")
    df_versus = _anular_outliers(
        df_versus, "EAN Competidor", "Precio Competidor Regular ($)",
        "Precio Competidor Oferta ($)", "Disponibilidad Competidor", "Sin Dato")
    df_versus = _anular_outliers(
        df_versus, "Tu EAN", "Tu Precio Regular ($)", "Tu Precio Oferta ($)")
    return df_precios, df_versus


# ---------------------------------------------------------------------------
# 2. OBSERVACIONES (IA si hay API key, si no resumen calculado con datos reales)
# ---------------------------------------------------------------------------

def calcular_metricas(df_versus):
    """Metricas reales para alimentar el resumen (IA o reglas)."""
    m = {"total": len(df_versus), "mas_barato": 0, "mas_caro": 0,
         "empate": 0, "sin_dato": 0, "detalle": []}
    for _, r in df_versus.iterrows():
        tu = r["Tu Precio Oferta ($)"] if pd.notna(r["Tu Precio Oferta ($)"]) else r["Tu Precio Regular ($)"]
        co = r["Precio Competidor Oferta ($)"] if pd.notna(r["Precio Competidor Oferta ($)"]) else r["Precio Competidor Regular ($)"]
        # Competidor sin stock: precio no comprable (suele quedar viejo). No cuenta.
        if pd.isna(tu) or pd.isna(co) or not co or r.get("Disponibilidad Competidor") == "Sin Stock":
            m["sin_dato"] += 1
            continue
        brecha_pct = (tu - co) / co
        if abs(brecha_pct) < 0.01:
            m["empate"] += 1
        elif tu < co:
            m["mas_barato"] += 1
        else:
            m["mas_caro"] += 1
        m["detalle"].append({
            "producto": r["Tu Producto"],
            "competidor": r["Producto Competidor"],
            "retailer": r["Retailer"],
            "tu_precio": round(float(tu), 2),
            "precio_comp": round(float(co), 2),
            "brecha_pct": round(float(brecha_pct) * 100, 1),
        })
    return m


def resumen_por_reglas(m, df_precios):
    hoy = datetime.now().strftime("%d/%m/%Y")
    lineas = []
    lineas.append(f"Reporte de vigilancia de precios - {hoy}")
    lineas.append("")
    lineas.append(
        f"Se monitorearon {len(df_precios)} apariciones de tus productos en "
        f"{df_precios['Retailer'].nunique() if not df_precios.empty else 0} retailers, "
        f"y {m['total']} comparaciones directas contra competidores asignados."
    )
    lineas.append("")
    if m["total"]:
        lineas.append(
            f"Posicionamiento: estas mas barato que el competidor en {m['mas_barato']} casos, "
            f"mas caro en {m['mas_caro']}, en paridad en {m['empate']} "
            f"y sin dato comparable en {m['sin_dato']}."
        )
    caros = sorted([d for d in m["detalle"] if d["brecha_pct"] > 0],
                   key=lambda x: x["brecha_pct"], reverse=True)[:5]
    if caros:
        lineas.append("")
        lineas.append("Donde estas mas caro (revisar precio o promo):")
        for d in caros:
            lineas.append(
                f"  - {d['producto']} en {d['retailer']}: ${d['tu_precio']:,.0f} "
                f"vs {d['competidor']} ${d['precio_comp']:,.0f} (+{d['brecha_pct']:.1f}%)"
            )
    baratos = sorted([d for d in m["detalle"] if d["brecha_pct"] < 0],
                     key=lambda x: x["brecha_pct"])[:5]
    if baratos:
        lineas.append("")
        lineas.append("Donde lideras en precio (oportunidad defensiva / margen):")
        for d in baratos:
            lineas.append(
                f"  - {d['producto']} en {d['retailer']}: ${d['tu_precio']:,.0f} "
                f"vs {d['competidor']} ${d['precio_comp']:,.0f} ({d['brecha_pct']:.1f}%)"
            )
    return "\n".join(lineas)


def resumen_por_ia(m, df_precios):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        return None
    contexto = {
        "fecha": datetime.now().strftime("%d/%m/%Y"),
        "apariciones_precios": int(len(df_precios)),
        "retailers": int(df_precios["Retailer"].nunique()) if not df_precios.empty else 0,
        "comparaciones": m,
    }
    prompt = (
        "Sos un analista de pricing para una marca de consumo masivo en Argentina. "
        "Con estos datos reales de comparacion vs competidores, escribi un resumen "
        "ejecutivo claro y accionable en espanol (maximo 250 palabras, sin markdown), "
        "destacando donde la marca esta cara, donde lidera, y 2-3 acciones concretas.\n\n"
        f"DATOS:\n{json.dumps(contexto, ensure_ascii=False, indent=2)}"
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"IA no disponible ({e}); uso resumen calculado.")
        return None


def generar_observaciones(df_versus, df_precios):
    m = calcular_metricas(df_versus)
    texto = resumen_por_ia(m, df_precios)
    fuente = "IA (Claude)"
    if not texto:
        texto = resumen_por_reglas(m, df_precios)
        fuente = "Resumen calculado"
    return texto, fuente


# ---------------------------------------------------------------------------
# 3. ESCRITURA DEL EXCEL
# ---------------------------------------------------------------------------

def _colletter(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def escribir_excel(df_precios, df_versus, observaciones, fuente_obs, excel_path):
    with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
        workbook = writer.book

        header_format = workbook.add_format({
            "bold": True, "font_color": "#FFFFFF", "bg_color": "#1F1F24",
            "border": 1, "align": "center", "valign": "vcenter", "font_name": "Arial",
        })
        money_format = workbook.add_format(
            {"num_format": "$#,##0.00;($#,##0.00);-", "align": "right", "font_name": "Arial"})
        percent_format = workbook.add_format(
            {"num_format": "0.0%;(0.0%);-", "align": "right", "font_name": "Arial"})
        wrap_format = workbook.add_format(
            {"font_name": "Arial", "valign": "top", "text_wrap": True})
        title_format = workbook.add_format(
            {"bold": True, "font_size": 14, "font_name": "Arial"})
        sub_format = workbook.add_format(
            {"italic": True, "font_color": "#666666", "font_name": "Arial"})

        # ---- Solapa 1: PRECIOS ----------------------------------------
        df_precios.to_excel(writer, sheet_name="Precios", index=False, startrow=0)
        ws_p = writer.sheets["Precios"]
        for col_num, value in enumerate(df_precios.columns):
            ws_p.write(0, col_num, value, header_format)
        col_idx = {c: i for i, c in enumerate(df_precios.columns)}
        for money_col in ("Precio Regular ($)", "Precio Oferta ($)"):
            if money_col in col_idx:
                c = col_idx[money_col]
                for row_num in range(len(df_precios)):
                    val = df_precios.iloc[row_num][money_col]
                    if pd.notna(val):
                        ws_p.write_number(row_num + 1, c, float(val), money_format)
                    else:
                        ws_p.write_blank(row_num + 1, c, None, money_format)
        ws_p.set_default_row(20)
        ws_p.set_row(0, 28)
        anchos_precios = {
            "Producto": 42, "EAN": 16, "Marca": 16, "Categoria": 18, "Retailer": 13,
            "Precio Regular ($)": 17, "Precio Oferta ($)": 17, "Disponibilidad": 14,
            "Promocion": 16, "Ultima Captura": 18, "Evidencia Web": 30,
        }
        for name, w in anchos_precios.items():
            if name in col_idx:
                ws_p.set_column(col_idx[name], col_idx[name], w)
        ws_p.freeze_panes(1, 0)
        if not df_precios.empty:
            ws_p.autofilter(0, 0, len(df_precios), len(df_precios.columns) - 1)

        # ---- Solapa 2: VERSUS COMPETENCIA -----------------------------
        extra_cols = [
            "Brecha Reg vs Reg (%)",
            "Brecha Reg vs Oferta Comp (%)",
            "Brecha Oferta vs Reg Comp (%)",
            "Brecha Oferta vs Oferta (%)",
        ]
        df_versus.to_excel(writer, sheet_name="Versus competencia", index=False, startrow=0)
        ws_v = writer.sheets["Versus competencia"]
        for col_num, value in enumerate(df_versus.columns):
            ws_v.write(0, col_num, value, header_format)
        vidx = {c: i for i, c in enumerate(df_versus.columns)}

        c_tu_reg = _colletter(vidx["Tu Precio Regular ($)"])
        c_tu_of = _colletter(vidx["Tu Precio Oferta ($)"])
        c_co_reg = _colletter(vidx["Precio Competidor Regular ($)"])
        c_co_of = _colletter(vidx["Precio Competidor Oferta ($)"])

        base = len(df_versus.columns)
        for j, name in enumerate(extra_cols):
            ws_v.write(0, base + j, name, header_format)

        for money_col in ("Tu Precio Regular ($)", "Tu Precio Oferta ($)",
                          "Precio Competidor Regular ($)", "Precio Competidor Oferta ($)"):
            c = vidx[money_col]
            for row_num in range(len(df_versus)):
                val = df_versus.iloc[row_num][money_col]
                if pd.notna(val):
                    ws_v.write_number(row_num + 1, c, float(val), money_format)
                else:
                    ws_v.write_blank(row_num + 1, c, None, money_format)

        # Brecha (positivo = tu producto mas caro). "" si falta cualquier operando.
        def brecha(tu, co, r):
            return (f'=IFERROR(IF(AND(ISNUMBER({tu}{r}),ISNUMBER({co}{r})),'
                    f'({tu}{r}-{co}{r})/{co}{r},""),"")')

        for row_num in range(len(df_versus)):
            r = row_num + 2
            ws_v.write_formula(row_num + 1, base + 0, brecha(c_tu_reg, c_co_reg, r), percent_format)
            ws_v.write_formula(row_num + 1, base + 1, brecha(c_tu_reg, c_co_of, r), percent_format)
            ws_v.write_formula(row_num + 1, base + 2, brecha(c_tu_of, c_co_reg, r), percent_format)
            ws_v.write_formula(row_num + 1, base + 3, brecha(c_tu_of, c_co_of, r), percent_format)

        ws_v.set_default_row(20)
        ws_v.set_row(0, 28)
        anchos_versus = {
            "Tu Producto": 40, "Tu EAN": 16, "Tu Precio Regular ($)": 17,
            "Tu Precio Oferta ($)": 17, "Producto Competidor": 40, "EAN Competidor": 16,
            "Retailer": 13, "Precio Competidor Regular ($)": 20,
            "Precio Competidor Oferta ($)": 20, "Disponibilidad Competidor": 18,
            "Ultima Captura": 18, "Evidencia Web": 30,
        }
        for name, w in anchos_versus.items():
            if name in vidx:
                ws_v.set_column(vidx[name], vidx[name], w)
        for j in range(len(extra_cols)):
            ws_v.set_column(base + j, base + j, 22)
        ws_v.freeze_panes(1, 0)
        if not df_versus.empty:
            ws_v.autofilter(0, 0, len(df_versus), base + len(extra_cols) - 1)

        # ---- Solapa 3: OBSERVACIONES ----------------------------------
        ws_o = workbook.add_worksheet("Observaciones")
        ws_o.set_column(0, 0, 110)
        ws_o.write(0, 0, "Observaciones del dia", title_format)
        ws_o.write(1, 0, f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}  -  Fuente: {fuente_obs}", sub_format)
        row = 3
        for linea in observaciones.split("\n"):
            ws_o.write(row, 0, linea, wrap_format)
            row += 1


# ---------------------------------------------------------------------------
# 4. MAIN
# ---------------------------------------------------------------------------

def main():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("ERROR: falta DATABASE_URL en el entorno.", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    try:
        df_precios, df_versus = cargar_datos(conn)
    finally:
        conn.close()

    if df_precios.empty and df_versus.empty:
        print("ADVERTENCIA: no se encontraron datos para el cliente "
              f"{ID_CLIENTE}. No se genera reporte vacio.", file=sys.stderr)
        sys.exit(2)

    observaciones, fuente_obs = generar_observaciones(df_versus, df_precios)

    out_dir = os.environ.get(
        "REPORTES_DIR",
        os.path.join(ROOT_DIR, "outputs"),
    )
    hist_dir = os.path.join(out_dir, "historico")
    os.makedirs(hist_dir, exist_ok=True)

    # Nombre unico con la fecha del dia al final -> nunca pisa un Excel abierto
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    file_name = f"Reporte_Vigilancia_Precios_{stamp}.xlsx"
    excel_path = os.path.join(hist_dir, file_name)
    escribir_excel(df_precios, df_versus, observaciones, fuente_obs, excel_path)
    print(f"Excel generado exitosamente en: {excel_path}")
    print(f"  Precios: {len(df_precios)} filas | Versus: {len(df_versus)} filas | Obs: {fuente_obs}")
    print(f"ARCHIVO_GENERADO:{file_name}")


if __name__ == "__main__":
    main()
