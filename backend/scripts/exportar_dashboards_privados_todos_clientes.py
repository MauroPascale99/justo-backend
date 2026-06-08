import sqlite3
import subprocess
import sys

DB_PATH = "db/justo_pricing.db"


def main():
    import sys
    import os
    import yaml
    
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
    
    config_path = os.path.join(BACKEND_DIR, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
        
    db_type = config.get("db", {}).get("tipo", "sqlite")
    if db_type == "postgres":
        print("Base de datos configurada como Postgres (Supabase).")
        print("Los dashboards de los clientes se consultan y generan de forma dinámica desde el frontend.")
        print("Se saltea la exportación de dashboards locales estáticos por cliente.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT id_cliente, nombre_cliente
        FROM clientes
        WHERE estado = 'activo'
        ORDER BY id_cliente
    """)

    clientes = cur.fetchall()
    conn.close()

    if not clientes:
        print("No hay clientes activos para exportar dashboards privados.")
        return

    print("EXPORTANDO DASHBOARDS PRIVADOS")
    print("=" * 80)
    print(f"Clientes activos detectados: {len(clientes)}")
    print("=" * 80)

    resultados = []

    for id_cliente, nombre_cliente in clientes:
        print(f"\nCliente {id_cliente} | {nombre_cliente}")
        print("-" * 80)

        cmd = [
            sys.executable,
            "herramientas/exportar_dashboard_privado_cliente.py",
            "--id-cliente",
            str(id_cliente),
        ]

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        print(proc.stdout)

        estado = "OK" if proc.returncode == 0 else "ERROR"

        resultados.append({
            "id_cliente": id_cliente,
            "nombre_cliente": nombre_cliente,
            "estado": estado,
            "returncode": proc.returncode,
        })

    print("\nRESUMEN EXPORTACIÓN DASHBOARDS PRIVADOS")
    print("=" * 80)

    ok = 0
    error = 0

    for r in resultados:
        print(f"{r['estado']} | id_cliente={r['id_cliente']} | {r['nombre_cliente']}")
        if r["estado"] == "OK":
            ok += 1
        else:
            error += 1

    print("-" * 80)
    print(f"OK: {ok}")
    print(f"ERROR: {error}")
    print("=" * 80)

    if error > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
