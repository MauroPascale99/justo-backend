"""Capa de datos para JUSTO Pricing Universal.

Soporta dos backends según config['tipo']:
  - 'sqlite'   : base local para desarrollo (comportamiento original)
  - 'postgres' : Supabase en producción (nuevo)

La API pública es idéntica en ambos casos.
Ningún script externo necesita cambios.
"""

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Intentamos importar psycopg2. Si no está instalado y se usa SQLite, no importa.
try:
    import psycopg2
    import psycopg2.extras  # RealDictCursor
    _PSYCOPG2_OK = True
except ImportError:
    _PSYCOPG2_OK = False


class Database:
    """
    Uso con SQLite (desarrollo, sin cambios):
        db = Database({"tipo": "sqlite", "path": "db/justo_pricing.db"})

    Uso con Supabase/Postgres (producción):
        db = Database({"tipo": "postgres"})
        # Lee DATABASE_URL del entorno automáticamente.
        # O pasá la URL explícita:
        db = Database({"tipo": "postgres", "url": "postgresql://..."})
    """

    def __init__(self, config: dict):
        self.config = config
        self.db_type = config.get("tipo", "sqlite")

        if self.db_type == "sqlite":
            self.db_path = config.get("path", "db/justo_pricing.db")
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        elif self.db_type == "postgres":
            if not _PSYCOPG2_OK:
                raise ImportError(
                    "Instalá psycopg2 para usar Postgres:\n"
                    "  pip install psycopg2-binary"
                )
            # Prioridad: config['url'] → variable de entorno DATABASE_URL
            self._pg_url = config.get("url") or os.environ.get("DATABASE_URL")
            if not self._pg_url:
                raise ValueError(
                    "Para postgres necesitás DATABASE_URL en el entorno "
                    "o 'url' en el config."
                )
        else:
            raise ValueError(f"db.tipo no reconocido: {self.db_type!r}. "
                             "Usá 'sqlite' o 'postgres'.")

    # ──────────────────────────────────────────────
    # Conexiones internas
    # ──────────────────────────────────────────────

    def _get_connection(self):
        if self.db_type == "sqlite":
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            return conn
        else:
            conn = psycopg2.connect(self._pg_url)
            return conn

    def get_cursor_for_connection(self, conn):
        if self.db_type == "sqlite":
            return conn.cursor()
        else:
            return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    @contextmanager
    def get_cursor(self):
        conn = self._get_connection()
        try:
            if self.db_type == "sqlite":
                cur = conn.cursor()
            else:
                # RealDictCursor → cada fila se comporta como dict,
                # igual que sqlite3.Row
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ──────────────────────────────────────────────
    # Helpers de SQL: diferencias SQLite ↔ Postgres
    # ──────────────────────────────────────────────

    def _ph(self) -> str:
        """Placeholder: ? para SQLite, %s para Postgres."""
        return "?" if self.db_type == "sqlite" else "%s"

    def _now_sql(self) -> str:
        """Función NOW() según backend."""
        return "datetime('now')" if self.db_type == "sqlite" else "now()"

    def _params(self, *values):
        """Devuelve la lista de params tal cual (sin cambios, solo para claridad)."""
        return list(values)

    def _upsert_producto_sql(self) -> str:
        """
        INSERT … ON CONFLICT es compatible en SQLite >= 3.24 y Postgres >= 9.5.
        La sintaxis es idéntica, pero los placeholders difieren.
        """
        p = self._ph()
        now = self._now_sql()
        return f"""
            INSERT INTO productos_fuente
               (id_fuente, retailer, nombre_original, url_producto, url_imagen,
                categoria_original, subcategoria_original, ean_detectado, marca_original, tipo_marca)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            ON CONFLICT(id_fuente, url_producto)
            DO UPDATE SET
                nombre_original      = EXCLUDED.nombre_original,
                url_imagen           = EXCLUDED.url_imagen,
                categoria_original   = EXCLUDED.categoria_original,
                subcategoria_original= EXCLUDED.subcategoria_original,
                ean_detectado        = COALESCE(EXCLUDED.ean_detectado,  productos_fuente.ean_detectado),
                marca_original       = COALESCE(EXCLUDED.marca_original, productos_fuente.marca_original),
                tipo_marca           = COALESCE(EXCLUDED.tipo_marca,     productos_fuente.tipo_marca),
                ultima_vez_visto     = {now}
        """

    def _select_id_producto_sql(self) -> str:
        p = self._ph()
        return (
            f"SELECT id_producto_fuente FROM productos_fuente "
            f"WHERE id_fuente = {p} AND url_producto = {p}"
        )

    # ──────────────────────────────────────────────
    # API pública — IDÉNTICA al database.py original
    # ──────────────────────────────────────────────

    def inicializar(self, schema_path: str = "db/schema.sql"):
        """Solo aplica en SQLite. En Postgres el schema se crea con la migración SQL."""
        if self.db_type == "sqlite":
            with open(schema_path, "r", encoding="utf-8") as f:
                sql = f.read()
            with self._get_connection() as conn:
                conn.executescript(sql)
            self.migrar_columnas_universales()
            logger.info("Base SQLite inicializada: %s", self.db_path)
        else:
            logger.info("Postgres: schema ya aplicado vía migración SQL. "
                        "inicializar() no hace nada.")

    def migrar_columnas_universales(self):
        """Migraciones de columnas — solo relevante en SQLite."""
        if self.db_type != "sqlite":
            return
        with self.get_cursor() as cur:
            cur.execute("PRAGMA table_info(productos_fuente)")
            cols = {r[1] for r in cur.fetchall()}
            if "marca_original" not in cols:
                cur.execute("ALTER TABLE productos_fuente ADD COLUMN marca_original TEXT")
            if "tipo_marca" not in cols:
                cur.execute("ALTER TABLE productos_fuente ADD COLUMN tipo_marca TEXT")

    def obtener_fuente(self, retailer: str) -> Optional[Dict]:
        p = self._ph()
        with self.get_cursor() as cur:
            cur.execute(f"SELECT * FROM fuentes WHERE retailer = {p}", (retailer,))
            row = cur.fetchone()
            return dict(row) if row else None

    def actualizar_ultima_captura(self, retailer: str, estado: str = "activa"):
        p = self._ph()
        now = self._now_sql()
        with self.get_cursor() as cur:
            cur.execute(
                f"""UPDATE fuentes
                    SET ultima_captura = {now}, estado = {p},
                        total_capturas = total_capturas + 1
                    WHERE retailer = {p}""",
                (estado, retailer),
            )

    def upsert_producto_fuente(self, datos: Dict[str, Any]) -> int:
        with self.get_cursor() as cur:
            return self._upsert_producto_fuente_impl(cur, datos)

    def obtener_ultimo_precio(self, id_producto_fuente: int) -> Optional[Dict]:
        p = self._ph()
        with self.get_cursor() as cur:
            cur.execute(
                f"""SELECT precio_actual, tipo_promocion
                    FROM capturas_precio
                    WHERE id_producto_fuente = {p}
                    ORDER BY id_captura DESC LIMIT 1""",
                (id_producto_fuente,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def insertar_captura(self, datos: Dict[str, Any]) -> int:
        with self.get_cursor() as cur:
            return self._insertar_captura_impl(cur, datos)

    def obtener_fuentes_map(self) -> Dict[str, Dict]:
        """Devuelve todas las fuentes indexadas por retailer."""
        with self.get_cursor() as cur:
            cur.execute("SELECT * FROM fuentes")
            return {row["retailer"]: dict(row) for row in cur.fetchall()}

    def upsert_producto_fuente_cursor(self, cur, datos: Dict[str, Any]) -> int:
        """Upsert usando cursor ya abierto. Más rápido para cargas masivas."""
        return self._upsert_producto_fuente_impl(cur, datos)

    def insertar_captura_cursor(self, cur, datos: Dict[str, Any]) -> int:
        """Inserta captura usando cursor ya abierto."""
        return self._insertar_captura_impl(cur, datos)

    def registrar_auditoria(self, datos: Dict[str, Any]):
        p = self._ph()
        with self.get_cursor() as cur:
            cur.execute(
                f"""INSERT INTO auditoria_capturas
                    (id_fuente, retailer, fecha_inicio, fecha_fin, duracion_segundos,
                     total_productos, total_exitosos, total_errores, total_cambios_precio,
                     estado_corrida, detalle)
                    VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})""",
                (
                    datos.get("id_fuente"),    datos.get("retailer"),
                    datos.get("fecha_inicio"), datos.get("fecha_fin"),
                    datos.get("duracion_segundos"),
                    datos.get("total_productos", 0), datos.get("total_exitosos", 0),
                    datos.get("total_errores", 0),   datos.get("total_cambios_precio", 0),
                    datos.get("estado_corrida", "ok"), datos.get("detalle"),
                ),
            )

    def exportar_capturas_df(self, retailer: Optional[str] = None, fecha: Optional[str] = None):
        import pandas as pd
        p = self._ph()
        query = """
            SELECT
                cp.fecha_captura, cp.hora_captura, pf.retailer,
                pf.categoria_original AS categoria,
                pf.subcategoria_original AS subcategoria,
                pf.nombre_original AS nombre_producto_original,
                pf.marca_original AS marca, pf.tipo_marca,
                pf.ean_detectado AS ean,
                cp.precio_actual, cp.precio_regular, cp.precio_oferta,
                cp.precio_por_unidad, cp.unidad_precio,
                cp.tipo_promocion, cp.texto_promocion, cp.disponibilidad,
                pf.url_producto, pf.url_imagen,
                cp.score_confianza_dato, cp.estado_captura, cp.es_cambio_precio
            FROM capturas_precio cp
            JOIN productos_fuente pf ON pf.id_producto_fuente = cp.id_producto_fuente
            WHERE 1=1
        """
        params = []
        if retailer:
            query += f" AND pf.retailer = {p}"
            params.append(retailer)
        if fecha:
            query += f" AND cp.fecha_captura = {p}"
            params.append(fecha)
        query += " ORDER BY cp.fecha_captura DESC, pf.retailer, pf.nombre_original"

        conn = self._get_connection()
        df = pd.read_sql_query(query, conn, params=params or None)
        conn.close()
        return df

    # ──────────────────────────────────────────────
    # Implementaciones internas (usan cursor externo)
    # ──────────────────────────────────────────────

    def _upsert_producto_fuente_impl(self, cur, datos: Dict[str, Any]) -> int:
        cur.execute(
            self._upsert_producto_sql(),
            (
                datos["id_fuente"],    datos["retailer"],    datos["nombre_original"],
                datos.get("url_producto"), datos.get("url_imagen"),
                datos.get("categoria_original"), datos.get("subcategoria_original"),
                datos.get("ean_detectado"),  datos.get("marca_original"), datos.get("tipo_marca"),
            ),
        )
        cur.execute(
            self._select_id_producto_sql(),
            (datos["id_fuente"], datos.get("url_producto")),
        )
        row = cur.fetchone()
        return int(row["id_producto_fuente"]) if row else -1

    def _insertar_captura_impl(self, cur, datos: Dict[str, Any]) -> int:
        p = self._ph()

        # Evitar duplicados por hash
        cur.execute(
            f"SELECT id_captura FROM capturas_precio WHERE hash_captura = {p} LIMIT 1",
            (datos["hash_captura"],),
        )
        if cur.fetchone():
            return -1

        # Detectar cambio de precio
        cur.execute(
            f"""SELECT precio_actual FROM capturas_precio
                WHERE id_producto_fuente = {p}
                ORDER BY id_captura DESC LIMIT 1""",
            (datos["id_producto_fuente"],),
        )
        row = cur.fetchone()
        es_cambio = bool(row and row["precio_actual"] != datos.get("precio_actual"))

        cur.execute(
            f"""INSERT INTO capturas_precio
                (id_producto_fuente, fecha_captura, hora_captura,
                 precio_actual, precio_regular, precio_oferta,
                 precio_por_unidad, unidad_precio, tipo_promocion, texto_promocion,
                 disponibilidad, hash_captura, score_confianza_dato,
                 estado_captura, error_detalle, es_cambio_precio)
                VALUES ({p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p},{p})""",
            (
                datos["id_producto_fuente"], datos["fecha_captura"], datos["hora_captura"],
                datos.get("precio_actual"),  datos.get("precio_regular"), datos.get("precio_oferta"),
                datos.get("precio_por_unidad"), datos.get("unidad_precio"),
                datos.get("tipo_promocion"),    datos.get("texto_promocion"),
                bool(datos.get("disponibilidad", True)), datos["hash_captura"],
                datos.get("score_confianza_dato", 0.0), datos.get("estado_captura", "ok"),
                datos.get("error_detalle"), es_cambio,
            ),
        )
        # Postgres no tiene lastrowid → usamos RETURNING
        if self.db_type == "postgres":
            # El INSERT anterior no tiene RETURNING, rehacemos con fetchone
            # En cargas masivas esto es aceptable; para optimizar se puede
            # agregar RETURNING id_captura al INSERT.
            cur.execute(
                f"SELECT id_captura FROM capturas_precio WHERE hash_captura = {p}",
                (datos["hash_captura"],),
            )
            row = cur.fetchone()
            return int(row["id_captura"]) if row else -1
        else:
            return int(cur.lastrowid)
