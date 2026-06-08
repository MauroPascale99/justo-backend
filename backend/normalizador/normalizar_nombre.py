"""Normalización universal de productos para JUSTO Pricing."""

import re
from typing import Optional, Tuple
from unidecode import unidecode
from slugify import slugify

STOPWORDS_PRODUCTO = {
    "de", "el", "la", "los", "las", "un", "una", "del", "al", "para", "con", "sin",
    "por", "en", "y", "e", "o", "u", "x", "pack", "paquete", "envase", "frasco",
    "botella", "bolsa", "caja", "sobre", "sachet", "bidon", "bidón", "garrafa",
    "limpieza", "detergente", "limpiador", "crema", "agua", "jabon", "jabón", "shampoo",
    "galletitas", "snacks", "vino", "remera", "campera", "silla", "helado",
}


def _norm(txt: str) -> str:
    return unidecode(str(txt or "")).strip().lower()


def normalizar_nombre(nombre_original: str) -> str:
    if not nombre_original:
        return ""
    nombre = str(nombre_original).strip()
    reemplazos = {"Ã¡":"á","Ã©":"é","Ã­":"í","Ã³":"ó","Ãº":"ú","Ã±":"ñ"}
    for a, b in reemplazos.items():
        nombre = nombre.replace(a, b)
    nombre = re.sub(r"\s+", " ", nombre).strip()
    palabras = []
    for p in nombre.split():
        if p.isupper() and len(p) <= 5:
            palabras.append(p)
        else:
            palabras.append(p.capitalize())
    return " ".join(palabras)


def generar_slug(nombre_limpio: str, retailer: str = "") -> str:
    return slugify(f"{nombre_limpio} {retailer}".strip(), separator="-", lowercase=True)


def marca_en_lista(nombre_producto: str, marcas_conocidas: list) -> Optional[str]:
    if not nombre_producto:
        return None
    nombre_norm = f" {_norm(nombre_producto)} "
    for marca in sorted(marcas_conocidas or [], key=lambda x: len(str(x)), reverse=True):
        m_norm = _norm(marca)
        if not m_norm:
            continue
        patron = r"(?<![a-z0-9])" + re.escape(m_norm) + r"(?![a-z0-9])"
        if re.search(patron, nombre_norm):
            return str(marca).strip()
    return None


def validar_marca_detectada(marca: Optional[str], retailer: str, config: dict) -> Optional[str]:
    if not marca:
        return None
    marca_txt = str(marca).strip()
    if not marca_txt or marca_txt.isdigit():
        return None
    marca_norm = _norm(marca_txt)
    if marca_norm in STOPWORDS_PRODUCTO:
        return None

    marcas_propias = config.get("normalizacion", {}).get("marcas_propias_retailer", {})
    retailer_norm = _norm(retailer)
    for ret, marcas in marcas_propias.items():
        for m in marcas:
            if marca_norm == _norm(m) and retailer_norm != _norm(ret):
                # Ej: "Día" en Coto suele ser palabra común, no marca propia.
                return None
    return marca_txt


def extraer_marca(
    nombre_producto: str,
    marcas_conocidas: list,
    marca_original: Optional[str] = None,
    retailer: str = "",
    config: Optional[dict] = None,
) -> Optional[str]:
    """Extrae marca en modo conservador.

    Prioridad:
    1. marca estructurada de la fuente,
    2. whitelist universal,
    3. vacío. Nunca toma automáticamente la primera palabra.
    """
    config = config or {}
    if marca_original:
        validada = validar_marca_detectada(marca_original, retailer, config)
        if validada:
            return validada
    por_lista = marca_en_lista(nombre_producto, marcas_conocidas)
    return validar_marca_detectada(por_lista, retailer, config)


def clasificar_tipo_marca(marca: Optional[str], retailer: str, config: dict) -> str:
    if not marca:
        return "sin_marca"
    marca_norm = _norm(marca)
    retailer_norm = _norm(retailer)
    marcas_propias = config.get("normalizacion", {}).get("marcas_propias_retailer", {})
    for ret, marcas in marcas_propias.items():
        if retailer_norm == _norm(ret) and any(marca_norm == _norm(m) for m in marcas):
            return "marca_propia"
    return "marca_fabricante"


PATRONES_CONTENIDO = [
    (re.compile(r"(\d+[.,]?\d*)\s*(litros?|lts?|lt|l)\b", re.I), "l"),
    (re.compile(r"(\d+[.,]?\d*)\s*(mililitros?|mls?|ml|cc)\b", re.I), "ml"),
    (re.compile(r"(\d+[.,]?\d*)\s*(kilos?|kgs?|kg|k)\b", re.I), "kg"),
    (re.compile(r"(\d+[.,]?\d*)\s*(gramos?|grs?|gr|g)\b", re.I), "g"),
    (re.compile(r"(?:x|\s)(\d+)\s*(unidades?|uds?|ud|un|u)\b", re.I), "un"),
    (re.compile(r"(\d+)\s*(rollos?)\b", re.I), "rollos"),
    (re.compile(r"(\d+)\s*(hojas?)\b", re.I), "hojas"),
]


def extraer_contenido(nombre_producto: str) -> Tuple[Optional[float], Optional[str]]:
    if not nombre_producto:
        return None, None
    for patron, unidad in PATRONES_CONTENIDO:
        m = patron.search(nombre_producto)
        if m:
            try:
                valor = float(m.group(1).replace(",", "."))
                if unidad == "ml" and valor >= 1000:
                    return round(valor / 1000, 3), "l"
                if unidad == "g" and valor >= 1000:
                    return round(valor / 1000, 3), "kg"
                return valor, unidad
            except Exception:
                pass
    return None, None


def extraer_formato(nombre_producto: str) -> Optional[str]:
    if not nombre_producto:
        return None
    formatos = {
        "liquido": r"\bl[ií]quido\b|\bliquid[oa]\b",
        "crema": r"\bcrema\b",
        "gel": r"\bgel\b",
        "polvo": r"\bpolvo\b|\ben polvo\b",
        "aerosol": r"\baerosol\b|\bspray\b",
        "pastilla": r"\bpastilla[s]?\b|\btableta[s]?\b",
        "barra": r"\bbarra[s]?\b",
        "toallita": r"\btoallita[s]?\b|\bpa[nñ]o[s]?\b",
    }
    for formato, patron in formatos.items():
        if re.search(patron, nombre_producto, re.I):
            return formato
    return None
