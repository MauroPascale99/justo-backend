"""
JUSTO Pricing 360 â€” AuditorÃ­a de capturas
Logging estructurado, exportaciÃ³n a CSV/Excel, detecciÃ³n de cambios.
"""

import os
import logging
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class AuditorCaptura:
    """Registra y exporta los resultados de cada corrida de captura."""

    def __init__(self, config: dict):
        self.config = config
        self.dir_outputs = config.get("outputs", {}).get("directorio", "outputs")
        self.exportar_excel = config.get("outputs", {}).get("exportar_excel", True)
        os.makedirs(self.dir_outputs, exist_ok=True)

    def exportar_csv(
        self,
        productos: List[Dict[str, Any]],
        nombre_archivo: str,
        modo: str = "a",  # "a" para append, "w" para sobreescribir
    ) -> str:
        """
        Exporta lista de productos a CSV.
        modo="a" acumula en el archivo existente (histÃ³rico).
        """
        if not productos:
            logger.warning("Sin productos para exportar.")
            return ""

        df = pd.DataFrame(productos)

        ruta = os.path.join(self.dir_outputs, nombre_archivo)
        escribir_header = not os.path.exists(ruta) or modo == "w"

        df.to_csv(ruta, mode=modo, header=escribir_header, index=False, encoding="utf-8-sig")
        logger.info(f"CSV exportado: {ruta} ({len(df)} registros)")
        return ruta

    def exportar_excel_archivo(
        self,
        productos: List[Dict[str, Any]],
        nombre_archivo: str = None,
    ) -> str:
        """
        Exporta a Excel con formato bÃ¡sico.
        Un archivo por fecha de captura.
        """
        if not productos:
            return ""

        if not nombre_archivo:
            fecha = datetime.now().strftime("%Y%m%d_%H%M")
            nombre_archivo = f"precios_limpieza_{fecha}.xlsx"

        ruta = os.path.join(self.dir_outputs, nombre_archivo)
        df = pd.DataFrame(productos)

        with pd.ExcelWriter(ruta, engine="openpyxl") as writer:
            # Hoja principal
            df.to_excel(writer, sheet_name="Capturas", index=False)

            # Hoja de resumen por retailer
            resumen = df.groupby("retailer").agg(
                total_productos=("nombre_producto_original", "count"),
                precio_promedio=("precio_actual", "mean"),
                con_oferta=("tipo_promocion", lambda x: (x == "OFERTA").sum()),
                sin_stock=("tipo_promocion", lambda x: (x == "SIN_STOCK").sum()),
                score_promedio=("score_confianza_dato", "mean"),
            ).reset_index()

            resumen["precio_promedio"] = resumen["precio_promedio"].round(2)
            resumen["score_promedio"] = resumen["score_promedio"].round(3)
            resumen.to_excel(writer, sheet_name="Resumen", index=False)

        logger.info(f"Excel exportado: {ruta}")
        return ruta

    def resumen_corrida(self, productos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Genera estadÃ­sticas de resumen de la corrida."""
        if not productos:
            return {}

        df = pd.DataFrame(productos)

        return {
            "total_productos": len(df),
            "por_retailer": df.groupby("retailer").size().to_dict(),
            "por_tipo_promo": df.groupby("tipo_promocion").size().to_dict(),
            "precio_promedio_global": round(df["precio_actual"].mean(), 2) if "precio_actual" in df else None,
            "score_promedio": round(df["score_confianza_dato"].mean(), 3) if "score_confianza_dato" in df else None,
            "con_ean": int(df["ean"].notna().sum()) if "ean" in df else 0,
            "sin_stock": int((df.get("tipo_promocion") == "SIN_STOCK").sum()),
            "errores": int((df.get("estado_captura") == "error").sum()),
        }

