"""Scraper base VTEX para Día y Chango Más."""

import logging
import time
from typing import Any, List, Optional

from fuentes.base_scraper import BaseScraper, ProductoCapturado
import random
import requests

def get_json_con_reintentos(url, headers=None, timeout=30, max_intentos=8, logger=None, fuente='VTEX'):
    import time
    import random
    import requests

    for intento in range(1, max_intentos + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout)

            if response.status_code == 429:
                espera = min(45 * intento, 240) + random.randint(10, 35)
                mensaje = f'[{fuente}] HTTP 429 Too Many Requests. Intento {intento}/{max_intentos}. Esperando {espera}s y reintentando misma pagina...'
                if logger:
                    logger.warning(mensaje)
                else:
                    print(mensaje)
                time.sleep(espera)
                continue

            if response.status_code in [500, 502, 503, 504]:
                espera = min(30 * intento, 180) + random.randint(5, 25)
                mensaje = f'[{fuente}] Error servidor {response.status_code}. Intento {intento}/{max_intentos}. Esperando {espera}s y reintentando...'
                if logger:
                    logger.warning(mensaje)
                else:
                    print(mensaje)
                time.sleep(espera)
                continue

            response.raise_for_status()

            try:
                return response.json()
            except ValueError:
                espera = 30 + random.randint(5, 20)
                mensaje = f'[{fuente}] Respuesta no es JSON valido. Intento {intento}/{max_intentos}. Esperando {espera}s...'
                if logger:
                    logger.warning(mensaje)
                else:
                    print(mensaje)
                time.sleep(espera)
                continue

        except requests.exceptions.RequestException as e:
            espera = min(30 * intento, 180) + random.randint(5, 25)
            mensaje = f'[{fuente}] Error de request: {e}. Intento {intento}/{max_intentos}. Esperando {espera}s...'
            if logger:
                logger.warning(mensaje)
            else:
                print(mensaje)
            time.sleep(espera)
            continue

    raise RuntimeError(f'[{fuente}] No se pudo obtener JSON luego de {max_intentos} intentos: {url}')


logger = logging.getLogger(__name__)


class VTEXScraper(BaseScraper):
    VTEX_API_PATH = "/api/catalog_system/pub/products/search"
    ITEMS_POR_PAGINA = 49

    def __init__(self, config_fuente: dict, config_captura: dict):
        super().__init__(config_fuente, config_captura)
        self.vtex_account = config_fuente.get("vtex_account", "")
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    def _url_api_vtex(self) -> str:
        return f"{self.url_base}{self.VTEX_API_PATH}"

    def capturar_categoria(self, categoria_config: dict) -> List[ProductoCapturado]:
        productos: List[ProductoCapturado] = []
        categoria_id = categoria_config.get("categoria_id")
        nombre_cat = categoria_config.get("nombre", "General")

        if not categoria_id:
            logger.error("[%s] Categoría sin categoria_id: %s", self.retailer, nombre_cat)
            return productos

        desde = 0
        max_paginas = int(self.config_captura.get("max_paginas_por_categoria", 800))

        # Límite específico de la categoría, si existe.
        limite_categoria = (
            categoria_config.get("limite_productos")
            or categoria_config.get("__max_productos_categoria")
        )

        # Límite global de la corrida.
        # Esto evita que una categoría enorme, como Almacén, recorra miles de productos
        # cuando el comando se ejecuta con --max 300 o similar.
        limite_corrida = (
            self.config_captura.get("max_productos_corrida")
            or self.config_captura.get("max_productos")
            or self.config_captura.get("limite_productos")
        )

        if limite_categoria:
            limite_categoria = int(limite_categoria)
        elif limite_corrida:
            limite_categoria = int(limite_corrida)
        else:
            limite_categoria = None

        logger.info(
            "[%s] %s: iniciando VTEX | categoria_id=%s | page_size=%s | max_paginas=%s",
            self.retailer,
            nombre_cat,
            categoria_id,
            self.ITEMS_POR_PAGINA,
            max_paginas,
        )

        for pagina in range(max_paginas):
            hasta = desde + self.ITEMS_POR_PAGINA
            params = {
                "fq": f"C:/{categoria_id}/",
                "_from": desde,
                "_to": hasta,
                "O": "OrderByTopSaleDESC",
            }

            try:
                data = self._get_json(self._url_api_vtex(), params=params)

                if not data or not isinstance(data, list):
                    logger.info(
                        "[%s] %s | página %s | rango %s-%s | sin datos, fin de categoría",
                        self.retailer,
                        nombre_cat,
                        pagina + 1,
                        desde,
                        hasta,
                    )
                    break

                nuevos = 0

                for item in data:
                    prod = self._parsear_producto_vtex(item, nombre_cat)
                    if prod:
                        prod.calcular_hash()
                        productos.append(prod)
                        nuevos += 1

                    if limite_categoria and len(productos) >= int(limite_categoria):
                        break

                # Loguea las primeras páginas y después cada 10 páginas,
                # igual que Coto, para no saturar la consola.
                if pagina < 3 or (pagina + 1) % 10 == 0 or len(data) < self.ITEMS_POR_PAGINA:
                    logger.info(
                        "[%s] %s | página %s | rango %s-%s | +%s | acumulado categoría: %s",
                        self.retailer,
                        nombre_cat,
                        pagina + 1,
                        desde,
                        hasta,
                        nuevos,
                        len(productos),
                    )

                if limite_categoria and len(productos) >= int(limite_categoria):
                    logger.info(
                        "[%s] %s: límite de categoría alcanzado (%s)",
                        self.retailer,
                        nombre_cat,
                        limite_categoria,
                    )
                    break

                if len(data) < self.ITEMS_POR_PAGINA:
                    logger.info(
                        "[%s] %s: última página detectada | registros página=%s | total categoría=%s",
                        self.retailer,
                        nombre_cat,
                        len(data),
                        len(productos),
                    )
                    break

                desde = hasta + 1
                self._esperar()

                # Chango Más / MásOnline aplica rate limit más agresivo.
                # Se agrega pausa extra para evitar HTTP 429 Too Many Requests.
                if self.retailer == "changomas":
                    logger.info(
                        "[%s] Pausa anti-rate-limit Chango Más antes de próxima página...",
                        self.retailer,
                    )
                    time.sleep(12)

            except Exception as e:
                logger.error("[%s] Error VTEX cat %s página %s: %s", self.retailer, nombre_cat, pagina + 1, e)
                break

        if not productos:
            logger.warning("[%s] Fallback búsqueda texto: %s", self.retailer, nombre_cat)
            productos = self._busqueda_vtex_texto(nombre_cat)

        logger.info("[%s] %s: %s productos", self.retailer, nombre_cat, len(productos))
        return productos

    def _parsear_producto_vtex(self, item: dict, categoria: str) -> Optional[ProductoCapturado]:
        p = ProductoCapturado()
        p.fuente = f"{self.retailer}_vtex"
        p.retailer = self.retailer
        p.categoria = categoria
        p.nombre_producto_original = (item.get("productName") or "").strip()

        if not p.nombre_producto_original:
            return None

        p.marca_original = item.get("brand") or item.get("brandId")
        p.subcategoria = categoria

        link = item.get("link", "")
        p.url_producto = link if str(link).startswith("http") else f"{self.url_base}{link}"

        items = item.get("items", []) or []

        if items:
            sku = items[0]

            ean = sku.get("ean")
            if not ean and sku.get("referenceId"):
                try:
                    ean = sku.get("referenceId", [{}])[0].get("Value")
                except Exception:
                    ean = None

            if ean and str(ean).isdigit() and len(str(ean)) >= 8:
                p.ean = str(ean)

            images = sku.get("images", []) or []
            if images:
                p.url_imagen = images[0].get("imageUrl")

            sellers = sku.get("sellers", []) or []
            offer = None

            for seller in sellers:
                comm = seller.get("commertialOffer") or {}
                if comm:
                    offer = comm
                    break

            if offer:
                price = self.limpiar_precio(offer.get("Price"))
                available = offer.get("IsAvailable", True)

                p.disponibilidad = bool(available)

                if self.retailer in ["disco", "jumbo", "vea"]:
                    price_without_discount = self.limpiar_precio(offer.get("PriceWithoutDiscount"))
                    if price:
                        p.precio_actual = price
                        p.precio_regular = price_without_discount or price

                        if price_without_discount and price < price_without_discount:
                            p.precio_oferta = price
                    else:
                        p.tipo_promocion = "SIN_PRECIO"
                else:
                    list_price = self.limpiar_precio(offer.get("ListPrice"))
                    if price:
                        p.precio_actual = price
                        p.precio_regular = list_price or price

                        if list_price and price < list_price:
                            p.precio_oferta = price
                    else:
                        p.tipo_promocion = "SIN_PRECIO"

                teasers = offer.get("Teasers") or []
                if teasers:
                    names = [t.get("Name") for t in teasers if t.get("Name")]
                    p.texto_promocion = " | ".join(names) if names else None

                if not p.disponibilidad:
                    p.tipo_promocion = "SIN_STOCK"

        return p

    def _busqueda_vtex_texto(self, termino: str) -> List[ProductoCapturado]:
        productos = []
        params = {"ft": termino, "_from": 0, "_to": self.ITEMS_POR_PAGINA}

        data = self._get_json(self._url_api_vtex(), params=params)

        if data and isinstance(data, list):
            logger.info("[%s] Fallback texto '%s': %s registros", self.retailer, termino, len(data))

            for item in data:
                prod = self._parsear_producto_vtex(item, termino)
                if prod:
                    prod.calcular_hash()
                    productos.append(prod)

        return productos

    def _parsear_producto(self, raw_data: Any) -> Optional[ProductoCapturado]:
        return self._parsear_producto_vtex(raw_data, "General")
