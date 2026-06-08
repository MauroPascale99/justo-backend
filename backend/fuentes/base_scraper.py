"""
JUSTO Pricing 360 — Base Scraper Universal
Incluye rate limiting, requests con reintentos, cache en memoria y estructura común de producto.
"""

import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import requests
from cachetools import TTLCache
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential, before_sleep_log

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


class ProductoCapturado:
    """Estructura universal devuelta por todos los scrapers."""

    def __init__(self):
        self.fecha_captura: str = date.today().isoformat()
        self.hora_captura: str = datetime.now().strftime("%H:%M:%S")
        self.fuente: str = ""
        self.retailer: str = ""
        self.categoria: str = ""
        self.subcategoria: str = ""
        self.nombre_producto_original: str = ""
        self.url_producto: Optional[str] = None
        self.url_imagen: Optional[str] = None
        self.ean: Optional[str] = None
        self.marca_original: Optional[str] = None
        self.tipo_marca: Optional[str] = None
        self.precio_actual: Optional[float] = None
        self.precio_regular: Optional[float] = None
        self.precio_oferta: Optional[float] = None
        self.precio_por_unidad: Optional[float] = None
        self.unidad_precio: Optional[str] = None
        self.tipo_promocion: str = "REGULAR"
        self.texto_promocion: Optional[str] = None
        self.disponibilidad: bool = True
        self.estado_captura: str = "ok"
        self.error_detalle: Optional[str] = None
        self.score_confianza_dato: float = 0.0
        self.hash_captura: str = ""

    def calcular_hash(self) -> str:
        campos = "|".join([
            str(self.retailer),
            str(self.url_producto or self.nombre_producto_original),
            str(self.precio_actual),
            str(self.precio_regular),
            str(self.precio_oferta),
            str(self.tipo_promocion),
            str(self.fecha_captura),
        ])
        self.hash_captura = hashlib.sha256(campos.encode("utf-8")).hexdigest()
        return self.hash_captura

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


class BaseScraper(ABC):
    def __init__(self, config_fuente: dict, config_captura: dict):
        self.config = config_fuente
        self.config_captura = config_captura
        self.retailer = config_fuente["retailer"]
        self.nombre = config_fuente["nombre"]
        self.url_base = config_fuente.get("url_base", "").rstrip("/")
        self.delay = config_captura.get("delay_entre_requests", 2.0)
        self.timeout = config_captura.get("timeout_request", 20)
        ttl = config_captura.get("ttl_cache_minutos", 60) * 60
        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=ttl)
        self.session = requests.Session()
        self.session.headers.update(self._headers_base())
        for k, v in config_fuente.get("headers_extra", {}).items():
            self.session.headers[k] = v
        self.stats = {"total": 0, "exitosos": 0, "errores": 0}
        logger.info("[%s] Scraper inicializado", self.nombre)

    def _headers_base(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.7",
            "Connection": "keep-alive",
            "DNT": "1",
        }

    def _esperar(self, delay_override: Optional[float] = None):
        delay = delay_override if delay_override is not None else self.delay
        time.sleep(delay + random.uniform(0.2, 0.7))

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=20),
        retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> requests.Response:
        cache_key = f"{url}|{params}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        max_intentos = 8

        for intento in range(1, max_intentos + 1):
            resp = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
                headers=headers,
                allow_redirects=True
            )

            if resp.status_code in (429, 503):
                espera = min(45 * intento, 240)
                logger.warning(
                    "[%s] HTTP %s. Intento %s/%s. Pausa responsable de %ss y reintento misma URL.",
                    self.retailer,
                    resp.status_code,
                    intento,
                    max_intentos,
                    espera
                )
                time.sleep(espera)
                continue

            if resp.status_code in (500, 502, 504):
                espera = min(30 * intento, 180)
                logger.warning(
                    "[%s] HTTP %s. Intento %s/%s. Pausa de %ss y reintento.",
                    self.retailer,
                    resp.status_code,
                    intento,
                    max_intentos,
                    espera
                )
                time.sleep(espera)
                continue

            if resp.status_code == 403:
                logger.error("[%s] HTTP 403 en %s. Activar fallback/manual para esta fuente.", self.retailer, url[:100])

            resp.raise_for_status()
            self._cache[cache_key] = resp
            return resp

        raise RuntimeError(f"[{self.retailer}] No se pudo obtener respuesta luego de {max_intentos} intentos: {url}")

    def _get_json(self, url: str, params: Optional[dict] = None, headers: Optional[dict] = None) -> Optional[Any]:
        try:
            return self._get(url, params=params, headers=headers).json()
        except RuntimeError as e:
            logger.error("[%s] Error crítico obteniendo JSON: %s", self.retailer, e)
            raise
        except Exception as e:
            logger.error("[%s] Error parseando JSON: %s", self.retailer, e)
            return None

    def limpiar_precio(self, texto: Any) -> Optional[float]:
        if texto is None:
            return None
        if isinstance(texto, (int, float)):
            return float(texto)
        s = str(texto).strip()
        for char in ["$", "ARS", "€", "£", " ", "\xa0", "\n"]:
            s = s.replace(char, "")
        if not s or s in {"-", "–"}:
            return None
        try:
            if "," in s and "." in s:
                s = s.replace(".", "").replace(",", ".")
            elif "," in s:
                s = s.replace(",", ".")
            elif "." in s:
                partes = s.split(".")
                if len(partes) == 2 and len(partes[1]) == 3:
                    s = s.replace(".", "")
            return round(float(s), 2)
        except Exception:
            return None

    @abstractmethod
    def capturar_categoria(self, categoria_config: dict) -> List[ProductoCapturado]:
        pass

    @abstractmethod
    def _parsear_producto(self, raw_data: Any) -> Optional[ProductoCapturado]:
        pass

    def ejecutar(self, max_productos: int = 50000) -> List[ProductoCapturado]:
        """Ejecuta la captura respetando max_productos también dentro de cada categoría.

        Antes el límite se aplicaba recién al final de cada categoría. En Coto,
        por ejemplo, Almacén tiene más de 5.000 productos; si se pedía --max 1000
        igual recorría toda la categoría. Ahora se informa a cada scraper cuántos
        productos faltan capturar y se corta antes.
        """
        productos: List[ProductoCapturado] = []
        categorias = self.config.get("categorias", []) or self.config.get("categorias_limpieza", [])
        logger.info("[%s] Iniciando captura universal: %s categorías | límite corrida: %s", self.nombre, len(categorias), max_productos)

        for idx, cat in enumerate(categorias, start=1):
            restante = max_productos - len(productos)
            if restante <= 0:
                logger.info("[%s] Límite de productos alcanzado: %s", self.nombre, len(productos))
                break

            try:
                cat_runtime = dict(cat)
                cat_runtime["__max_productos_categoria"] = restante
                logger.info(
                    "[%s] Categoría %s/%s: %s | acumulado: %s | restante: %s",
                    self.nombre, idx, len(categorias), cat.get("nombre"), len(productos), restante
                )
                capturados = self.capturar_categoria(cat_runtime)
                if len(capturados) > restante:
                    capturados = capturados[:restante]

                productos.extend(capturados)
                self.stats["exitosos"] += len(capturados)
                self.stats["total"] += len(capturados)
                logger.info(
                    "[%s] Categoría terminada: %s | capturados categoría: %s | acumulado total: %s",
                    self.nombre, cat.get("nombre"), len(capturados), len(productos)
                )
            except Exception as e:
                self.stats["errores"] += 1
                logger.exception("[%s] Error en categoría %s: %s", self.nombre, cat.get("nombre"), e)

            if idx < len(categorias) and len(productos) < max_productos:
                self._esperar(self.config_captura.get("delay_entre_paginas", 1.2))

        logger.info("[%s] Captura finalizada: %s productos", self.nombre, len(productos))
        return productos[:max_productos]
