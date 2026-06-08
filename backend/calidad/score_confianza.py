"""
JUSTO Pricing 360 — Score de confianza del dato
Puntúa cada captura entre 0.0 y 1.0 según completitud y coherencia.
Permite filtrar datos dudosos en el dashboard y reportes.
"""

from typing import Optional
from fuentes.base_scraper import ProductoCapturado


def calcular_score(producto: ProductoCapturado) -> float:
    """
    Score 0.0 a 1.0. Suma ponderada de criterios de calidad.
    Un score >= 0.7 es confiable. < 0.4 requiere revisión humana.
    """
    score = 0.0
    max_score = 0.0

    # ── 1. Precio disponible y coherente (peso: 30%) ────────────────────
    max_score += 0.30
    if producto.precio_actual is not None and producto.precio_actual > 0:
        score += 0.30
        # Penalizar si el precio parece anómalo (< $1 o > $1.000.000)
        if producto.precio_actual < 1 or producto.precio_actual > 1_000_000:
            score -= 0.15

    # ── 2. Nombre del producto presente (peso: 20%) ─────────────────────
    max_score += 0.20
    if producto.nombre_producto_original and len(producto.nombre_producto_original) > 3:
        score += 0.20
        if len(producto.nombre_producto_original) < 5:
            score -= 0.10  # Nombre muy corto, sospechoso

    # ── 3. URL del producto (peso: 15%) ──────────────────────────────────
    max_score += 0.15
    if producto.url_producto and producto.url_producto.startswith("http"):
        score += 0.15

    # ── 4. EAN disponible (peso: 15%) ────────────────────────────────────
    max_score += 0.15
    if producto.ean and str(producto.ean).isdigit():
        ean_str = str(producto.ean)
        # EAN válido: 8, 12, 13 o 14 dígitos
        if len(ean_str) in [8, 12, 13, 14]:
            score += 0.15
        else:
            score += 0.05  # EAN de longitud inusual, puntaje parcial

    # ── 5. Coherencia precio regular vs oferta (peso: 10%) ───────────────
    max_score += 0.10
    if producto.precio_regular is not None and producto.precio_oferta is not None:
        if producto.precio_oferta <= producto.precio_regular:
            score += 0.10
        else:
            score -= 0.10  # Precio oferta > regular: dato inconsistente

    elif producto.precio_regular is not None:
        score += 0.05  # Al menos hay precio regular

    # ── 6. Imagen disponible (peso: 5%) ──────────────────────────────────
    max_score += 0.05
    if producto.url_imagen and producto.url_imagen.startswith("http"):
        score += 0.05

    # ── 7. Tipo de promoción clasificado (peso: 5%) ───────────────────────
    max_score += 0.05
    tipos_validos = {"REGULAR", "OFERTA", "PROMO_CONDICIONAL", "PRECIO_FIDELIDAD", "SIN_PRECIO", "SIN_STOCK"}
    if producto.tipo_promocion in tipos_validos:
        score += 0.05

    # Normalizar a [0.0, 1.0]
    score_final = max(0.0, min(1.0, score / max_score if max_score > 0 else 0.0))
    return round(score_final, 3)


def nivel_confianza(score: float) -> str:
    """Etiqueta legible del score para reportes y auditoría."""
    if score >= 0.85:
        return "ALTO"
    elif score >= 0.65:
        return "MEDIO"
    elif score >= 0.40:
        return "BAJO"
    else:
        return "REVISAR"
