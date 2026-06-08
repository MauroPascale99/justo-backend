"""Scraper universal Coto Digital — ATG JSON."""

import json
import logging
from typing import Optional

from fuentes.base_scraper import BaseScraper, ProductoCapturado

logger = logging.getLogger(__name__)


class CotoScraper(BaseScraper):
    ITEMS_POR_PAGINA = 30

    def _extraer_catalogo(self, data: dict) -> Optional[dict]:
        try:
            for slot in data.get("contents", [{}])[0].get("Main", []):
                if slot.get("@type") == "Main_Slot":
                    contents = slot.get("contents", [])
                    if contents:
                        return contents[0]
        except Exception:
            return None
        return None

    def capturar_categoria(self, categoria_config):
        productos = []
        nombre_cat = categoria_config.get("nombre", "Sin categoría")
        url_path = categoria_config.get("url")
        max_categoria = int(categoria_config.get("__max_productos_categoria") or 0)
        if not url_path:
            logger.error("[Coto] Sin URL para categoría %s", nombre_cat)
            return productos

        url_base_cat = self.url_base + url_path
        offset = 0
        iteracion = 0
        max_iteraciones = int(self.config_captura.get("max_paginas_por_categoria", 800))
        total = 0

        while iteracion < max_iteraciones:
            if max_categoria and len(productos) >= max_categoria:
                logger.info("[Coto] %s: límite de prueba alcanzado dentro de categoría (%s)", nombre_cat, max_categoria)
                break

            params = {"format": "json", "Nrpp": self.ITEMS_POR_PAGINA, "No": offset}
            try:
                data = self._get_json(url_base_cat, params=params)
                if not data:
                    logger.warning("[Coto] %s: respuesta vacía en offset %s", nombre_cat, offset)
                    break
                catalogo = self._extraer_catalogo(data)
                if not catalogo:
                    logger.error("[Coto] Sin Main_Slot para %s en offset %s", nombre_cat, offset)
                    break
                total = int(catalogo.get("totalNumRecs", 0) or 0)
                records = catalogo.get("records", []) or []
                if iteracion == 0:
                    paginas_estimadas = (total // self.ITEMS_POR_PAGINA) + (1 if total % self.ITEMS_POR_PAGINA else 0)
                    logger.info("[Coto] %s: %s productos declarados | %s páginas estimadas", nombre_cat, total, paginas_estimadas)
                if not records or total == 0:
                    logger.warning("[Coto] %s: sin records en offset %s", nombre_cat, offset)
                    break

                agregados_pagina = 0
                for record in records:
                    if max_categoria and len(productos) >= max_categoria:
                        break
                    sub = record.get("records") or []
                    raw = sub[0] if sub else record
                    prod = self._parsear_sku(raw, nombre_cat)
                    if prod:
                        prod.calcular_hash()
                        productos.append(prod)
                        agregados_pagina += 1

                iteracion += 1
                offset += self.ITEMS_POR_PAGINA

                # Log de avance: primeras 3 páginas y luego cada 10 páginas.
                if iteracion <= 3 or iteracion % 10 == 0 or offset >= total:
                    porcentaje = (min(offset, total) / total * 100) if total else 0
                    logger.info(
                        "[Coto] %s | página %s | offset %s/%s | %.1f%% | +%s | acumulado categoría: %s",
                        nombre_cat, iteracion, min(offset, total), total, porcentaje, agregados_pagina, len(productos)
                    )

                if offset >= total:
                    break
                self._esperar()
            except Exception as e:
                logger.error("[Coto] Error en %s offset %s: %s", nombre_cat, offset, e)
                break

        logger.info("[Coto] %s: %s productos capturados", nombre_cat, len(productos))
        return productos

    def _parsear_sku(self, record, categoria):
        attrs = record.get("attributes", {}) or {}

        def get(key):
            val = attrs.get(key)
            if isinstance(val, list) and val:
                return str(val[0]).strip()
            if val is not None and not isinstance(val, list):
                return str(val).strip()
            return None

        p = ProductoCapturado()
        p.fuente = "coto_digital"
        p.retailer = "coto"
        p.categoria = categoria
        p.nombre_producto_original = get("product.displayName") or get("sku.displayName") or get("product.description")
        if not p.nombre_producto_original:
            return None

        # Marca estructurada de Coto. Esta es la fuente más confiable.
        p.marca_original = get("product.MARCA") or get("product.brand") or get("sku.brand")
        if not p.marca_original:
            dto_car = get("product.dtoCaracteristicas")
            if dto_car:
                try:
                    for item in json.loads(dto_car):
                        if str(item.get("nombre", "")).upper() == "MARCA":
                            p.marca_original = item.get("descripcion")
                            break
                except Exception:
                    pass

        ean = get("product.eanPrincipal") or get("sku.ean")
        if ean and ean.isdigit() and len(ean) >= 8:
            p.ean = ean

        p.subcategoria = get("product.LCLASE") or get("parentCategory.displayName")

        record_state = record.get("detailsAction", {}).get("recordState", "")
        if record_state:
            slug = record_state.split("/_/")[0] if "/_/" in record_state else record_state
            slug = slug.split("?")[0]
            p.url_producto = f"https://www.cotodigital.com.ar/sitios/cdigi/producto{slug}"

        p.url_imagen = get("product.largeImage.url") or get("product.mediumImage.url")

        precio_activo = self.limpiar_precio(get("sku.activePrice"))
        precio_por_unidad = self.limpiar_precio(get("sku.referencePrice"))
        if precio_activo:
            p.precio_regular = precio_activo
            p.precio_actual = precio_activo
        else:
            p.tipo_promocion = "SIN_PRECIO"
        if precio_por_unidad and precio_activo and abs(precio_por_unidad - precio_activo) > 1:
            p.precio_por_unidad = precio_por_unidad

        dto_raw = get("product.dtoDescuentos")
        if dto_raw:
            try:
                dtos = json.loads(dto_raw)
                if dtos:
                    dto = dtos[0]
                    precio_dto = self.limpiar_precio(dto.get("precioDescuento"))
                    texto = " ".join(filter(None, [dto.get("textoDescuento", "").strip(), dto.get("textoPrecioRegular", "").strip()]))
                    if precio_dto and precio_activo and precio_dto < precio_activo:
                        p.precio_oferta = precio_dto
                        p.precio_actual = precio_dto
                        p.texto_promocion = texto or None
                    elif texto:
                        p.texto_promocion = texto
            except Exception:
                pass

        p.disponibilidad = True
        return p

    def _parsear_producto(self, raw_data):
        return self._parsear_sku(raw_data, "General")
