import argparse
import json
import re
import sqlite3
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

DB_PATH = "db/justo_pricing.db"


def limpiar_txt(x):
    if x is None:
        return ""
    return str(x).lower().strip()


def normalizar_nombre(x):
    x = limpiar_txt(x)
    x = re.sub(r"[^a-záéíóúñ0-9 ]+", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def similitud(a, b):
    a = normalizar_nombre(a)
    b = normalizar_nombre(b)
    if not a or not b:
        return 0
    return SequenceMatcher(None, a, b).ratio()


def json_response(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Sugerir competidores para un producto propio del cliente."
    )

    parser.add_argument("--id-cliente", type=int, required=True)
    parser.add_argument("--id-producto-cliente", type=int, required=True)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--modo-json", action="store_true")

    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ==========================================================
    # Validar cliente
    # ==========================================================
    cur.execute("""
        SELECT id_cliente, nombre_cliente
        FROM clientes
        WHERE id_cliente = ?
          AND estado = 'activo'
    """, (args.id_cliente,))

    cliente = cur.fetchone()

    if not cliente:
        conn.close()
        payload = {
            "ok": False,
            "error": f"No existe cliente activo con id_cliente={args.id_cliente}",
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    # ==========================================================
    # Producto propio
    # ==========================================================
    cur.execute("""
        SELECT
            id_producto_cliente,
            id_cliente,
            id_producto_fuente,
            ean,
            nombre_producto,
            marca,
            categoria,
            retailer
        FROM productos_cliente
        WHERE id_cliente = ?
          AND id_producto_cliente = ?
          AND activo = 1
    """, (
        args.id_cliente,
        args.id_producto_cliente,
    ))

    prod = cur.fetchone()

    if not prod:
        conn.close()
        payload = {
            "ok": False,
            "error": "No existe producto propio activo para ese cliente.",
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    (
        id_producto_cliente,
        id_cliente,
        id_producto_fuente,
        ean_propio,
        nombre_propio,
        marca_propia,
        categoria_propia,
        retailer_origen,
    ) = prod

    # ==========================================================
    # Validar plan
    # ==========================================================
    cur.execute("""
        SELECT
            p.codigo_plan,
            p.nombre_plan,
            p.max_competidores_por_producto,
            p.permite_oportunidades_vs_competidor
        FROM suscripciones_cliente sc
        JOIN planes p
          ON p.id_plan = sc.id_plan
        WHERE sc.id_cliente = ?
          AND sc.estado = 'activa'
        ORDER BY sc.id_suscripcion DESC
        LIMIT 1
    """, (args.id_cliente,))

    plan = cur.fetchone()

    if not plan:
        conn.close()
        payload = {
            "ok": False,
            "error": "El cliente no tiene suscripción activa.",
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    codigo_plan, nombre_plan, max_competidores, permite_oportunidades = plan

    # ==========================================================
    # Competidores ya configurados
    # ==========================================================
    cur.execute("""
        SELECT COUNT(*)
        FROM mapa_competitivo_cliente
        WHERE id_cliente = ?
          AND id_producto_cliente = ?
          AND activo = 1
    """, (
        args.id_cliente,
        args.id_producto_cliente,
    ))

    competidores_actuales = cur.fetchone()[0]
    cupo_competidores = max_competidores - competidores_actuales

    # ==========================================================
    # Retailers habilitados
    # ==========================================================
    cur.execute("""
        SELECT retailer
        FROM retailers_cliente
        WHERE id_cliente = ?
          AND activo = 1
    """, (args.id_cliente,))

    retailers_habilitados = [
        str(r[0]).lower().strip()
        for r in cur.fetchall()
    ]

    # ==========================================================
    # Categorías habilitadas
    # ==========================================================
    cur.execute("""
        SELECT DISTINCT categoria
        FROM categorias_cliente
        WHERE id_cliente = ?
          AND activa = 1
    """, (args.id_cliente,))

    categorias_habilitadas = [
        str(r[0]).lower().strip()
        for r in cur.fetchall()
    ]

    conn.close()

    if cupo_competidores <= 0:
        payload = {
            "ok": True,
            "cliente": cliente[1],
            "producto_propio": {
                "id_producto_cliente": id_producto_cliente,
                "ean": ean_propio,
                "nombre": nombre_propio,
                "marca": marca_propia,
                "categoria": categoria_propia,
            },
            "plan": {
                "codigo_plan": codigo_plan,
                "nombre_plan": nombre_plan,
                "max_competidores_por_producto": max_competidores,
                "competidores_actuales": competidores_actuales,
                "cupo_disponible": 0,
            },
            "candidatos": [],
            "mensaje": "El producto ya alcanzó el máximo de competidores permitidos por el plan.",
        }
        json_response(payload) if args.modo_json else print(payload["mensaje"])
        return

    # ==========================================================
    # Cargar catálogo actual
    # ==========================================================
    conn = sqlite3.connect(DB_PATH)

    catalogo = pd.read_sql_query("""
        SELECT
            pf.id_producto_fuente,
            pf.retailer,
            pf.ean_detectado AS ean,
            pf.nombre_original AS nombre_producto,
            pf.marca_original AS marca,
            pf.categoria_original AS categoria,
            pf.url_producto,
            pf.url_imagen,
            c.fecha_captura,
            c.hora_captura,
            c.precio_actual,
            c.precio_regular,
            c.precio_oferta,
            c.tipo_promocion,
            c.disponibilidad
        FROM productos_fuente pf
        JOIN capturas_precio c
          ON c.id_producto_fuente = pf.id_producto_fuente
        WHERE c.id_captura IN (
            SELECT MAX(c2.id_captura)
            FROM capturas_precio c2
            GROUP BY c2.id_producto_fuente
        )
          AND c.precio_actual IS NOT NULL
          AND c.precio_actual > 0
    """, conn)

    conn.close()

    if catalogo.empty:
        payload = {
            "ok": False,
            "error": "No hay catálogo disponible con precios.",
        }
        json_response(payload) if args.modo_json else print(payload["error"])
        return

    # ==========================================================
    # Filtros SaaS
    # ==========================================================
    catalogo["retailer_norm"] = catalogo["retailer"].astype(str).str.lower().str.strip()
    catalogo["categoria_norm"] = catalogo["categoria"].astype(str).str.lower().str.strip()
    catalogo["ean_norm"] = catalogo["ean"].astype(str).str.strip()
    catalogo["marca_norm"] = catalogo["marca"].astype(str).str.lower().str.strip()

    catalogo = catalogo[
        catalogo["retailer_norm"].isin(retailers_habilitados)
    ].copy()

    def categoria_permitida(cat):
        cat_l = str(cat).lower().strip()
        return any(c in cat_l or cat_l in c for c in categorias_habilitadas)

    catalogo = catalogo[
        catalogo["categoria"].apply(categoria_permitida)
    ].copy()

    # Excluir mismo producto / mismo EAN
    ean_propio_norm = str(ean_propio or "").strip()
    if ean_propio_norm:
        catalogo = catalogo[catalogo["ean_norm"] != ean_propio_norm].copy()

    if id_producto_fuente:
        catalogo = catalogo[catalogo["id_producto_fuente"] != id_producto_fuente].copy()

    # En competidores directos queremos marcas distintas.
    marca_propia_norm = limpiar_txt(marca_propia)
    if marca_propia_norm:
        catalogo["misma_marca"] = catalogo["marca_norm"] == marca_propia_norm
    else:
        catalogo["misma_marca"] = False

    # No eliminamos misma marca al 100% porque puede haber duplicados o marcas mal capturadas,
    # pero la penalizamos fuerte en el score.
    # ==========================================================
    # Scoring
    # ==========================================================
    nombre_base = nombre_propio
    categoria_base = categoria_propia

    catalogo["score_nombre"] = catalogo["nombre_producto"].apply(
        lambda x: similitud(nombre_base, x)
    )

    catalogo["score_categoria"] = catalogo["categoria"].apply(
        lambda x: 1 if categoria_permitida(x) else 0
    )

    catalogo["penalizacion_misma_marca"] = catalogo["misma_marca"].apply(
        lambda x: 0.35 if x else 0
    )

    catalogo["score_final"] = (
        catalogo["score_nombre"] * 0.75
        + catalogo["score_categoria"] * 0.25
        - catalogo["penalizacion_misma_marca"]
    )

    # Priorizamos candidatos razonables
    catalogo = catalogo.sort_values(
        by=["score_final", "score_nombre", "precio_actual"],
        ascending=[False, False, True]
    ).head(args.limit)

    candidatos = []

    for _, r in catalogo.iterrows():
        candidatos.append({
            "id_producto_fuente": int(r["id_producto_fuente"]),
            "retailer": str(r["retailer"]),
            "ean": str(r["ean"]),
            "nombre_producto": str(r["nombre_producto"]),
            "marca": str(r["marca"]),
            "categoria": str(r["categoria"]),
            "precio_actual": float(r["precio_actual"]),
            "tipo_promocion": str(r.get("tipo_promocion", "")),
            "disponibilidad": str(r.get("disponibilidad", "")),
            "score_final": round(float(r["score_final"]), 4),
            "score_nombre": round(float(r["score_nombre"]), 4),
            "misma_marca": bool(r["misma_marca"]),
            "url_producto": str(r.get("url_producto", "")),
        })

    payload = {
        "ok": True,
        "cliente": {
            "id_cliente": args.id_cliente,
            "nombre_cliente": cliente[1],
        },
        "producto_propio": {
            "id_producto_cliente": id_producto_cliente,
            "id_producto_fuente": id_producto_fuente,
            "ean": ean_propio,
            "nombre": nombre_propio,
            "marca": marca_propia,
            "categoria": categoria_propia,
            "retailer_origen": retailer_origen,
        },
        "plan": {
            "codigo_plan": codigo_plan,
            "nombre_plan": nombre_plan,
            "max_competidores_por_producto": max_competidores,
            "competidores_actuales": competidores_actuales,
            "cupo_disponible": cupo_competidores,
            "permite_oportunidades_vs_competidor": bool(permite_oportunidades),
        },
        "filtros_aplicados": {
            "retailers_habilitados": retailers_habilitados,
            "categorias_habilitadas": categorias_habilitadas,
        },
        "candidatos": candidatos,
    }

    # Guardar CSV para inspección/debug
    out = Path(f"outputs/clientes/{args.id_cliente}/sugerencias_competidores_producto_{id_producto_cliente}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)

    if candidatos:
        pd.DataFrame(candidatos).to_csv(out, index=False, encoding="utf-8-sig")

    if args.modo_json:
        json_response(payload)
    else:
        print("\nSUGERENCIAS DE COMPETIDORES")
        print("=" * 120)
        print(f"Cliente: {cliente[1]} | id_cliente={args.id_cliente}")
        print(f"Producto propio: {nombre_propio}")
        print(f"Marca propia: {marca_propia}")
        print(f"Categoría: {categoria_propia}")
        print(f"Plan: {nombre_plan} ({codigo_plan})")
        print(f"Competidores: {competidores_actuales} / {max_competidores}")
        print("=" * 120)

        if not candidatos:
            print("No se encontraron candidatos.")
        else:
            for c in candidatos:
                print(f"ID FUENTE: {c['id_producto_fuente']}")
                print(f"Retailer: {c['retailer']}")
                print(f"EAN: {c['ean']}")
                print(f"Producto: {c['nombre_producto']}")
                print(f"Marca: {c['marca']}")
                print(f"Categoría: {c['categoria']}")
                print(f"Precio actual: {c['precio_actual']}")
                print(f"Score final: {c['score_final']}")
                print(f"Misma marca: {c['misma_marca']}")
                print(f"URL: {c['url_producto']}")
                print("-" * 120)

        print(f"\nCSV generado: {out}")


if __name__ == "__main__":
    main()
