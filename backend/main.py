"""JUSTO Pricing 360 — Capturador Universal.

Uso:
  python main.py --fuente coto --max 50000
  python main.py --fuente dia --max 10000
  python main.py --fuente changomas --max 10000
  python main.py --solo-exportar
"""

import argparse
import logging
from pathlib import Path
import pandas as pd
from normalizador.deduplicar_productos import deduplicar_productos
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
# Cargar .env de la raíz antes de cambiar el directorio de trabajo
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

import yaml
from rich.console import Console
from rich.table import Table

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from calidad.auditoria import AuditorCaptura
from calidad.score_confianza import calcular_score
from db.database import Database
from fuentes.changomas import ChangoMasScraper
from fuentes.coto import CotoScraper
from fuentes.dia import DiaScraper
from normalizador.clasificar_promocion import clasificar_tipo_promocion, normalizar_texto_promo
from normalizador.normalizar_nombre import (
    clasificar_tipo_marca,
    extraer_contenido,
    extraer_formato,
    extraer_marca,
    normalizar_nombre,
)

console = Console()
SCRAPERS = {
    "coto": CotoScraper,
    "dia": DiaScraper,
    "changomas": ChangoMasScraper,
    "carrefour": ChangoMasScraper,
    "jumbo": ChangoMasScraper,
    "disco": ChangoMasScraper,
    "vea": ChangoMasScraper,
}


def cargar_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def configurar_logging(config: dict):
    os.makedirs(config.get("directorio", "logs"), exist_ok=True)
    nivel = getattr(logging, config.get("nivel", "INFO").upper(), logging.INFO)
    fecha = datetime.now().strftime("%Y%m%d")
    log_path = os.path.join(config.get("directorio", "logs"), f"justo_{fecha}.log")
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s | %(levelname)-8s | %(name)-22s | %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler()],
    )
    return logging.getLogger("justo.main")


def guardar_productos(db: Database, productos: list, config: dict) -> list:
    """Normaliza y guarda productos/capturas en una transacción por lotes.

    La versión anterior abría una conexión/commit por cada upsert y por cada captura.
    Con 31.000+ productos eso podía parecer colgado durante muchísimo tiempo,
    especialmente si la carpeta estaba dentro de OneDrive.
    """
    marcas_conocidas = config.get("normalizacion", {}).get("marcas_conocidas", [])
    registros = []
    log = logging.getLogger("justo.guardar")

    if not productos:
        log.info("No hay productos para guardar.")
        return registros

    total = len(productos)
    batch_size = int(config.get("db", {}).get("batch_size", 1000) or 1000)
    fuentes_cache = db.obtener_fuentes_map()

    log.info("Guardando %s productos/capturas en SQLite por lotes de %s...", total, batch_size)

    conn = db._get_connection()
    try:
        cur = db.get_cursor_for_connection(conn)
        for idx, prod in enumerate(productos, start=1):
            try:
                fuente = fuentes_cache.get(prod.retailer)
                if not fuente:
                    log.warning("Fuente no encontrada en DB: %s", prod.retailer)
                    continue

                prod.tipo_promocion = clasificar_tipo_promocion(
                    precio_actual=prod.precio_actual,
                    precio_regular=prod.precio_regular,
                    precio_oferta=prod.precio_oferta,
                    texto_promocion=prod.texto_promocion,
                    disponibilidad=prod.disponibilidad,
                )
                prod.texto_promocion = normalizar_texto_promo(prod.texto_promocion)
                nombre_limpio = normalizar_nombre(prod.nombre_producto_original)
                marca = extraer_marca(
                    prod.nombre_producto_original,
                    marcas_conocidas,
                    marca_original=prod.marca_original,
                    retailer=prod.retailer,
                    config=config,
                )
                tipo_marca = clasificar_tipo_marca(marca, prod.retailer, config)
                prod.tipo_marca = tipo_marca
                contenido, unidad = extraer_contenido(prod.nombre_producto_original)
                formato = extraer_formato(prod.nombre_producto_original)
                prod.score_confianza_dato = calcular_score(prod)

                id_prod = db.upsert_producto_fuente_cursor(cur, {
                    "id_fuente": fuente["id_fuente"],
                    "retailer": prod.retailer,
                    "nombre_original": prod.nombre_producto_original,
                    "url_producto": prod.url_producto,
                    "url_imagen": prod.url_imagen,
                    "categoria_original": prod.categoria,
                    "subcategoria_original": prod.subcategoria or None,
                    "ean_detectado": prod.ean,
                    "marca_original": marca,
                    "tipo_marca": tipo_marca,
                })
                if id_prod < 0:
                    continue

                db.insertar_captura_cursor(cur, {
                    "id_producto_fuente": id_prod,
                    "fecha_captura": prod.fecha_captura,
                    "hora_captura": prod.hora_captura,
                    "precio_actual": prod.precio_actual,
                    "precio_regular": prod.precio_regular,
                    "precio_oferta": prod.precio_oferta,
                    "precio_por_unidad": prod.precio_por_unidad,
                    "unidad_precio": prod.unidad_precio,
                    "tipo_promocion": prod.tipo_promocion,
                    "texto_promocion": prod.texto_promocion,
                    "disponibilidad": int(prod.disponibilidad),
                    "hash_captura": prod.hash_captura,
                    "score_confianza_dato": prod.score_confianza_dato,
                    "estado_captura": prod.estado_captura,
                    "error_detalle": prod.error_detalle,
                })

                registros.append({
                    "fecha_captura": prod.fecha_captura,
                    "hora_captura": prod.hora_captura,
                    "retailer": prod.retailer,
                    "categoria": prod.categoria,
                    "subcategoria": prod.subcategoria,
                    "nombre_producto_original": prod.nombre_producto_original,
                    "nombre_producto_limpio": nombre_limpio,
                    "marca": marca,
                    "tipo_marca": tipo_marca,
                    "marca_original_fuente": prod.marca_original,
                    "ean": prod.ean,
                    "contenido": contenido,
                    "unidad_medida": unidad,
                    "formato": formato,
                    "precio_actual": prod.precio_actual,
                    "precio_regular": prod.precio_regular,
                    "precio_oferta": prod.precio_oferta,
                    "precio_por_unidad": prod.precio_por_unidad,
                    "unidad_precio": prod.unidad_precio,
                    "tipo_promocion": prod.tipo_promocion,
                    "texto_promocion": prod.texto_promocion,
                    "disponibilidad": prod.disponibilidad,
                    "url_producto": prod.url_producto,
                    "url_imagen": prod.url_imagen,
                    "score_confianza_dato": prod.score_confianza_dato,
                    "estado_captura": prod.estado_captura,
                    "hash_captura": prod.hash_captura,
                })

                if idx % batch_size == 0:
                    conn.commit()
                    log.info("Guardado parcial: %s/%s productos procesados | registros salida: %s", idx, total, len(registros))

            except Exception as e:
                log.exception("Error guardando producto %s: %s", getattr(prod, "nombre_producto_original", "?"), e)

        conn.commit()
        log.info("Guardado finalizado: %s productos procesados | registros salida: %s", total, len(registros))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return registros

def fuentes_a_ejecutar(config: dict, fuente: str | None) -> dict:
    fuentes_config = config.get("fuentes", {})
    if fuente:
        if fuente not in fuentes_config:
            raise ValueError(f"Fuente no configurada: {fuente}")
        return {fuente: fuentes_config[fuente]}
    return {k: v for k, v in fuentes_config.items() if v.get("habilitada", False)}


def imprimir_resumen(registros: list):
    if not registros:
        console.print("[yellow]Sin registros generados.[/yellow]")
        return
    from collections import Counter
    por_retailer = Counter(r["retailer"] for r in registros)
    table = Table(title="Resumen JUSTO Pricing Universal")
    table.add_column("Retailer")
    table.add_column("Productos", justify="right")
    for retailer, total in por_retailer.items():
        table.add_row(retailer, str(total))
    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="JUSTO Pricing 360 — Capturador Universal")
    parser.add_argument("--fuente", type=str, choices=list(SCRAPERS.keys()), help="Ejecutar una fuente puntual")
    parser.add_argument("--max", type=int, default=None, help="Máximo de productos por fuente")
    parser.add_argument("--config", type=str, default="config.yaml", help="Archivo de configuración")
    parser.add_argument("--solo-exportar", action="store_true", help="Exporta la DB actual sin capturar")
    args = parser.parse_args()

    config = cargar_config(args.config)
    log = configurar_logging(config.get("logs", {}))
    log.info("JUSTO Pricing Universal iniciado")
    db = Database(config["db"])
    db.inicializar("db/schema.sql")
    auditor = AuditorCaptura(config)

    if args.solo_exportar:
        df = db.exportar_capturas_df()
        registros = df.to_dict(orient="records")
        auditor.exportar_csv(registros, config["outputs"]["normalizado_csv"], modo="w")
        if config["outputs"].get("exportar_excel"):
            auditor.exportar_excel_archivo(registros, "JUSTO_Pricing_export.xlsx")
        console.print("[green]Exportación completada.[/green]")
        return

    max_productos = args.max or config.get("captura", {}).get("max_productos_por_corrida", 50000)
    todos = []

    for key, fuente_cfg in fuentes_a_ejecutar(config, args.fuente).items():
        scraper_cls = SCRAPERS[key]
        scraper = scraper_cls(fuente_cfg, config["captura"])
        inicio = datetime.now()
        productos = scraper.ejecutar(max_productos=max_productos)

        total_bruto = len(productos)
        log.info(
            "[%s] Captura bruta finalizada: %s registros. Iniciando deduplicación...",
            key,
            total_bruto,
        )

        productos, auditoria_duplicados = deduplicar_productos(productos)

        log.info(
            "[%s] Deduplicación finalizada: %s registros brutos -> %s productos únicos. Grupos duplicados detectados: %s.",
            key,
            total_bruto,
            len(productos),
            len(auditoria_duplicados),
        )

        if auditoria_duplicados:
            Path("outputs").mkdir(exist_ok=True)
            archivo_auditoria = f"outputs/auditoria_duplicados_{key}.csv"
            pd.DataFrame(auditoria_duplicados).to_csv(
                archivo_auditoria,
                index=False,
                encoding="utf-8-sig",
            )
            log.info("[%s] Auditoría de duplicados exportada: %s", key, archivo_auditoria)

        log.info("[%s] Iniciando guardado de productos únicos...", key)
        registros = guardar_productos(db, productos, config)
        log.info("[%s] Guardado terminado. Iniciando exportación CSV...", key)
        fecha = datetime.now().strftime("%Y%m%d")
        auditor.exportar_csv(registros, f"capturas_{key}_{fecha}.csv", modo="w")
        auditor.exportar_csv(registros, config["outputs"]["normalizado_csv"], modo="a")
        log.info("[%s] Exportación CSV terminada.", key)
        db.actualizar_ultima_captura(key)
        db.registrar_auditoria({
            "id_fuente": db.obtener_fuente(key)["id_fuente"] if db.obtener_fuente(key) else None,
            "retailer": key,
            "fecha_inicio": inicio.isoformat(),
            "fecha_fin": datetime.now().isoformat(),
            "duracion_segundos": (datetime.now() - inicio).total_seconds(),
            "total_productos": len(registros),
            "total_exitosos": len(registros),
            "total_errores": scraper.stats.get("errores", 0),
            "estado_corrida": "ok",
        })
        todos.extend(registros)
        delay_fuente = config.get("captura", {}).get("delay_entre_fuentes", 8)
        if not args.fuente:
            scraper._esperar(delay_fuente)

    if config["outputs"].get("exportar_excel") and todos:
        auditor.exportar_excel_archivo(todos, f"JUSTO_Pricing_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
    imprimir_resumen(todos)


if __name__ == "__main__":
    main()
