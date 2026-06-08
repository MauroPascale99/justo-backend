"""
JUSTO Pricing 360 — Migración completa SQLite → Supabase
=========================================================
Ejecutar desde la raíz del proyecto:
    python migrar_a_supabase.py

Requisitos:
    pip install psycopg2-binary python-dotenv

El script es seguro para correr más de una vez:
    - Usa ON CONFLICT DO NOTHING en todas las inserciones
    - No duplica datos
    - Muestra progreso en tiempo real
"""

import os
import sys
import sqlite3
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

# ── Configuración ──────────────────────────────────────────
SQLITE_PATH = "local_data/justo_pricing_local_reference.db"
DATABASE_URL = os.getenv("DATABASE_URL")
BATCH_SIZE   = 500   # filas por INSERT batch

# ── Colores para la terminal ───────────────────────────────
OK    = "\033[92m[OK]\033[0m"
INFO  = "\033[96m[..]\033[0m"
WARN  = "\033[93m[!!]\033[0m"
ERROR = "\033[91m[ERROR]\033[0m"


def log(simbolo, msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"{ts} {simbolo} {msg}")


def verificar_config():
    if not DATABASE_URL:
        print(f"{ERROR} No encontré DATABASE_URL en el .env")
        sys.exit(1)
    if not os.path.exists(SQLITE_PATH):
        print(f"{ERROR} No encontré el SQLite en: {SQLITE_PATH}")
        print("        Asegurate de correr el script desde la raíz del proyecto.")
        sys.exit(1)
    log(OK, "Config verificada")


def conectar():
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(DATABASE_URL)
    log(OK, "Conexiones abiertas (SQLite + Supabase)")
    return sqlite_conn, pg_conn


def contar(sqlite_conn, tabla):
    cur = sqlite_conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {tabla}")
    return cur.fetchone()[0]


def insertar_batch(pg_cur, sql, batch):
    """Ejecuta un INSERT batch con psycopg2.extras.execute_values."""
    psycopg2.extras.execute_values(pg_cur, sql, batch, page_size=BATCH_SIZE)


def progreso(actual, total, label=""):
    pct = int(actual / total * 50) if total else 50
    bar = "█" * pct + "░" * (50 - pct)
    print(f"\r  [{bar}] {actual:,}/{total:,} {label}", end="", flush=True)


# ══════════════════════════════════════════════════════════════
# MIGRACIÓN POR TABLA
# ══════════════════════════════════════════════════════════════

def migrar_fuentes(sl, pg):
    """fuentes — 7 filas, se insertan con ON CONFLICT DO NOTHING."""
    log(INFO, "Migrando fuentes...")
    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    cur_sl.execute("SELECT * FROM fuentes")
    rows = cur_sl.fetchall()

    sql = """
        INSERT INTO fuentes
            (id_fuente, nombre, retailer, tipo_fuente, url_base,
             frecuencia_horas, estado, ultima_captura,
             total_capturas, total_errores, creado_en, actualizado_en)
        VALUES %s
        ON CONFLICT (retailer) DO UPDATE SET
            ultima_captura  = EXCLUDED.ultima_captura,
            total_capturas  = EXCLUDED.total_capturas,
            total_errores   = EXCLUDED.total_errores,
            actualizado_en  = now()
    """
    data = [
        (r["id_fuente"], r["nombre"], r["retailer"], r["tipo_fuente"],
         r["url_base"], r["frecuencia_horas"], r["estado"],
         r["ultima_captura"], r["total_capturas"], r["total_errores"],
         r["creado_en"], r["actualizado_en"])
        for r in rows
    ]
    insertar_batch(cur_pg, sql, data)
    pg.commit()

    # Sincronizar la secuencia para que los nuevos id_fuente no colisionen
    cur_pg.execute("SELECT setval('fuentes_id_fuente_seq', (SELECT MAX(id_fuente) FROM fuentes))")
    pg.commit()
    log(OK, f"fuentes: {len(data)} filas migradas")


def migrar_productos_fuente(sl, pg):
    """productos_fuente — ~62k filas en batches."""
    total = contar(sl, "productos_fuente")
    log(INFO, f"Migrando productos_fuente ({total:,} filas)...")

    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    sql = """
        INSERT INTO productos_fuente
            (id_producto_fuente, id_fuente, retailer, nombre_original,
             url_producto, url_imagen, categoria_original, subcategoria_original,
             ean_detectado, marca_original, tipo_marca,
             fecha_alta, ultima_vez_visto, estado)
        VALUES %s
        ON CONFLICT (id_fuente, url_producto) DO NOTHING
    """

    cur_sl.execute("""
        SELECT id_producto_fuente, id_fuente, retailer, nombre_original,
               url_producto, url_imagen, categoria_original, subcategoria_original,
               ean_detectado, marca_original, tipo_marca,
               fecha_alta, ultima_vez_visto, estado
        FROM productos_fuente
    """)

    migrados = 0
    while True:
        rows = cur_sl.fetchmany(BATCH_SIZE)
        if not rows:
            break
        data = [tuple(r) for r in rows]
        insertar_batch(cur_pg, sql, data)
        pg.commit()
        migrados += len(data)
        progreso(migrados, total)

    print()  # newline tras la barra

    # Sincronizar secuencia
    cur_pg.execute("SELECT setval('productos_fuente_id_producto_fuente_seq', (SELECT MAX(id_producto_fuente) FROM productos_fuente))")
    pg.commit()
    log(OK, f"productos_fuente: {migrados:,} filas migradas")


def migrar_capturas_precio(sl, pg):
    """capturas_precio — ~63k filas en batches."""
    total = contar(sl, "capturas_precio")
    log(INFO, f"Migrando capturas_precio ({total:,} filas)...")

    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    sql = """
        INSERT INTO capturas_precio
            (id_captura, id_producto_fuente, fecha_captura, hora_captura,
             precio_actual, precio_regular, precio_oferta,
             precio_por_unidad, unidad_precio, tipo_promocion, texto_promocion,
             disponibilidad, hash_captura, score_confianza_dato,
             estado_captura, error_detalle, es_cambio_precio, creado_en)
        VALUES %s
        ON CONFLICT (hash_captura) DO NOTHING
    """

    # SQLite tiene 'stock' y 'disponibilidad' como int (0/1)
    # Postgres los espera como boolean
    cur_sl.execute("""
        SELECT id_captura, id_producto_fuente, fecha_captura, hora_captura,
               precio_actual, precio_regular, precio_oferta,
               precio_por_unidad, unidad_precio, tipo_promocion, texto_promocion,
               disponibilidad, hash_captura, score_confianza_dato,
               estado_captura, error_detalle, es_cambio_precio, creado_en
        FROM capturas_precio
        ORDER BY id_captura
    """)

    migrados = 0
    while True:
        rows = cur_sl.fetchmany(BATCH_SIZE)
        if not rows:
            break
        data = []
        for r in rows:
            data.append((
                r["id_captura"], r["id_producto_fuente"],
                r["fecha_captura"], r["hora_captura"],
                r["precio_actual"], r["precio_regular"], r["precio_oferta"],
                r["precio_por_unidad"], r["unidad_precio"],
                r["tipo_promocion"], r["texto_promocion"],
                bool(r["disponibilidad"]),   # int → bool
                r["hash_captura"],
                r["score_confianza_dato"],
                r["estado_captura"], r["error_detalle"],
                bool(r["es_cambio_precio"]), # int → bool
                r["creado_en"],
            ))
        insertar_batch(cur_pg, sql, data)
        pg.commit()
        migrados += len(data)
        progreso(migrados, total)

    print()

    cur_pg.execute("SELECT setval('capturas_precio_id_captura_seq', (SELECT MAX(id_captura) FROM capturas_precio))")
    pg.commit()
    log(OK, f"capturas_precio: {migrados:,} filas migradas")


def migrar_auditoria(sl, pg):
    total = contar(sl, "auditoria_capturas")
    log(INFO, f"Migrando auditoria_capturas ({total} filas)...")

    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    sql = """
        INSERT INTO auditoria_capturas
            (id_auditoria, id_fuente, retailer, fecha_inicio, fecha_fin,
             duracion_segundos, total_productos, total_exitosos, total_errores,
             total_cambios_precio, estado_corrida, detalle, creado_en)
        VALUES %s
        ON CONFLICT DO NOTHING
    """
    cur_sl.execute("SELECT * FROM auditoria_capturas")
    rows = cur_sl.fetchall()
    data = [
        (r["id_auditoria"], r["id_fuente"], r["retailer"],
         r["fecha_inicio"], r["fecha_fin"], r["duracion_segundos"],
         r["total_productos"], r["total_exitosos"], r["total_errores"],
         r["total_cambios_precio"], r["estado_corrida"],
         r["detalle"], r["creado_en"])
        for r in rows
    ]
    insertar_batch(cur_pg, sql, data)
    pg.commit()
    cur_pg.execute("SELECT setval('auditoria_capturas_id_auditoria_seq', (SELECT MAX(id_auditoria) FROM auditoria_capturas))")
    pg.commit()
    log(OK, f"auditoria_capturas: {len(data)} filas migradas")


def migrar_planes(sl, pg):
    """planes — 3 filas, ya insertadas por el SQL de migración, actualizamos."""
    log(INFO, "Sincronizando planes...")
    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    cur_sl.execute("SELECT * FROM planes")
    rows = cur_sl.fetchall()

    for r in rows:
        cur_pg.execute("""
            INSERT INTO planes (
                id_plan, codigo_plan, nombre_plan, descripcion,
                precio_mensual, moneda, max_productos,
                max_competidores_por_producto, max_categorias,
                max_usuarios, max_retailers, frecuencia_horas, historico_dias,
                permite_oportunidades_vs_competidor, permite_exportar,
                permite_alertas_avanzadas, permite_historico,
                activo, creado_en, actualizado_en
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (codigo_plan) DO UPDATE SET
                precio_mensual = EXCLUDED.precio_mensual,
                actualizado_en = now()
        """, (
            r["id_plan"], r["codigo_plan"], r["nombre_plan"], r["descripcion"],
            r["precio_mensual"], r["moneda"], r["max_productos"],
            r["max_competidores_por_producto"], r["max_categorias"],
            r["max_usuarios"], r["max_retailers"], r["frecuencia_horas"],
            r["historico_dias"],
            bool(r["permite_oportunidades_vs_competidor"]),
            bool(r["permite_exportar"]),
            bool(r["permite_alertas_avanzadas"]),
            bool(r["permite_historico"]),
            bool(r["activo"]),
            r["creado_en"], r["actualizado_en"],
        ))
    pg.commit()
    cur_pg.execute("SELECT setval('planes_id_plan_seq', (SELECT MAX(id_plan) FROM planes))")
    pg.commit()
    log(OK, f"planes: {len(rows)} filas sincronizadas")


def migrar_clientes(sl, pg):
    log(INFO, "Migrando clientes...")
    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    cur_sl.execute("SELECT * FROM clientes")
    rows = cur_sl.fetchall()

    for r in rows:
        cur_pg.execute("""
            INSERT INTO clientes (
                id_cliente, nombre_cliente, razon_social, cuit, rubro,
                descripcion, email_contacto, telefono_contacto,
                nombre_responsable, plan_comercial, estado,
                origen_registro, fecha_alta, actualizado_en
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id_cliente) DO NOTHING
        """, (
            r["id_cliente"], r["nombre_cliente"], r["razon_social"],
            r["cuit"], r["rubro"], r["descripcion"],
            r["email_contacto"], r["telefono_contacto"],
            r["nombre_responsable"], r["plan_comercial"],
            r["estado"], r["origen_registro"],
            r["fecha_alta"], r["actualizado_en"],
        ))
    pg.commit()
    cur_pg.execute("SELECT setval('clientes_id_cliente_seq', (SELECT MAX(id_cliente) FROM clientes))")
    pg.commit()
    log(OK, f"clientes: {len(rows)} filas migradas")


def migrar_tablas_cliente(sl, pg):
    """Migra todas las tablas pequeñas de configuración del cliente."""
    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    # suscripciones_cliente
    cur_sl.execute("SELECT * FROM suscripciones_cliente")
    for r in cur_sl.fetchall():
        cur_pg.execute("""
            INSERT INTO suscripciones_cliente
                (id_suscripcion, id_cliente, id_plan, estado,
                 fecha_inicio, fecha_fin, renovacion_automatica,
                 creado_en, actualizado_en)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id_suscripcion) DO NOTHING
        """, (
            r["id_suscripcion"], r["id_cliente"], r["id_plan"],
            r["estado"], r["fecha_inicio"], r["fecha_fin"],
            bool(r["renovacion_automatica"]),
            r["creado_en"], r["actualizado_en"],
        ))
    pg.commit()
    log(OK, "suscripciones_cliente migrada")

    # usuarios_cliente (sin password_hash — Supabase Auth maneja auth)
    cur_sl.execute("SELECT * FROM usuarios_cliente")
    for r in cur_sl.fetchall():
        cur_pg.execute("""
            INSERT INTO usuarios_cliente
                (id_usuario, id_cliente, auth_user_id,
                 nombre_usuario, email, rol, estado,
                 ultimo_login, fecha_alta, actualizado_en)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (email) DO NOTHING
        """, (
            r["id_usuario"], r["id_cliente"],
            None,  # auth_user_id se completa cuando el usuario haga login por primera vez
            r["nombre_usuario"], r["email"],
            r["rol"], r["estado"],
            r["ultimo_login"], r["fecha_alta"], r["actualizado_en"],
        ))
    pg.commit()
    log(OK, "usuarios_cliente migrada (auth_user_id se completa al primer login)")

    # retailers_cliente
    cur_sl.execute("SELECT * FROM retailers_cliente")
    for r in cur_sl.fetchall():
        cur_pg.execute("""
            INSERT INTO retailers_cliente
                (id_retailer_cliente, id_cliente, retailer, activo,
                 creado_en, actualizado_en)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id_cliente, retailer) DO NOTHING
        """, (
            r["id_retailer_cliente"], r["id_cliente"], r["retailer"],
            bool(r["activo"]), r["creado_en"], r["actualizado_en"],
        ))
    pg.commit()
    log(OK, "retailers_cliente migrada")

    # categorias_cliente
    cur_sl.execute("SELECT * FROM categorias_cliente")
    for r in cur_sl.fetchall():
        cur_pg.execute("""
            INSERT INTO categorias_cliente
                (id_categoria_cliente, id_cliente, retailer, categoria,
                 categoria_id, prioridad, activa, fecha_alta)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id_categoria_cliente) DO NOTHING
        """, (
            r["id_categoria_cliente"], r["id_cliente"], r["retailer"],
            r["categoria"], r["categoria_id"], r["prioridad"],
            bool(r["activa"]), r["fecha_alta"],
        ))
    pg.commit()
    log(OK, "categorias_cliente migrada")


def migrar_oportunidades(sl, pg):
    """oportunidades_historicas — schema diferente al nuevo.

    El ON CONFLICT DO NOTHING de abajo depende del indice unico
    ux_oport_hist_negocio (clave de negocio, NULLS NOT DISTINCT).
    Sin ese indice cada corrida duplicaba toda la tabla.
    """
    total = contar(sl, "oportunidades_historicas")
    log(INFO, f"Migrando oportunidades_historicas ({total:,} filas)...")
    log(WARN, "El schema local tiene columnas distintas al nuevo. Se mapean las relevantes.")

    cur_sl = sl.cursor()
    cur_pg = pg.cursor()

    sql = """
        INSERT INTO oportunidades_historicas
            (id_cliente, ean, retailer_propio,
             precio_propio, brecha_pct, tipo_oportunidad,
             fecha_deteccion, creado_en)
        VALUES %s
        ON CONFLICT DO NOTHING
    """

    # El SQLite local tiene id_cliente implícito = 1 (Ecovita)
    # Mapeamos las columnas disponibles al nuevo schema
    cur_sl.execute("""
        SELECT ean_norm, retailer, precio_actual,
               brecha_vs_minimo_pct, alerta_pricing,
               fecha_captura, creado_en
        FROM oportunidades_historicas
        ORDER BY id_oportunidad_historica
    """)

    migrados = 0
    while True:
        rows = cur_sl.fetchmany(BATCH_SIZE)
        if not rows:
            break
        data = []
        for r in rows:
            data.append((
                1,                          # id_cliente = Ecovita (cliente de prueba)
                r["ean_norm"],              # ean
                r["retailer"],              # retailer_propio
                r["precio_actual"],         # precio_propio
                r["brecha_vs_minimo_pct"],  # brecha_pct
                r["alerta_pricing"],        # tipo_oportunidad
                r["fecha_captura"],         # fecha_deteccion
                r["creado_en"],
            ))
        insertar_batch(cur_pg, sql, data)
        pg.commit()
        migrados += len(data)
        progreso(migrados, total)

    print()
    log(OK, f"oportunidades_historicas: {migrados:,} filas migradas")


def verificar_resultado(pg):
    log(INFO, "Verificando conteos en Supabase...")
    cur = pg.cursor()
    tablas = [
        "fuentes", "productos_fuente", "capturas_precio",
        "auditoria_capturas", "planes", "clientes",
        "suscripciones_cliente", "usuarios_cliente",
        "retailers_cliente", "categorias_cliente",
        "oportunidades_historicas",
    ]
    print()
    print("  Tabla                          | Filas en Supabase")
    print("  -------------------------------|------------------")
    for t in tablas:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        n = cur.fetchone()[0]
        print(f"  {t:<31}| {n:>10,}")
    print()


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print()
    print("=" * 60)
    print("  JUSTO Pricing 360 — Migración SQLite → Supabase")
    print("=" * 60)
    print()

    verificar_config()
    sl, pg = conectar()

    try:
        inicio = datetime.now()

        migrar_fuentes(sl, pg)
        migrar_productos_fuente(sl, pg)
        migrar_capturas_precio(sl, pg)
        migrar_auditoria(sl, pg)
        migrar_planes(sl, pg)
        migrar_clientes(sl, pg)
        migrar_tablas_cliente(sl, pg)
        migrar_oportunidades(sl, pg)

        duracion = (datetime.now() - inicio).seconds
        print()
        print("=" * 60)
        log(OK, f"Migración completa en {duracion} segundos")
        print("=" * 60)

        verificar_resultado(pg)

    except Exception as e:
        pg.rollback()
        print()
        log(ERROR, str(e))
        raise
    finally:
        sl.close()
        pg.close()


if __name__ == "__main__":
    main()
