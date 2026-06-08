"""
JUSTO Pricing 360 — Captura completa de catálogo VTEX
=====================================================
Recorre todas las categorías de cada retailer VTEX y captura
el catálogo completo de productos con precios.

Uso:
    # Todos los retailers
    python capturar_catalogo_vtex_completo.py

    # Un retailer específico
    python capturar_catalogo_vtex_completo.py --retailer carrefour

    # Solo ver categorías sin capturar (dry-run)
    python capturar_catalogo_vtex_completo.py --retailer carrefour --dry-run

    # Limitar productos por categoría (útil para pruebas)
    python capturar_catalogo_vtex_completo.py --retailer carrefour --max-por-categoria 200

Requisitos:
    pip install requests psycopg2-binary python-dotenv
"""

import argparse
import hashlib
import os
import time
import traceback
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# ── Configuración de retailers VTEX ───────────────────────────────────────────
RETAILERS_VTEX = {
    "carrefour": {
        "nombre":   "Carrefour",
        "base_url": "https://www.carrefour.com.ar",
    },
    "jumbo": {
        "nombre":   "Jumbo",
        "base_url": "https://www.jumbo.com.ar",
    },
    "disco": {
        "nombre":   "Disco",
        "base_url": "https://www.disco.com.ar",
    },
    "vea": {
        "nombre":   "Vea",
        "base_url": "https://www.vea.com.ar",
    },
    "changomas": {
        "nombre":   "Chango Más",
        "base_url": "https://www.masonline.com.ar",
    },
}

# ── Configuración general ─────────────────────────────────────────────────────
PAGE_SIZE            = 50       # productos por request (máx VTEX = 50)
MAX_POR_CATEGORIA    = 2000     # límite por categoría (0 = sin límite)
PAUSA_ENTRE_PAGES    = 0.4      # segundos entre páginas
PAUSA_ENTRE_CATS     = 0.8      # segundos entre categorías
PAUSA_ENTRE_RETAILS  = 3.0      # segundos entre retailers
MAX_REINTENTOS       = 3        # reintentos por request fallida
TIMEOUT              = 15       # segundos timeout por request

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json, text/plain, */*",
}


# ══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE EXTRACCIÓN VTEX
# ══════════════════════════════════════════════════════════════════════════════

def get_json(url: str, reintentos: int = MAX_REINTENTOS) -> dict | list | None:
    """GET con reintentos automáticos."""
    for intento in range(reintentos):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code in (200, 206):
                return r.json()
            elif r.status_code == 429:
                espera = 5 * (intento + 1)
                print(f"    Rate limit (429) — esperando {espera}s...")
                time.sleep(espera)
            elif r.status_code == 404:
                return None
            else:
                print(f"    HTTP {r.status_code} en {url}")
                time.sleep(2)
        except requests.exceptions.Timeout:
            print(f"    Timeout (intento {intento+1}/{reintentos})")
            time.sleep(2)
        except Exception as e:
            print(f"    Error: {e} (intento {intento+1}/{reintentos})")
            time.sleep(2)
    return None


def obtener_categorias(base_url: str) -> list[dict]:
    """Obtiene el árbol de categorías completo (3 niveles) de un retailer VTEX."""
    url = f"{base_url}/api/catalog_system/pub/category/tree/3"
    data = get_json(url)
    if not data:
        return []

    categorias_planas = []

    def flatten(cats, parent_path="", nivel=0):
        for cat in cats:
            cid = str(cat.get("id"))
            cpath = f"{parent_path}/{cid}" if parent_path else cid
            categorias_planas.append({
                "id":     cat.get("id"),
                "nombre": cat.get("name", ""),
                "nivel":  nivel,
                "path":   cpath,
            })
            hijos = cat.get("children") or []
            if hijos:
                flatten(hijos, cpath, nivel + 1)

    flatten(data)
    return categorias_planas


def obtener_productos_categoria(base_url: str, categoria_path: str,
                                max_productos: int = MAX_POR_CATEGORIA) -> list[dict]:
    """Obtiene todos los productos de una categoría paginando."""
    productos = []
    vistos = set()
    start = 0

    while True:
        if max_productos > 0 and len(productos) >= max_productos:
            break

        end = min(start + PAGE_SIZE - 1, start + PAGE_SIZE - 1)
        if max_productos > 0:
            end = min(end, max_productos - 1)

        url = (
            f"{base_url}/api/catalog_system/pub/products/search"
            f"?fq=C:/{categoria_path}/&_from={start}&_to={end}"
            f"&O=OrderByTopSaleDESC"
        )

        data = get_json(url)

        if not data:
            break

        nuevos = 0
        for p in data:
            pid = p.get("productId")
            if pid and pid not in vistos:
                vistos.add(pid)
                productos.append(p)
                nuevos += 1

        if len(data) < PAGE_SIZE:
            break  # última página

        if nuevos == 0:
            break  # sin productos nuevos = fin

        start += PAGE_SIZE
        time.sleep(PAUSA_ENTRE_PAGES)

    return productos


def extraer_precio_y_stock(item: dict, retailer: str) -> tuple:
    sellers = item.get("sellers") or []
    if not sellers:
        return None, None, None, None, "sin_seller"

    offer = (sellers[0].get("commertialOffer") or {})

    precio_actual  = offer.get("Price")
    
    if retailer in ["disco", "jumbo", "vea"]:
        precio_regular = offer.get("PriceWithoutDiscount") or precio_actual
        precio_oferta  = None
        try:
            if precio_actual and precio_regular:
                if float(precio_actual) < float(precio_regular):
                    precio_oferta = precio_actual
        except Exception:
            pass
    else:
        precio_regular = offer.get("ListPrice")
        precio_oferta  = None
        try:
            if precio_actual and precio_regular:
                if float(precio_actual) < float(precio_regular):
                    precio_oferta = precio_actual
        except Exception:
            pass

    disponible = offer.get("IsAvailable")
    stock      = offer.get("AvailableQuantity")

    if disponible is True:
        disp = "disponible"
    elif disponible is False:
        disp = "sin_stock"
    else:
        disp = "desconocida"

    if stock == 0:
        disp = "sin_stock"

    return precio_actual, precio_regular, precio_oferta, stock, disp


def normalizar_producto(p: dict, retailer: str) -> dict:
    items = p.get("items") or []
    item  = items[0] if items else {}

    precio_actual, precio_regular, precio_oferta, stock, disp = extraer_precio_y_stock(item, retailer)

    categorias = p.get("categories") or []
    categoria  = str(categorias[0]).strip("/") if categorias else ""

    images    = item.get("images") or []
    url_imagen = images[0].get("imageUrl", "") if images else ""

    return {
        "retailer":          retailer,
        "id_externo":        str(p.get("productId", "") or ""),
        "nombre_original":   str(p.get("productName", "") or "").strip(),
        "marca_original":    str(p.get("brand", "") or "").strip(),
        "categoria_original":categoria,
        "ean_detectado":     str(item.get("ean", "") or "").strip(),
        "url_producto":      str(p.get("link", "") or "").strip(),
        "url_imagen":        url_imagen,
        "precio_actual":     precio_actual,
        "precio_regular":    precio_regular,
        "precio_oferta":     precio_oferta,
        "disponibilidad":    disp,
        "stock":             stock,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GUARDADO EN SUPABASE / POSTGRES
# ══════════════════════════════════════════════════════════════════════════════

GUARDAR_CAPTURAS = True  # --solo-catalogo lo pone en False (modo liviano para busqueda)

def get_pg_conn():
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL no encontrada en el .env")
    conn = psycopg2.connect(url)
    # Si una corrida se corta (Ctrl+C), evita que queden transacciones colgadas
    # reteniendo locks via el pooler: la sesion idle se auto-termina.
    with conn.cursor() as c:
        c.execute("SET idle_in_transaction_session_timeout = '30s'")
        c.execute("SET statement_timeout = '60s'")
        c.execute("SET lock_timeout = '10s'")
    conn.commit()
    return conn


def obtener_id_fuente(cur, retailer: str) -> int | None:
    cur.execute("SELECT id_fuente FROM fuentes WHERE retailer = %s", (retailer,))
    row = cur.fetchone()
    return row[0] if row else None


def upsert_producto(cur, prod: dict, id_fuente: int) -> tuple[int, str]:
    cur.execute("""
        INSERT INTO productos_fuente
            (id_fuente, retailer, nombre_original, url_producto, url_imagen,
             categoria_original, ean_detectado, marca_original)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id_fuente, url_producto) DO UPDATE SET
            nombre_original   = EXCLUDED.nombre_original,
            url_imagen        = EXCLUDED.url_imagen,
            categoria_original= EXCLUDED.categoria_original,
            ean_detectado     = COALESCE(EXCLUDED.ean_detectado, productos_fuente.ean_detectado),
            marca_original    = COALESCE(EXCLUDED.marca_original, productos_fuente.marca_original),
            ultima_vez_visto  = now()
        RETURNING id_producto_fuente, (xmax = 0) as es_nuevo
    """, (
        id_fuente,
        prod["retailer"],
        prod["nombre_original"],
        prod["url_producto"] or f"sin-url-{prod['id_externo']}",
        prod["url_imagen"],
        prod["categoria_original"],
        prod["ean_detectado"] or None,
        prod["marca_original"] or None,
    ))
    row = cur.fetchone()
    return row[0], ("insertado" if row[1] else "actualizado")


def insertar_captura(cur, prod: dict, id_producto_fuente: int,
                     fecha: str, hora: str) -> bool:
    hash_base = "|".join([
        prod["retailer"],
        prod["id_externo"],
        prod["ean_detectado"] or "",
        str(id_producto_fuente),
        fecha,
        hora,
        str(prod["precio_actual"] or ""),
        prod["disponibilidad"],
    ])
    hash_captura = hashlib.sha256(hash_base.encode()).hexdigest()

    try:
        cur.execute("""
            INSERT INTO capturas_precio
                (id_producto_fuente, fecha_captura, hora_captura,
                 precio_actual, precio_regular, precio_oferta,
                 disponibilidad, hash_captura, score_confianza_dato,
                 estado_captura)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (hash_captura) DO NOTHING
        """, (
            id_producto_fuente,
            fecha, hora,
            prod["precio_actual"],
            prod["precio_regular"],
            prod["precio_oferta"],
            prod["disponibilidad"] in ("disponible",),
            hash_captura,
            1.0,
            "ok",
        ))
        return cur.rowcount > 0
    except Exception as e:
        print(f"    Error captura: {e}")
        return False


def guardar_batch(productos: list[dict], retailer: str,
                  fecha: str, hora: str) -> tuple[int, int, int]:
    conn = get_pg_conn()
    cur  = conn.cursor()

    id_fuente = obtener_id_fuente(cur, retailer)
    if not id_fuente:
        print(f"  WARN: no existe fuente para {retailer} en Supabase")
        conn.close()
        return 0, 0, 0

    insertados  = 0
    actualizados = 0
    capturas    = 0

    for prod in productos:
        if not prod["nombre_original"]:
            continue
        try:
            id_prod, accion = upsert_producto(cur, prod, id_fuente)
            if accion == "insertado":
                insertados += 1
            else:
                actualizados += 1

            if GUARDAR_CAPTURAS and prod["precio_actual"]:
                ok = insertar_captura(cur, prod, id_prod, fecha, hora)
                if ok:
                    capturas += 1

        except Exception as e:
            print(f"  Error guardando {prod['nombre_original'][:40]}: {e}")
            conn.rollback()
            continue

    conn.commit()

    # Actualizar ultima_captura en fuentes
    cur.execute("""
        UPDATE fuentes
        SET ultima_captura = now(),
            total_capturas = total_capturas + %s
        WHERE retailer = %s
    """, (capturas, retailer))
    conn.commit()
    conn.close()

    return insertados, actualizados, capturas


# ══════════════════════════════════════════════════════════════════════════════
# LÓGICA PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def capturar_retailer(retailer: str, config: dict,
                      dry_run: bool = False,
                      max_por_cat: int = MAX_POR_CATEGORIA):

    base_url = config["base_url"]
    nombre   = config["nombre"]

    print(f"\n{'='*70}")
    print(f"  RETAILER: {nombre} ({retailer})")
    print(f"  URL: {base_url}")
    print(f"  Modo: {'DRY-RUN (sin guardar)' if dry_run else 'PRODUCCIÓN'}")
    print(f"{'='*70}")

    # 1. Obtener categorías
    print("\n  Obteniendo árbol de categorías...")
    categorias = obtener_categorias(base_url)
    if not categorias:
        print(f"  ERROR: No se pudieron obtener categorías de {nombre}")
        return

    print(f"  {len(categorias)} categorías encontradas")
    for c in categorias[:10]:
        print(f"    {'  ' * c['nivel']}[{c['id']}] {c['nombre']}")
    if len(categorias) > 10:
        print(f"    ... y {len(categorias) - 10} más")

    if dry_run:
        print("\n  [DRY-RUN] Mostrando solo categorías. Usá sin --dry-run para capturar.")
        return

    # 2. Capturar productos por categoría
    fecha = datetime.now().strftime("%Y-%m-%d")
    hora  = datetime.now().strftime("%H:%M:%S")

    total_insertados  = 0
    total_actualizados = 0
    total_capturas    = 0
    total_productos   = 0
    cats_ok           = 0
    cats_error        = 0

    for i, cat in enumerate(categorias):
        print(f"\n  [{i+1}/{len(categorias)}] {cat['nombre']} (id={cat['id']})")

        try:
            productos_vtex = obtener_productos_categoria(
                base_url, cat["path"], max_productos=max_por_cat
            )

            if not productos_vtex:
                print(f"    Sin productos")
                time.sleep(PAUSA_ENTRE_CATS)
                continue

            productos_norm = [
                normalizar_producto(p, retailer)
                for p in productos_vtex
            ]

            # Filtrar productos sin URL (no se pueden guardar)
            productos_validos = [
                p for p in productos_norm
                if p["nombre_original"] and (p["url_producto"] or p["id_externo"])
            ]

            print(f"    {len(productos_validos)} productos — guardando en Supabase...")

            ins, act, cap = guardar_batch(productos_validos, retailer, fecha, hora)
            total_insertados  += ins
            total_actualizados += act
            total_capturas    += cap
            total_productos   += len(productos_validos)
            cats_ok += 1

            print(f"    ✓ +{ins} nuevos, {act} actualizados, {cap} capturas")

        except KeyboardInterrupt:
            print("\n\n  Interrumpido por el usuario.")
            break
        except Exception as e:
            print(f"    ERROR en categoría {cat['nombre']}: {e}")
            traceback.print_exc()
            cats_error += 1

        time.sleep(PAUSA_ENTRE_CATS)

    # 3. Resumen del retailer
    print(f"\n  {'─'*50}")
    print(f"  RESUMEN {nombre}")
    print(f"  {'─'*50}")
    print(f"  Categorías procesadas: {cats_ok} ok, {cats_error} errores")
    print(f"  Productos totales:     {total_productos:,}")
    print(f"  Nuevos insertados:     {total_insertados:,}")
    print(f"  Actualizados:          {total_actualizados:,}")
    print(f"  Capturas de precio:    {total_capturas:,}")

    return {
        "retailer":     retailer,
        "productos":    total_productos,
        "insertados":   total_insertados,
        "actualizados": total_actualizados,
        "capturas":     total_capturas,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Captura completa de catálogo VTEX para todos los retailers."
    )
    parser.add_argument(
        "--retailer",
        choices=list(RETAILERS_VTEX.keys()),
        default=None,
        help="Retailer específico. Sin este argumento corre todos.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo muestra categorías, no guarda nada.",
    )
    parser.add_argument(
        "--solo-catalogo",
        action="store_true",
        help="Modo liviano: refresca solo el indice de busqueda (productos_fuente), sin historico de precios.",
    )
    parser.add_argument(
        "--max-por-categoria",
        type=int,
        default=MAX_POR_CATEGORIA,
        help=f"Máximo de productos por categoría (default: {MAX_POR_CATEGORIA}, 0=sin límite).",
    )
    args = parser.parse_args()

    global GUARDAR_CAPTURAS
    if args.solo_catalogo:
        GUARDAR_CAPTURAS = False

    retailers_a_correr = (
        {args.retailer: RETAILERS_VTEX[args.retailer]}
        if args.retailer
        else RETAILERS_VTEX
    )

    print("\n" + "═" * 70)
    print("  JUSTO PRICING 360 — Captura completa catálogo VTEX")
    print("═" * 70)
    print(f"  Retailers: {', '.join(retailers_a_correr.keys())}")
    print(f"  Max por categoría: {args.max_por_categoria or 'sin límite'}")
    print(f"  Modo: {'DRY-RUN' if args.dry_run else 'PRODUCCIÓN'}")

    inicio = datetime.now()
    resultados = []

    for retailer, config in retailers_a_correr.items():
        resultado = capturar_retailer(
            retailer, config,
            dry_run=args.dry_run,
            max_por_cat=args.max_por_categoria,
        )
        if resultado:
            resultados.append(resultado)
        if not args.dry_run:
            time.sleep(PAUSA_ENTRE_RETAILS)

    duracion = int((datetime.now() - inicio).total_seconds())

    if resultados:
        print("\n" + "═" * 70)
        print("  RESUMEN FINAL")
        print("═" * 70)
        print(f"  {'Retailer':<15} {'Productos':>10} {'Nuevos':>10} {'Capturas':>10}")
        print(f"  {'─'*15} {'─'*10} {'─'*10} {'─'*10}")
        for r in resultados:
            print(f"  {r['retailer']:<15} {r['productos']:>10,} {r['insertados']:>10,} {r['capturas']:>10,}")
        total_p = sum(r["productos"] for r in resultados)
        total_n = sum(r["insertados"] for r in resultados)
        total_c = sum(r["capturas"] for r in resultados)
        print(f"  {'─'*15} {'─'*10} {'─'*10} {'─'*10}")
        print(f"  {'TOTAL':<15} {total_p:>10,} {total_n:>10,} {total_c:>10,}")
        print(f"\n  Duración total: {duracion // 60}m {duracion % 60}s")
        print("═" * 70)


if __name__ == "__main__":
    main()
