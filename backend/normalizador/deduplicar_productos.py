from collections import defaultdict
from typing import List, Tuple, Dict, Any


def _limpiar_texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def _normalizar_texto(valor):
    return (
        _limpiar_texto(valor)
        .lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )


def _crear_clave_producto(producto):
    """
    Criterio de deduplicación:
    1. retailer + url_producto
    2. retailer + ean
    3. retailer + nombre limpio/original + contenido + unidad
    """

    retailer = _normalizar_texto(getattr(producto, "retailer", ""))
    url = _normalizar_texto(getattr(producto, "url_producto", ""))
    ean = _normalizar_texto(getattr(producto, "ean", ""))

    nombre_limpio = _normalizar_texto(
        getattr(producto, "nombre_limpio", None)
        or getattr(producto, "nombre_original", "")
    )

    contenido = _normalizar_texto(getattr(producto, "contenido", ""))
    unidad = _normalizar_texto(getattr(producto, "unidad_medida", ""))

    if retailer and url:
        return f"{retailer}|url|{url}"

    if retailer and ean:
        return f"{retailer}|ean|{ean}"

    return f"{retailer}|nombre|{nombre_limpio}|{contenido}|{unidad}"


def _fusionar_productos(productos_duplicados):
    """
    Conserva el primer producto como principal y le agrega trazabilidad:
    - categorias_detectadas
    - subcategorias_detectadas
    - cantidad_apariciones
    """

    principal = productos_duplicados[0]

    categorias = []
    subcategorias = []

    for p in productos_duplicados:
        cat = _limpiar_texto(getattr(p, "categoria", ""))
        sub = _limpiar_texto(getattr(p, "subcategoria", ""))

        if cat and cat not in categorias:
            categorias.append(cat)

        if sub and sub not in subcategorias:
            subcategorias.append(sub)

    principal.categorias_detectadas = " | ".join(categorias)
    principal.subcategorias_detectadas = " | ".join(subcategorias)
    principal.cantidad_apariciones = len(productos_duplicados)

    return principal


def deduplicar_productos(productos: List[Any]) -> Tuple[List[Any], List[Dict[str, Any]]]:
    """
    Devuelve:
    - productos_unicos: lista limpia para guardar/exportar
    - auditoria: detalle técnico de duplicados detectados
    """

    grupos = defaultdict(list)

    for producto in productos:
        clave = _crear_clave_producto(producto)
        grupos[clave].append(producto)

    productos_unicos = []
    auditoria = []

    for clave, items in grupos.items():
        producto_final = _fusionar_productos(items)
        productos_unicos.append(producto_final)

        if len(items) > 1:
            auditoria.append({
                "clave_deduplicacion": clave,
                "cantidad_apariciones": len(items),
                "retailer": getattr(producto_final, "retailer", None),
                "nombre_producto": getattr(producto_final, "nombre_original", None),
                "url_producto": getattr(producto_final, "url_producto", None),
                "ean": getattr(producto_final, "ean", None),
                "categorias_detectadas": getattr(producto_final, "categorias_detectadas", None),
                "subcategorias_detectadas": getattr(producto_final, "subcategorias_detectadas", None),
            })

    return productos_unicos, auditoria
