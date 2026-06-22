import os
import time
import requests
import hashlib
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

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
    "dia": {
        "nombre":   "Dia",
        "base_url": "https://diaio.vtexcommercestable.com.br", # Or https://www.supermercadosdia.com.ar ? Let's see config.yaml
    }
}

# Let's adjust Dia url from config.yaml
# config.yaml says: url_base: https://diaio.vtexcommercestable.com.br for dia
# Wait, let's use the url from config.yaml:
RETAILERS_VTEX["dia"]["base_url"] = "https://www.supermercadosdia.com.ar" # Or let's test if alternateIds_Ean works on dia vtex domain

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json, text/plain, */*",
}

def get_pg_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL not found in environment")
    conn = psycopg2.connect(url)
    # Autocommit: cada upsert/captura se confirma al instante. Evita transacciones
    # largas que retienen locks y, si la corrida se corta, no deja transacciones
    # abiertas bloqueando (causa del statement timeout).
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute("SET statement_timeout = '30s'")
        c.execute("SET lock_timeout = '8s'")
        c.execute("SET idle_in_transaction_session_timeout = '60s'")
    return conn

def get_target_eans(cur):
    """Todos los EANs a capturar: productos de TODOS los clientes activos + sus
    competidores. Universal, sin hardcodear cliente ni marca."""
    cur.execute("""
        SELECT DISTINCT ean FROM (
            SELECT ean
            FROM productos_cliente
            WHERE activo = true AND ean IS NOT NULL AND ean != ''
            UNION
            SELECT m.ean_competidor AS ean
            FROM mapa_competitivo_cliente m
            WHERE m.activo = true
              AND m.ean_competidor IS NOT NULL AND m.ean_competidor != ''
        ) t;
    """)
    return [r[0] for r in cur.fetchall()]


def get_target_brands(cur):
    """Marcas objetivo (cliente + competidores) en minuscula, para keyword search
    en VTEX y para el filtro de Coto. Universal."""
    cur.execute("""
        SELECT DISTINCT lower(trim(marca)) AS marca FROM (
            SELECT marca FROM productos_cliente
            WHERE activo = true AND marca IS NOT NULL AND trim(marca) != ''
            UNION
            SELECT marca_competidor AS marca FROM mapa_competitivo_cliente
            WHERE activo = true AND marca_competidor IS NOT NULL AND trim(marca_competidor) != ''
        ) t;
    """)
    return [r[0] for r in cur.fetchall() if r[0]]


def get_coto_categorias():
    """(nombre, path) de categorias de Coto desde config.yaml. Fallback a Limpieza."""
    try:
        import yaml
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml")
        c = yaml.safe_load(open(cfg_path, encoding="utf-8"))
        cats = c["fuentes"]["coto"]["categorias"]
        return [(cat["nombre"], cat["url"]) for cat in cats]
    except Exception as e:
        print(f"  No se pudo leer categorias Coto de config.yaml ({e}); uso Limpieza")
        return [("Limpieza", "/sitios/cdigi/categoria/catalogo-limpieza/_/N-nityfw")]

def obtener_id_fuente(cur, retailer: str) -> int:
    cur.execute("SELECT id_fuente FROM fuentes WHERE retailer = %s", (retailer,))
    row = cur.fetchone()
    return row[0] if row else None

def upsert_producto(cur, prod: dict, id_fuente: int) -> int:
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
        RETURNING id_producto_fuente
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
    return cur.fetchone()[0]

def insertar_captura(cur, prod: dict, id_producto_fuente: int, fecha: str, hora: str) -> bool:
    # Solo guardamos una captura si CAMBIO algo respecto a la ultima (precio o
    # disponibilidad). Antes se guardaba una fila por corrida aunque no cambiara
    # nada (el hash incluia fecha/hora), lo que inflaba la tabla ~15k filas/dia.
    disp_bool = prod["disponibilidad"] == "disponible"

    def _n(x):
        try:
            return None if x is None or x == "" else round(float(x), 2)
        except Exception:
            return None

    nueva = (_n(prod["precio_actual"]), _n(prod["precio_regular"]),
             _n(prod["precio_oferta"]), disp_bool)

    cur.execute("""
        SELECT precio_actual, precio_regular, precio_oferta, disponibilidad
        FROM capturas_precio
        WHERE id_producto_fuente = %s
        ORDER BY fecha_captura DESC, id_captura DESC
        LIMIT 1
    """, (id_producto_fuente,))
    last = cur.fetchone()

    if last is not None:
        anterior = (_n(last[0]), _n(last[1]), _n(last[2]), bool(last[3]))
        if nueva == anterior:
            return False  # sin cambios -> no se guarda (ahorra espacio)

    es_cambio = last is not None  # habia captura previa distinta -> es un cambio real

    hash_base = "|".join([
        prod["retailer"],
        prod.get("id_externo", ""),
        prod["ean_detectado"] or "",
        str(id_producto_fuente),
        fecha,
        hora,
        str(prod["precio_actual"] or ""),
        str(prod["disponibilidad"]),
    ])
    hash_captura = hashlib.sha256(hash_base.encode()).hexdigest()

    cur.execute("SELECT 1 FROM capturas_precio WHERE hash_captura = %s LIMIT 1", (hash_captura,))
    if cur.fetchone():
        return False  # duplicado exacto

    cur.execute("""
        INSERT INTO capturas_precio
            (id_producto_fuente, fecha_captura, hora_captura,
             precio_actual, precio_regular, precio_oferta,
             disponibilidad, hash_captura, score_confianza_dato,
             estado_captura, es_cambio_precio)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1.0, 'ok', %s)
    """, (
        id_producto_fuente,
        fecha, hora,
        prod["precio_actual"],
        prod["precio_regular"],
        prod["precio_oferta"],
        disp_bool,
        hash_captura,
        es_cambio,
    ))
    return True

def _mejor_offer(sellers: list) -> dict:
    """Elige el seller disponible con menor Price valido. Evita sellers de
    marketplace o presentaciones (packs/cajas) con precios inflados. Universal."""
    cand = []
    for sel in sellers:
        off = sel.get("commertialOffer") or {}
        price = off.get("Price")
        try:
            price = float(price) if price is not None else None
        except Exception:
            price = None
        if price and price > 0:
            cand.append((price, off, bool(off.get("IsAvailable"))))
    if not cand:
        return (sellers[0].get("commertialOffer") or {}) if sellers else {}
    disponibles = [c for c in cand if c[2]]
    pool = disponibles if disponibles else cand
    pool.sort(key=lambda x: x[0])
    return pool[0][1]

def extraer_precio_y_stock(item: dict, retailer: str) -> tuple:
    sellers = item.get("sellers") or []
    if not sellers:
        return None, None, None, None, "sin_seller"

    offer = _mejor_offer(sellers)
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

    disp = "disponible" if disponible is True else "sin_stock"
    if stock == 0:
        disp = "sin_stock"

    return precio_actual, precio_regular, precio_oferta, stock, disp

def normalizar_producto_vtex(p: dict, retailer: str, target_ean: str = None) -> dict:
    items = p.get("items") or []
    item = None
    if target_ean:
        te = str(target_ean).strip()
        for it in items:
            if str(it.get("ean", "") or "").strip() == te:
                item = it
                break
    if item is None:
        item = items[0] if items else {}
    precio_actual, precio_regular, precio_oferta, stock, disp = extraer_precio_y_stock(item, retailer)
    categorias = p.get("categories") or []
    categoria  = str(categorias[0]).strip("/") if categorias else "Limpieza"
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

def _producto_con_ean(data: list, ean: str):
    """De una lista de productos VTEX, devuelve el que tiene un SKU con ese EAN exacto."""
    te = str(ean).strip()
    for p in data:
        for it in (p.get("items") or []):
            if str(it.get("ean", "") or "").strip() == te:
                return p
    return None

def buscar_por_ean(base_url: str, ret_key: str, ean: str):
    """Busca un producto por EAN probando dos endpoints VTEX:
      1) fq=alternateIds_Ean:<ean>  (cuando el EAN esta indexado como alt id)
      2) ft=<ean>                   (full-text; muchas tiendas resuelven el EAN asi)
    El fallback ft es clave: en varias tiendas (p.ej. Carrefour) alternateIds_Ean
    no devuelve nada y, sin esto, los productos solo se capturaban en el catalogo
    semanal y nunca en el scrapeo dirigido diario.
    Para ft se exige match EXACTO de EAN para no traer productos equivocados."""
    endpoints = [
        (f"{base_url}/api/catalog_system/pub/products/search?fq=alternateIds_Ean:{ean}", True),
        (f"{base_url}/api/catalog_system/pub/products/search?ft={ean}", False),
    ]
    for url, confiable in endpoints:
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    p = _producto_con_ean(data, ean)
                    if p is None and confiable:
                        p = data[0]  # alternateIds_Ean ya filtra por EAN: confiamos en el 1ro
                    if p is not None:
                        return normalizar_producto_vtex(p, ret_key, target_ean=ean)
        except Exception as e:
            print(f"  Error buscando EAN {ean} en {ret_key}: {e}")
        time.sleep(0.15)
    return None

def main():
    print("Iniciando captura dirigida JUSTO (productos de clientes + competidores)...")
    load_dotenv()
    
    conn = get_pg_conn()
    cur = conn.cursor()
    
    eans = get_target_eans(cur)
    eans_set = set(eans)
    brands = get_target_brands(cur)
    print(f"EANs objetivo (productos de clientes + competidores): {len(eans)}")
    print(f"Marcas objetivo para keyword search: {len(brands)}")
    
    fecha = datetime.now().strftime("%Y-%m-%d")
    hora  = datetime.now().strftime("%H:%M:%S")
    
    # ── VTEX Retailers ──────────────────────────────────────────────────────────
    # Para Dia, use the one in config: diaio.vtexcommercestable.com.br or superdia
    # Let's support both or check if we can query dia
    dia_url = "https://diaio.vtexcommercestable.com.br"
    RETAILERS_VTEX["dia"]["base_url"] = dia_url
    
    for ret_key, ret_cfg in RETAILERS_VTEX.items():
        base_url = ret_cfg["base_url"]
        nombre = ret_cfg["nombre"]
        print(f"\nScraping VTEX {nombre} ({ret_key})...")
        
        id_fuente = obtener_id_fuente(cur, ret_key)
        if not id_fuente:
            print(f"  ERROR: no id_fuente for {ret_key}")
            continue
            
        productos_detectados = []
        
        # 1. Search by EAN (alternateIds_Ean + fallback full-text ft=)
        for ean in eans:
            p_norm = buscar_por_ean(base_url, ret_key, ean)
            if p_norm:
                productos_detectados.append(p_norm)
                print(f"  Found EAN {ean}: {p_norm['nombre_original']} -> ${p_norm['precio_actual']}")
                
        # 2. Search by brand keywords (cliente + competidores) para captar variantes
        for brand in brands:
            url_kw = f"{base_url}/api/catalog_system/pub/products/search?ft={requests.utils.quote(brand)}&_from=0&_to=49"
            try:
                r = requests.get(url_kw, headers=HEADERS, timeout=12)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list) and data:
                        for p in data:
                            p_norm = normalizar_producto_vtex(p, ret_key)
                            if not any(pd["id_externo"] == p_norm["id_externo"] for pd in productos_detectados):
                                productos_detectados.append(p_norm)
                time.sleep(0.2)
            except Exception as e:
                print(f"  Error searching brand '{brand}' on {ret_key}: {e}")
            
        # Save to DB
        ins_cnt = 0
        cap_cnt = 0
        for prod in productos_detectados:
            try:
                id_pf = upsert_producto(cur, prod, id_fuente)
                ins_cnt += 1
                if prod["precio_actual"]:
                    ok = insertar_captura(cur, prod, id_pf, fecha, hora)
                    if ok:
                        cap_cnt += 1
            except Exception as e:
                print(f"  Error saving product {prod.get('nombre_original')}: {e}")
                conn.rollback()
                
        # Update fuentes table
        cur.execute("""
            UPDATE fuentes
            SET ultima_captura = now(),
                total_capturas = total_capturas + %s
            WHERE id_fuente = %s
        """, (cap_cnt, id_fuente))
        conn.commit()
        print(f"  -> {nombre} guardado: {ins_cnt} upserts, {cap_cnt} nuevas capturas")

    # ── COTO ──────────────────────────────────────────
    print("\nScraping COTO Digital (todas las categorias)...")
    id_fuente_coto = obtener_id_fuente(cur, "coto")
    if id_fuente_coto:
        coto_base = "https://www.cotodigital.com.ar"
        coto_products = []
        seen_coto = set()

        import json
        def limpiar_precio(texto):
            if not texto: return None
            s = str(texto).replace("$", "").replace("ARS", "").replace(" ", "").strip()
            if "," in s: s = s.replace(",", ".")
            try: return float(s)
            except: return None

        categorias = get_coto_categorias()
        for cat_nombre, cat_path in categorias:
            url_cat = f"{coto_base}{cat_path}" if cat_path.startswith("/") else f"{coto_base}/sitios/cdigi/categoria/{cat_path}"
            offset = 0
            limit = 30
            cat_count = 0

            for page in range(80): # up to 2400 products por categoria
                params = {"format": "json", "Nrpp": limit, "No": offset}
                try:
                    r = requests.get(url_cat, params=params, headers=HEADERS, timeout=15)
                    if r.status_code != 200:
                        break
                    data = r.json()
                    contents = data.get("contents", [{}])[0].get("Main", [])
                    records = []
                    for slot in contents:
                        if slot.get("@type") == "Main_Slot":
                            sub_contents = slot.get("contents", [])
                            if sub_contents:
                                records = sub_contents[0].get("records", []) or []
                                break
                    if not records:
                        break

                    for record in records:
                        sub = record.get("records") or []
                        raw = sub[0] if sub else record
                        attrs = raw.get("attributes", {}) or {}

                        def get_attr(key):
                            val = attrs.get(key)
                            if isinstance(val, list) and val:
                                return str(val[0]).strip()
                            if val is not None:
                                return str(val).strip()
                            return None

                        name = get_attr("product.displayName") or get_attr("sku.displayName")
                        marca = get_attr("product.MARCA") or get_attr("product.brand")
                        ean = get_attr("product.eanPrincipal") or get_attr("sku.ean")

                        if not name:
                            continue

                        # Filtro universal: EAN objetivo (cliente o competidor) o marca objetivo
                        name_l = name.lower()
                        marca_l = (marca or "").lower()
                        es_objetivo = (ean in eans_set) or any(b in name_l or b in marca_l for b in brands)
                        if not es_objetivo:
                            continue

                        precio_activo = limpiar_precio(get_attr("sku.activePrice"))
                        precio_regular = precio_activo
                        precio_oferta = None

                        dto_raw = get_attr("product.dtoDescuentos")
                        if dto_raw:
                            try:
                                dtos = json.loads(dto_raw)
                                if dtos:
                                    precio_dto = limpiar_precio(dtos[0].get("precioDescuento"))
                                    if precio_dto and precio_activo and precio_dto < precio_activo:
                                        precio_oferta = precio_dto
                                        precio_activo = precio_dto
                            except:
                                pass

                        url_prod = ""
                        record_state = raw.get("detailsAction", {}).get("recordState", "")
                        if record_state:
                            slug = record_state.split("/_/")[0] if "/_/" in record_state else record_state
                            slug = slug.split("?")[0]
                            url_prod = f"https://www.cotodigital.com.ar/sitios/cdigi/producto{slug}"

                        url_img = get_attr("product.largeImage.url") or get_attr("product.mediumImage.url")

                        id_ext = ean or url_prod
                        if id_ext in seen_coto:
                            continue
                        seen_coto.add(id_ext)

                        prod_norm = {
                            "retailer":          "coto",
                            "id_externo":        id_ext,
                            "nombre_original":   name,
                            "marca_original":    marca or None,
                            "categoria_original":cat_nombre,
                            "ean_detectado":     ean,
                            "url_producto":      url_prod,
                            "url_imagen":        url_img,
                            "precio_actual":     precio_activo,
                            "precio_regular":    precio_regular,
                            "precio_oferta":     precio_oferta,
                            "disponibilidad":    "disponible" if precio_activo else "sin_stock",
                        }
                        coto_products.append(prod_norm)
                        cat_count += 1

                    offset += limit
                    time.sleep(0.3)
                except Exception as e:
                    print(f"  Error en Coto {cat_nombre} pagina {page+1}: {e}")
                    break

            print(f"  Coto categoria '{cat_nombre}': {cat_count} objetivos encontrados")

        # Save Coto products to DB
        ins_cnt = 0
        cap_cnt = 0
        for prod in coto_products:
            try:
                id_pf = upsert_producto(cur, prod, id_fuente_coto)
                ins_cnt += 1
                if prod["precio_actual"]:
                    ok = insertar_captura(cur, prod, id_pf, fecha, hora)
                    if ok:
                        cap_cnt += 1
            except Exception as e:
                print(f"  Error saving Coto product {prod.get('nombre_original')}: {e}")
                conn.rollback()

        # Update fuentes table
        cur.execute("""
            UPDATE fuentes
            SET ultima_captura = now(),
                total_capturas = total_capturas + %s
            WHERE id_fuente = %s
        """, (cap_cnt, id_fuente_coto))
        conn.commit()
        print(f"  -> COTO guardado: {ins_cnt} upserts, {cap_cnt} nuevas capturas")
        
    cur.close()
    conn.close()
    print("\nTargeted scraping completado exitosamente.")

if __name__ == "__main__":
    main()
