"""
JUSTO Pricing 360 — Motor de Eventos de Precios y Alertas (Optimizado)
=====================================================================
Compara las últimas capturas de precio ingresadas con la captura
inmediatamente anterior usando funciones de ventana SQL (LEAD) para
minimizar latencia y consultas de red.
"""

import os
import sys
import yaml
from datetime import datetime
from dotenv import load_dotenv

# Resolver directorios
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(BACKEND_DIR)

load_dotenv(dotenv_path=os.path.join(ROOT_DIR, ".env"))

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from db.database import Database

# Cargar configuración
config_path = os.path.join(BACKEND_DIR, "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

db = Database(config["db"])

def execute_sql(cur, sql, params=None):
    """Traduce placeholders de PostgreSQL (%s) a SQLite (?) si es necesario."""
    if db.db_type == "sqlite":
        sql = sql.replace("%s", "?")
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)

def main():
    print("\n" + "="*70)
    print("  INICIANDO MOTOR DE EVENTOS DE PRECIOS Y ALERTAS (JUSTO AI)")
    print("="*70)

    conn = db._get_connection()
    cur = db.get_cursor_for_connection(conn)

    # 1. Obtener la fecha de captura más reciente
    execute_sql(cur, "SELECT MAX(fecha_captura) FROM capturas_precio")
    row_date = cur.fetchone()
    
    latest_date = None
    if row_date:
        if isinstance(row_date, dict):
            latest_date = row_date.get("max") or row_date.get("SELECT MAX(fecha_captura)") or list(row_date.values())[0]
        else:
            latest_date = row_date[0]

    if not latest_date:
        print("No hay capturas registradas en la base de datos.")
        conn.close()
        return

    print(f"Procesando capturas para la fecha más reciente: {latest_date}")

    # 2. Query optimizado usando funciones de ventana para traer todos los cambios
    sql_opt = """
        WITH EANs_interes AS (
            SELECT DISTINCT ean FROM productos_cliente WHERE activo = true AND ean IS NOT NULL AND ean != ''
            UNION
            SELECT DISTINCT ean_competidor FROM mapa_competitivo_cliente WHERE activo = true AND ean_competidor IS NOT NULL AND ean_competidor != ''
        ),
        ranked_captures AS (
            SELECT 
                c.id_captura,
                c.id_producto_fuente,
                c.fecha_captura,
                c.hora_captura,
                c.precio_actual,
                c.precio_regular,
                c.precio_oferta,
                c.disponibilidad,
                pf.retailer,
                pf.ean_detectado,
                pf.nombre_original,
                pf.marca_original,
                LEAD(c.precio_actual) OVER (PARTITION BY c.id_producto_fuente ORDER BY c.fecha_captura DESC, c.hora_captura DESC, c.id_captura DESC) as precio_actual_anterior,
                LEAD(c.precio_regular) OVER (PARTITION BY c.id_producto_fuente ORDER BY c.fecha_captura DESC, c.hora_captura DESC, c.id_captura DESC) as precio_regular_anterior,
                LEAD(c.precio_oferta) OVER (PARTITION BY c.id_producto_fuente ORDER BY c.fecha_captura DESC, c.hora_captura DESC, c.id_captura DESC) as precio_oferta_anterior,
                LEAD(c.disponibilidad) OVER (PARTITION BY c.id_producto_fuente ORDER BY c.fecha_captura DESC, c.hora_captura DESC, c.id_captura DESC) as disponibilidad_anterior,
                LEAD(c.id_captura) OVER (PARTITION BY c.id_producto_fuente ORDER BY c.fecha_captura DESC, c.hora_captura DESC, c.id_captura DESC) as id_captura_anterior,
                ROW_NUMBER() OVER (PARTITION BY c.id_producto_fuente ORDER BY c.fecha_captura DESC, c.hora_captura DESC, c.id_captura DESC) as rn
            FROM capturas_precio c
            JOIN productos_fuente pf ON pf.id_producto_fuente = c.id_producto_fuente
            WHERE pf.ean_detectado IN (SELECT ean FROM EANs_interes)
        )
        SELECT * FROM ranked_captures 
        WHERE rn = 1 
          AND fecha_captura = %s
          AND id_captura_anterior IS NOT NULL
    """

    print("Obteniendo historial de comparación...")
    execute_sql(cur, sql_opt, (latest_date,))
    comparativos = cur.fetchall()
    print(f"Total comparativas obtenidas para procesar: {len(comparativos)}")

    eventos_nuevos = 0
    alertas_nuevas = 0

    for row in comparativos:
        id_pf = row["id_producto_fuente"]
        id_captura_actual = row["id_captura"]
        id_captura_anterior = row["id_captura_anterior"]
        ean = row["ean_detectado"]
        retailer = row["retailer"]

        # Precios
        p1_act = row["precio_actual"] or row["precio_regular"]
        p2_ant = row["precio_actual_anterior"] or row["precio_regular_anterior"]

        # Disponibilidad
        disp1 = row["disponibilidad"]
        disp2 = row["disponibilidad_anterior"]
        disp1_bool = True if disp1 in (1, True, "1") else False
        disp2_bool = True if disp2 in (1, True, "1") else False

        tipo_evento = None
        precio_anterior = p2_ant
        precio_actual = p1_act
        var_abs = 0.0
        var_pct = 0.0

        # Caso A: Cambios de disponibilidad
        if disp2_bool and not disp1_bool:
            tipo_evento = "desaparicion"
        elif not disp2_bool and disp1_bool:
            tipo_evento = "reaparicion"
            if p1_act and p2_ant:
                var_abs = float(p1_act) - float(p2_ant)
                var_pct = (var_abs / float(p2_ant)) * 100 if p2_ant > 0 else 0.0
        
        # Caso B: Cambios de precio
        elif disp1_bool and disp2_bool and p1_act and p2_ant:
            p1_val = float(p1_act)
            p2_val = float(p2_ant)
            diff = p1_val - p2_val

            if abs(diff) >= 0.1:  # Ignorar diferencias de centavos
                var_abs = diff
                var_pct = (diff / p2_val) * 100
                
                # Caso B1: Oferta
                if row["precio_oferta"] and not row["precio_oferta_anterior"]:
                    tipo_evento = "promocion"
                else:
                    tipo_evento = "aumento" if diff > 0 else "baja"

        if not tipo_evento:
            continue

        # Verificar si ya guardamos este evento
        sql_check_evento = "SELECT id_evento FROM eventos_precio WHERE id_captura_actual = %s AND tipo_evento = %s"
        execute_sql(cur, sql_check_evento, (id_captura_actual, tipo_evento))
        existe_evento = cur.fetchone()

        id_evento = None
        if not existe_evento:
            sql_ins_evento = """
                INSERT INTO eventos_precio (
                    id_producto, retailer, tipo_evento, precio_anterior, precio_actual,
                    variacion_absoluta, variacion_pct, fecha_deteccion,
                    id_captura_anterior, id_captura_actual, validado
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            if db.db_type == "postgres":
                sql_ins_evento += " RETURNING id_evento"

            params_evento = (
                id_pf, retailer, tipo_evento, precio_anterior, precio_actual,
                var_abs, var_pct, datetime.now(),
                id_captura_anterior, id_captura_actual, False
            )
            execute_sql(cur, sql_ins_evento, params_evento)

            if db.db_type == "postgres":
                id_evento = cur.fetchone()["id_evento"]
            else:
                id_evento = cur.lastrowid
            
            eventos_nuevos += 1
        else:
            if isinstance(existe_evento, dict):
                id_evento = existe_evento["id_evento"]
            else:
                id_evento = existe_evento[0]

        # 3. Disparar alertas basadas en reglas de los clientes
        if ean:
            sql_reglas = """
                SELECT 
                    m.*,
                    p.nombre_producto as nombre_propio,
                    p.ean as ean_propio
                FROM mapa_competitivo_cliente m
                JOIN productos_cliente p ON p.id_producto_cliente = m.id_producto_cliente
                WHERE m.activo = true AND p.activo = true
                  AND (m.ean_competidor = %s OR p.ean = %s)
            """
            execute_sql(cur, sql_reglas, (str(ean).strip(), str(ean).strip()))
            reglas = cur.fetchall()

            for r in reglas:
                id_cliente = r["id_cliente"]
                id_prod_cli = r["id_producto_cliente"]
                umbral = float(r["umbral_variacion_pct"])

                es_competidor = (str(ean).strip() == str(r["ean_competidor"]).strip() and retailer == r["retailer_competidor"])
                es_propio = (str(ean).strip() == str(r["ean_propio"]).strip())

                alerta_mensaje = None
                prioridad = "BAJA"

                # A. Alertas de Competidor
                if es_competidor:
                    nombre_comp = r["nombre_competidor"]
                    if tipo_evento == "aumento" and r["alertar_suba_competidor"] and abs(var_pct) >= umbral:
                        alerta_mensaje = f"📈 {retailer.upper()}: Competidor {nombre_comp} subió de ${int(precio_anterior):,} a ${int(precio_actual):,} (+{var_pct:.1f}%)"
                        prioridad = "ALTA" if abs(var_pct) >= 10 else "MEDIA"
                    elif tipo_evento == "baja" and r["alertar_baja_competidor"] and abs(var_pct) >= umbral:
                        alerta_mensaje = f"📉 {retailer.upper()}: Competidor {nombre_comp} bajó de ${int(precio_anterior):,} a ${int(precio_actual):,} (-{abs(var_pct):.1f}%)"
                        prioridad = "ALTA" if abs(var_pct) >= 8 else "MEDIA"
                    elif tipo_evento == "promocion" and r["alertar_promocion"]:
                        alerta_mensaje = f"🏷️ {retailer.upper()}: Competidor {nombre_comp} activó oferta a ${int(precio_actual):,} (antes ${int(precio_anterior):,})"
                        prioridad = "MEDIA"
                    elif tipo_evento == "desaparicion" and r["alertar_ausencia"]:
                        alerta_mensaje = f"🚫 {retailer.upper()}: Competidor {nombre_comp} se encuentra ausente / sin stock"
                        prioridad = "MEDIA"

                # B. Alertas de Producto Propio
                elif es_propio:
                    nombre_propio = r["nombre_propio"]
                    if tipo_evento == "aumento" and r["alertar_suba_propio"] and abs(var_pct) >= umbral:
                        alerta_mensaje = f"📈 {retailer.upper()}: Tu producto {nombre_propio} subió de ${int(precio_anterior):,} a ${int(precio_actual):,} (+{var_pct:.1f}%)"
                        prioridad = "MEDIA"
                    elif tipo_evento == "baja" and r["alertar_baja_propio"] and abs(var_pct) >= umbral:
                        alerta_mensaje = f"📉 {retailer.upper()}: Tu producto {nombre_propio} bajó de ${int(precio_anterior):,} a ${int(precio_actual):,} (-{abs(var_pct):.1f}%)"
                        prioridad = "ALTA"

                if alerta_mensaje:
                    sql_check_alerta = "SELECT id_alerta FROM alertas_cliente WHERE id_cliente = %s AND id_producto_cliente = %s AND mensaje = %s"
                    execute_sql(cur, sql_check_alerta, (id_cliente, id_prod_cli, alerta_mensaje))
                    existe_alerta = cur.fetchone()

                    if not existe_alerta:
                        sql_ins_alerta = """
                            INSERT INTO alertas_cliente (
                                id_cliente, id_producto_cliente, tipo, mensaje, leida, fecha
                            )
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """
                        execute_sql(cur, sql_ins_alerta, (
                            id_cliente, id_prod_cli, f"precio_{tipo_evento}", alerta_mensaje, False, datetime.now()
                        ))
                        alertas_nuevas += 1

    conn.commit()
    conn.close()

    print(f"\nProceso finalizado:")
    print(f"  Eventos de variación creados: {eventos_nuevos}")
    print(f"  Alertas de clientes generadas: {alertas_nuevas}")
    print("="*70 + "\n")

if __name__ == "__main__":
    main()
