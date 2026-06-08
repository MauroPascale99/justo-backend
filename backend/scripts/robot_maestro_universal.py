import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

FUENTES_DEFAULT = [
    "coto",
    "dia",
    "changomas",
    "carrefour",
    "jumbo",
    "disco",
    "vea",
]

POSTPROCESOS = [
    ("Exportar normalizado final DB", ["python", "backend/scripts/exportar_normalizado_final_db.py"]),
    ("Reporte calidad fuentes", ["python", "backend/scripts/reporte_calidad_fuentes.py"]),
    ("Motor matching EAN", ["python", "backend/scripts/motor_matching_ean.py"]),
    ("Reporte matching por categoría", ["python", "backend/scripts/reporte_matching_por_categoria.py"]),
    ("Motor oportunidades pricing EAN", ["python", "backend/scripts/motor_oportunidades_pricing_ean.py"]),
    ("Guardar oportunidades históricas", ["python", "backend/scripts/guardar_oportunidades_historicas.py"]),
    ("Motor oportunidades vs competidor cliente", ["python", "backend/scripts/motor_oportunidades_vs_competidor_cliente.py"]),
    ("Exportar datasets dashboard", ["python", "backend/scripts/exportar_datasets_dashboard.py"]),
    ("Exportar dashboards privados clientes", ["python", "backend/scripts/exportar_dashboards_privados_todos_clientes.py"]),
]

def ahora():
    return datetime.now().isoformat(timespec="seconds")

def ejecutar(nombre, comando, log_path):
    inicio = time.time()

    print("\n" + "=" * 90)
    print(f"[{ahora()}] INICIO | {nombre}")
    print("Comando:", " ".join(comando))
    print("=" * 90)

    proc = subprocess.run(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    salida = proc.stdout or ""
    print(salida)

    duracion = round(time.time() - inicio, 2)
    estado = "OK" if proc.returncode == 0 else "ERROR"

    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 90 + "\n")
        f.write(f"[{ahora()}] {nombre} | {estado} | {duracion}s\n")
        f.write("Comando: " + " ".join(comando) + "\n")
        f.write(salida)

    print("-" * 90)
    print(f"[{ahora()}] FIN | {nombre} | {estado} | {duracion}s")
    print("-" * 90)

    return {
        "paso": nombre,
        "comando": " ".join(comando),
        "estado": estado,
        "returncode": proc.returncode,
        "duracion_segundos": duracion,
    }

def leer_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def generar_resumen(resultados, inicio, fin, resumen_txt, resumen_json):
    estado_general = "OK" if all(r["estado"] == "OK" for r in resultados) else "CON_ERRORES"

    resumen = {
        "robot": "JUSTO Pricing 360 - Robot Maestro Universal",
        "inicio": inicio,
        "fin": fin,
        "estado_general": estado_general,
        "pasos_total": len(resultados),
        "pasos_ok": sum(1 for r in resultados if r["estado"] == "OK"),
        "pasos_error": sum(1 for r in resultados if r["estado"] != "OK"),
        "resultados": resultados,
        "metricas": {},
    }

    calidad = leer_csv("outputs/reporte_calidad_fuentes.csv")
    if calidad:
        resumen["metricas"]["calidad_fuentes"] = calidad

    auditoria = leer_csv("outputs/auditoria_matching_ean_resumen.csv")
    if auditoria:
        resumen["metricas"]["auditoria_matching"] = auditoria

    oportunidades = leer_csv("outputs/resumen_oportunidades_pricing_ean_accionables.csv")
    if oportunidades:
        resumen["metricas"]["oportunidades"] = oportunidades

    Path(resumen_json).write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lineas = []
    lineas.append("JUSTO Pricing 360 - Robot Maestro Universal")
    lineas.append("=" * 80)
    lineas.append(f"Inicio: {inicio}")
    lineas.append(f"Fin: {fin}")
    lineas.append(f"Estado general: {estado_general}")
    lineas.append(f"Pasos OK: {resumen['pasos_ok']} / {resumen['pasos_total']}")
    lineas.append("")
    lineas.append("PASOS")
    lineas.append("-" * 80)

    for r in resultados:
        lineas.append(f"{r['estado']:>6} | {r['duracion_segundos']:>8}s | {r['paso']}")

    lineas.append("")
    lineas.append("ARCHIVOS CLAVE")
    lineas.append("-" * 80)

    archivos = [
        "outputs/capturas_normalizadas_final_db.csv",
        "outputs/reporte_calidad_fuentes.csv",
        "outputs/matching_ean_competitivo.csv",
        "outputs/cobertura_matching_ean_por_categoria.csv",
        "outputs/oportunidades_pricing_ean_accionables.csv",
        "outputs/resumen_oportunidades_pricing_ean_accionables.csv",
    ]

    for a in archivos:
        lineas.append(("OK     " if Path(a).exists() else "FALTA  ") + a)

    Path(resumen_txt).write_text("\n".join(lineas), encoding="utf-8")

    return resumen

def main():
    parser = argparse.ArgumentParser(description="JUSTO Pricing 360 - Robot Maestro Universal")
    parser.add_argument("--fuentes", nargs="*", default=FUENTES_DEFAULT)
    parser.add_argument("--max", type=int, default=3000)
    parser.add_argument("--solo-postproceso", action="store_true")
    parser.add_argument("--continuar-si-falla", action="store_true")
    args = parser.parse_args()

    Path("outputs").mkdir(exist_ok=True)
    Path("outputs/logs").mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = f"outputs/logs/robot_maestro_universal_{ts}.log"
    resumen_txt = f"outputs/resumen_robot_maestro_universal_{ts}.txt"
    resumen_json = f"outputs/resumen_robot_maestro_universal_{ts}.json"

    inicio = ahora()
    resultados = []

    print("\n" + "#" * 90)
    print("JUSTO Pricing 360 - ROBOT MAESTRO UNIVERSAL")
    print("#" * 90)
    print(f"Inicio: {inicio}")
    print(f"Solo postproceso: {args.solo_postproceso}")
    print(f"Fuentes: {', '.join(args.fuentes)}")
    print(f"Max por fuente: {args.max}")
    print("#" * 90)

    try:
        if not args.solo_postproceso:
            for fuente in args.fuentes:
                r = ejecutar(
                    f"Scraping fuente: {fuente}",
                    ["python", "main.py", "--fuente", fuente, "--max", str(args.max)],
                    log_path,
                )
                resultados.append(r)

                if r["estado"] != "OK" and not args.continuar_si_falla:
                    raise RuntimeError(f"Falló scraping de {fuente}")

        for nombre, comando in POSTPROCESOS:
            r = ejecutar(nombre, comando, log_path)
            resultados.append(r)

            if r["estado"] != "OK" and not args.continuar_si_falla:
                raise RuntimeError(f"Falló paso: {nombre}")

    finally:
        fin = ahora()
        resumen = generar_resumen(resultados, inicio, fin, resumen_txt, resumen_json)

        print("\n" + "#" * 90)
        print("ROBOT MAESTRO FINALIZADO")
        print("#" * 90)
        print(f"Estado general: {resumen['estado_general']}")
        print(f"Pasos OK: {resumen['pasos_ok']} / {resumen['pasos_total']}")
        print(f"Resumen TXT: {resumen_txt}")
        print(f"Resumen JSON: {resumen_json}")
        print(f"Log completo: {log_path}")
        print("#" * 90)

        if resumen["estado_general"] != "OK":
            sys.exit(1)

if __name__ == "__main__":
    main()
