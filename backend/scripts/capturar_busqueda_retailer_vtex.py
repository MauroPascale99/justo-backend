import argparse
import hashlib
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

DB_PATH = "db/justo_pricing.db"

RETAILERS = {
    "carrefour": {
        "base_url": "https://www.carrefour.com.ar",
        "nombre": "Carrefour",
    },
    "jumbo": {
        "base_url": "https://www.jumbo.com.ar",
        "nombre": "Jumbo",
    },
    "disco": {
        "base_url": "https://www.disco.com.ar",
        "nombre": "Disco",
    },
    "vea": {
        "base_url": "https://www.vea.com.ar",
        "nombre": "Vea",
    },
}


def normalizar_texto(x):
    if x is None:
        return ""
    return str(x).strip()


def extraer_precio_y_stock(item, retailer):
    sellers = item.get("sellers") or []

    if not sellers:
        return None, None, None, None, "sin_seller"

    seller = sellers[0]
    offer = seller.get("commertialOffer") or {}

    precio_actual = offer.get("Price")
    
    if retailer in ["disco", "jumbo", "vea"]:
        precio_regular = offer.get("PriceWithoutDiscount") or precio_actual
        precio_oferta = None
        try:
            if precio_actual and precio_regular and float(precio_actual) < float(precio_regular):
                precio_oferta = precio_actual
        except Exception:
            pass
    else:
        precio_regular = offer.get("ListPrice")
        precio_oferta = None
        try:
            if precio_actual and precio_regular and float(precio_actual) < float(precio_regular):
                precio_oferta = precio_actual
        except Exception:
            pass

    disponible = offer.get("IsAvailable")
    stock = offer.get("AvailableQuantity")

    if disponible is True:
        disponibilidad = "disponible"
    elif disponible is False:
        disponibilidad = "sin_stock"
    else:
        disponibilidad = "desconocida"

    if stock == 0:
        disponibilidad = "sin_stock"

    return precio_actual, precio_regular, precio_oferta, stock, disponibilidad


def extraer_imagen(item):
    images = item.get("images") or []
    if not images:
        return ""
    return images[0].get("imageUrl") or ""


def producto_desde_vtex(p, retailer):
    items = p.get("items") or []
    item = items[0] if items else {}

    precio_actual, precio_regular, precio_oferta, stock, disponibilidad = extraer_precio_y_stock(item, retailer)

    categorias = p.get("categories") or []
    categoria_original = ""
    if categorias:
        categoria_original = str(categorias[0]).strip("/")

    if not categoria_original:
        categoria_original = normalizar_texto(p.get("categoryId"))

    ean = normalizar_texto(item.get("ean"))

    return {
        "retailer": retailer,
        "id_externo": normalizar_texto(p.get("productId")),
        "nombre_original": normalizar_texto(p.get("productName")),
        "marca_original": normalizar_texto(p.get("brand")),
        "categoria_original": categoria_original,
        "ean_detectado": ean,
        "url_producto": normalizar_texto(p.get("link")),
        "url_imagen": extraer_imagen(item),
        "precio_actual": precio_actual,
        "precio_regular": precio_regular,
        "precio_oferta": precio_oferta,
        "tipo_promocion": "",
        "disponibilidad": disponibilidad,
        "stock": stock,
    }


def buscar_vtex(base_url, query, max_productos=100, page_size=50, pausa=0.5):
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
    }

    productos = []
    vistos = set()

    start = 0

    while len(productos) < max_productos:
        end = start + page_size - 1

        url = (
            f"{base_url}/api/catalog_system/pub/products/search/{query}"
            f"?_from={start}&_to={end}&O=OrderByTopSaleDESC"
        )

        print(f"Consultando: {url}")

        r = requests.get(url, headers=headers, timeout=30)

        # VTEX suele devolver 206 Partial Content cuando la respuesta es válida.
        if r.status_code not in (200, 206):
            print(f"Status no válido: {r.status_code}")
            print(r.text[:500])
            break

        data = r.json()

        if not data:
            print("Sin más datos.")
            break

        nuevos = 0

        for p in data:
            pid = str(p.get("productId") or "")
            if not pid or pid in vistos:
                continue

            vistos.add(pid)
            productos.append(p)
            nuevos += 1

            if len(productos) >= max_productos:
                break

        print(f"+{nuevos} nuevos | acumulado: {len(productos)}")

        if nuevos == 0 or len(data) < page_size:
            break

        start += page_size
        time.sleep(pausa)

    return productos


def asegurar_columnas(conn):
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS productos_fuente (
            id_producto_fuente INTEGER PRIMARY KEY AUTOINCREMENT,
            retailer TEXT NOT NULL,
            id_externo TEXT,
            nombre_original TEXT,
            marca_original TEXT,
            categoria_original TEXT,
            ean_detectado TEXT,
            url_producto TEXT,
            url_imagen TEXT,
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP,
            actualizado_en TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS capturas_precio (
            id_captura INTEGER PRIMARY KEY AUTOINCREMENT,
            id_producto_fuente INTEGER NOT NULL,
            fecha_captura TEXT,
            hora_captura TEXT,
            precio_actual REAL,
            precio_regular REAL,
            precio_oferta REAL,
            tipo_promocion TEXT,
            disponibilidad TEXT,
            stock REAL,
            creado_en TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()


def columnas_tabla(cur, tabla):
    cur.execute(f"PRAGMA table_info({tabla})")
    return [r[1] for r in cur.fetchall()]


def obtener_id_fuente_para_retailer(cur, retailer):
    """
    productos_fuente tiene id_fuente NOT NULL.
    Para captura dirigida usamos el id_fuente ya existente del mismo retailer.
    """
    cols = columnas_tabla(cur, "productos_fuente")

    if "id_fuente" not in cols:
        return None

    cur.execute("""
        SELECT id_fuente
        FROM productos_fuente
        WHERE lower(retailer) = lower(?)
          AND id_fuente IS NOT NULL
        LIMIT 1
    """, (retailer,))

    row = cur.fetchone()

    if row:
        return row[0]

    # Fallback por si existe tabla de fuentes con otro nombre común
    posibles_tablas = ["fuentes", "retailers_fuente", "fuentes_retailers"]

    for tabla in posibles_tablas:
        try:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,))
            if not cur.fetchone():
                continue

            cols_tabla = columnas_tabla(cur, tabla)

            id_col = None
            for c in ["id_fuente", "id_retailer", "id"]:
                if c in cols_tabla:
                    id_col = c
                    break

            nombre_col = None
            for c in ["retailer", "codigo", "nombre", "nombre_fuente"]:
                if c in cols_tabla:
                    nombre_col = c
                    break

            if id_col and nombre_col:
                cur.execute(f"""
                    SELECT {id_col}
                    FROM {tabla}
                    WHERE lower({nombre_col}) = lower(?)
                    LIMIT 1
                """, (retailer,))
                row = cur.fetchone()
                if row:
                    return row[0]
        except Exception:
            pass

    return None


def obtener_o_crear_producto(cur, prod):
    # Primero por retailer + id_externo
    cur.execute("""
        SELECT id_producto_fuente
        FROM productos_fuente
        WHERE retailer = ?
          AND id_externo = ?
        LIMIT 1
    """, (
        prod["retailer"],
        prod["id_externo"],
    ))

    row = cur.fetchone()

    if row:
        id_producto_fuente = row[0]

        cur.execute("""
            UPDATE productos_fuente
            SET
                nombre_original = ?,
                marca_original = ?,
                categoria_original = ?,
                ean_detectado = ?,
                url_producto = ?,
                url_imagen = ?,
                actualizado_en = CURRENT_TIMESTAMP
            WHERE id_producto_fuente = ?
        """, (
            prod["nombre_original"],
            prod["marca_original"],
            prod["categoria_original"],
            prod["ean_detectado"],
            prod["url_producto"],
            prod["url_imagen"],
            id_producto_fuente,
        ))

        return id_producto_fuente, "actualizado"

    # Fallback por retailer + EAN
    if prod["ean_detectado"]:
        cur.execute("""
            SELECT id_producto_fuente
            FROM productos_fuente
            WHERE retailer = ?
              AND ean_detectado = ?
            LIMIT 1
        """, (
            prod["retailer"],
            prod["ean_detectado"],
        ))

        row = cur.fetchone()

        if row:
            id_producto_fuente = row[0]

            cur.execute("""
                UPDATE productos_fuente
                SET
                    id_externo = ?,
                    nombre_original = ?,
                    marca_original = ?,
                    categoria_original = ?,
                    url_producto = ?,
                    url_imagen = ?,
                    actualizado_en = CURRENT_TIMESTAMP
                WHERE id_producto_fuente = ?
            """, (
                prod["id_externo"],
                prod["nombre_original"],
                prod["marca_original"],
                prod["categoria_original"],
                prod["url_producto"],
                prod["url_imagen"],
                id_producto_fuente,
            ))

            return id_producto_fuente, "actualizado_ean"

    cols_pf = columnas_tabla(cur, "productos_fuente")

    if "id_fuente" in cols_pf:
        id_fuente = obtener_id_fuente_para_retailer(cur, prod["retailer"])

        if id_fuente is None:
            raise SystemExit(
                f"No pude resolver id_fuente para retailer={prod['retailer']}. "
                "Primero verificá que ese retailer exista en productos_fuente o en la tabla de fuentes."
            )

        cur.execute("""
            INSERT INTO productos_fuente (
                id_fuente,
                retailer,
                id_externo,
                nombre_original,
                marca_original,
                categoria_original,
                ean_detectado,
                url_producto,
                url_imagen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            id_fuente,
            prod["retailer"],
            prod["id_externo"],
            prod["nombre_original"],
            prod["marca_original"],
            prod["categoria_original"],
            prod["ean_detectado"],
            prod["url_producto"],
            prod["url_imagen"],
        ))
    else:
        cur.execute("""
            INSERT INTO productos_fuente (
                retailer,
                id_externo,
                nombre_original,
                marca_original,
                categoria_original,
                ean_detectado,
                url_producto,
                url_imagen
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            prod["retailer"],
            prod["id_externo"],
            prod["nombre_original"],
            prod["marca_original"],
            prod["categoria_original"],
            prod["ean_detectado"],
            prod["url_producto"],
            prod["url_imagen"],
        ))

    return cur.lastrowid, "insertado"


def guardar_productos(productos_norm):
    conn = sqlite3.connect(DB_PATH)
    asegurar_columnas(conn)
    cur = conn.cursor()

    ahora = datetime.now()
    fecha = ahora.strftime("%Y-%m-%d")
    hora = ahora.strftime("%H:%M:%S")

    insertados = 0
    actualizados = 0
    capturas = 0

    cols_cp = columnas_tabla(cur, "capturas_precio")
    id_corrida = f"busqueda_{productos_norm[0]['retailer']}_{fecha.replace('-', '')}_{hora.replace(':', '')}" if productos_norm else ""

    for prod in productos_norm:
        id_producto_fuente, accion = obtener_o_crear_producto(cur, prod)

        if accion == "insertado":
            insertados += 1
        else:
            actualizados += 1

        # Insert dinámico para respetar el schema real de capturas_precio.
        # Algunas bases tienen columnas obligatorias como hash_captura / id_corrida.
        hash_base = "|".join([
            str(prod.get("retailer", "")),
            str(prod.get("id_externo", "")),
            str(prod.get("ean_detectado", "")),
            str(id_producto_fuente),
            str(fecha),
            str(hora),
            str(prod.get("precio_actual", "")),
            str(prod.get("disponibilidad", "")),
        ])

        hash_captura = hashlib.sha256(hash_base.encode("utf-8")).hexdigest()

        data_captura = {
            "id_producto_fuente": id_producto_fuente,
            "fecha_captura": fecha,
            "hora_captura": hora,
            "precio_actual": prod["precio_actual"],
            "precio_regular": prod["precio_regular"],
            "precio_oferta": prod["precio_oferta"],
            "tipo_promocion": prod["tipo_promocion"],
            "disponibilidad": prod["disponibilidad"],
            "stock": prod["stock"],
            "hash_captura": hash_captura,
            "id_corrida": id_corrida,
            "retailer": prod.get("retailer", ""),
            "fuente": prod.get("retailer", ""),
        }

        columnas_insert = [
            c for c in data_captura.keys()
            if c in cols_cp
        ]

        valores_insert = [data_captura[c] for c in columnas_insert]

        placeholders = ", ".join(["?"] * len(columnas_insert))
        columnas_sql = ", ".join(columnas_insert)

        try:
            cur.execute(
                f"INSERT INTO capturas_precio ({columnas_sql}) VALUES ({placeholders})",
                valores_insert
            )
            capturas += 1

        except sqlite3.IntegrityError as e:
            # Si el hash ya existe, no duplicamos la captura.
            if "hash_captura" in str(e) or "UNIQUE" in str(e).upper():
                pass
            else:
                raise

    conn.commit()
    conn.close()

    return insertados, actualizados, capturas


def main():
    parser = argparse.ArgumentParser(description="Captura dirigida por búsqueda VTEX para un retailer.")
    parser.add_argument("--retailer", required=True, choices=sorted(RETAILERS.keys()))
    parser.add_argument("--q", required=True, help="Texto de búsqueda. Ej: ecovita")
    parser.add_argument("--max", type=int, default=100)

    args = parser.parse_args()

    config = RETAILERS[args.retailer]

    print("\nCAPTURA DIRIGIDA VTEX")
    print("=" * 100)
    print(f"Retailer: {args.retailer}")
    print(f"Búsqueda: {args.q}")
    print(f"Máximo: {args.max}")
    print("=" * 100)

    productos_vtex = buscar_vtex(
        base_url=config["base_url"],
        query=args.q,
        max_productos=args.max,
    )

    productos_norm = [
        producto_desde_vtex(p, args.retailer)
        for p in productos_vtex
    ]

    print("\nPRODUCTOS NORMALIZADOS")
    print("=" * 100)

    for p in productos_norm[:20]:
        print(f"{p['retailer']} | {p['id_externo']} | {p['nombre_original']} | {p['marca_original']} | EAN {p['ean_detectado']} | ${p['precio_actual']} | {p['disponibilidad']}")

    if not productos_norm:
        print("No se encontraron productos.")
        return

    insertados, actualizados, capturas = guardar_productos(productos_norm)

    print("\nGUARDADO FINALIZADO")
    print("=" * 100)
    print(f"Productos encontrados: {len(productos_norm)}")
    print(f"Insertados nuevos: {insertados}")
    print(f"Actualizados existentes: {actualizados}")
    print(f"Capturas precio creadas: {capturas}")
    print("=" * 100)


if __name__ == "__main__":
    main()
