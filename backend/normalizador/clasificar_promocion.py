"""
JUSTO Pricing 360 — Clasificador de Promociones
Determina el tipo de precio de cada producto capturado.
Orden de prioridad: SIN_STOCK > SIN_PRECIO > PROMO_CONDICIONAL >
                    PRECIO_FIDELIDAD > OFERTA > REGULAR
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Patrones compilados para performance
PATRONES = {
    "SIN_STOCK": re.compile(
        r"sin\s*stock|agotado|no\s*disponible|out\s*of\s*stock",
        re.IGNORECASE
    ),
    "PROMO_CONDICIONAL": re.compile(
        r"(\d+)\s*[xX×]\s*(\d+)"           # 2x1, 3x2, etc.
        r"|segunda\s*unidad"
        r"|segunda\s*al\s*\d+"
        r"|llevando\s*\d+"
        r"|comprando\s*\d+"
        r"|pack\s*de\s*\d+"
        r"|\d+\s*und[s]?\s*por"
        r"|segunda\s*gratis"
        r"|en\s*la\s*segunda"
        r"|(\d+)%\s*en\s*la\s*segunda",
        re.IGNORECASE
    ),
    "PRECIO_FIDELIDAD": re.compile(
        r"club\s*(dia|coto|carrefour|jumbo|vea|changomas|chango)"
        r"|tarjeta\s*(dia|coto|carrefour|jumbo|visa|mastercard|naranja|galicia)"
        r"|precio\s*(socio|club|member|miembro)"
        r"|membresia|membresía"
        r"|beneficio\s*(tarjeta|club)"
        r"|con\s*tarjeta"
        r"|descuento\s*(tarjeta|club)",
        re.IGNORECASE
    ),
}


def clasificar_tipo_promocion(
    precio_actual: Optional[float],
    precio_regular: Optional[float],
    precio_oferta: Optional[float],
    texto_promocion: Optional[str],
    disponibilidad: bool = True,
) -> str:
    """
    Clasifica el tipo de precio según la lógica de negocio de JUSTO.

    Retorna uno de:
        REGULAR | OFERTA | PROMO_CONDICIONAL | PRECIO_FIDELIDAD |
        SIN_PRECIO | SIN_STOCK
    """
    texto = (texto_promocion or "").strip()

    # 1. Sin stock — máxima prioridad
    if not disponibilidad:
        return "SIN_STOCK"
    if texto and PATRONES["SIN_STOCK"].search(texto):
        return "SIN_STOCK"

    # 2. Sin precio
    if precio_actual is None and precio_regular is None:
        return "SIN_PRECIO"

    # 3. Promo condicional (requiere acción del comprador para obtener el precio)
    if texto and PATRONES["PROMO_CONDICIONAL"].search(texto):
        return "PROMO_CONDICIONAL"

    # 4. Precio fidelidad (club, tarjeta, membresía)
    if texto and PATRONES["PRECIO_FIDELIDAD"].search(texto):
        return "PRECIO_FIDELIDAD"

    # 5. Oferta (precio actual menor al regular/tachado)
    if (
        precio_regular is not None
        and precio_actual is not None
        and precio_actual < precio_regular * 0.99  # 1% de tolerancia por redondeo
    ):
        return "OFERTA"

    if precio_oferta is not None and precio_regular is not None:
        if precio_oferta < precio_regular * 0.99:
            return "OFERTA"

    # 6. Regular — precio normal sin promoción
    return "REGULAR"


def extraer_descuento_porcentual(
    precio_actual: Optional[float],
    precio_regular: Optional[float],
) -> Optional[float]:
    """
    Calcula el % de descuento entre precio regular y precio actual.
    Útil para filtrar y ordenar ofertas en el dashboard.
    """
    if not precio_regular or not precio_actual:
        return None
    if precio_regular <= 0:
        return None
    descuento = (precio_regular - precio_actual) / precio_regular * 100
    return round(descuento, 1) if descuento > 0 else None


def normalizar_texto_promo(texto: Optional[str]) -> Optional[str]:
    """
    Limpia el texto de promoción para estandarizarlo.
    Elimina espacios múltiples, saltos de línea, caracteres raros.
    """
    if not texto:
        return None
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"[^\w\s%$.,xXxX×°+\-–]", "", texto)
    return texto if texto else None
