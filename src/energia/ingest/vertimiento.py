"""Descarga de los reportes mensuales de Reducciones de generación renovable (vertimiento) del Coordinador.

El Coordinador publica un XLSX por mes (por central × día × hora, hojas por tecnología) con 1–2 meses de
rezago. Las páginas índice del sitio están detrás de un desafío de Cloudflare para GitHub Actions, pero los
archivos de `/wp-content/uploads/` sí se descargan (robots.txt los permite expresamente). Por eso se arma la URL
directa con el patrón observado y se prueban las carpetas de publicación posibles (1 a 3 meses después del mes
informado). Sin re-descargar, con pausa y User-Agent de navegador (autorizado por Carlos el 2026-10-19).

Patrón: /wp-content/uploads/AAAA/MM/Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_<Mes>-<AA>-PE-PFV_Publicar.xlsx
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

import requests

from energia.ingest.comun import DATA_RAW, LOGS, SITIO_CEN, USER_AGENT_NAVEGADOR, hoy_chile, registrar_corrida

FUENTE = "Coordinador Eléctrico Nacional — Reducciones de generación renovable"
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre",
         "Noviembre", "Diciembre"]


def sumar_meses(anio: int, mes: int, n: int) -> tuple[int, int]:
    k = anio * 12 + (mes - 1) + n
    return k // 12, k % 12 + 1


def nombre_archivo(anio: int, mes: int) -> str:
    return f"Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_{MESES[mes - 1]}-{anio % 100:02d}-PE-PFV_Publicar.xlsx"


def urls_candidatas(anio: int, mes: int, hoy: date) -> list[str]:
    """Carpetas de publicación posibles: 1, 2 y 3 meses después del mes informado (sin pasar de hoy)."""
    out = []
    for n in (1, 2, 3, 0):
        a, m = sumar_meses(anio, mes, n)
        if (a, m) <= (hoy.year, hoy.month):
            out.append(f"{SITIO_CEN}/wp-content/uploads/{a}/{m:02d}/{nombre_archivo(anio, mes)}")
    return out


def ruta_local(raw_dir: Path, anio: int, mes: int) -> Path:
    return raw_dir / "vertimiento" / f"mes={anio}-{mes:02d}.xlsx"


def main(argv: list[str] | None = None, raw_dir: Path = DATA_RAW, logs_dir: Path = LOGS,
         session: requests.Session | None = None, pausa_s: float = 3.0, hoy: date | None = None) -> int:
    p = argparse.ArgumentParser(description="Descarga reportes mensuales de vertimiento (Coordinador)")
    p.add_argument("--desde", default="2024-07", help="primer mes AAAA-MM (por defecto 2024-07)")
    args = p.parse_args(argv)
    hoy = hoy or hoy_chile()
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT_NAVEGADOR})
    a, m = (int(x) for x in args.desde.split("-"))
    resumen: dict = {"nuevos": [], "no_publicados": [], "bloqueados": [], "requests": 0, "error": None}
    try:
        while (a, m) < (hoy.year, hoy.month):
            destino = ruta_local(raw_dir, a, m)
            if not destino.exists():
                encontrado = False
                for url in urls_candidatas(a, m, hoy):
                    r = session.get(url, timeout=120)
                    resumen["requests"] += 1
                    time.sleep(pausa_s)
                    if r.status_code == 200 and r.content[:2] == b"PK":  # un xlsx es un zip: empieza con "PK"
                        destino.parent.mkdir(parents=True, exist_ok=True)
                        destino.write_bytes(r.content)
                        resumen["nuevos"].append({"mes": f"{a}-{m:02d}", "url": url, "bytes": len(r.content)})
                        encontrado = True
                        break
                    if r.status_code == 403:
                        resumen["bloqueados"].append(url)
                if not encontrado:
                    resumen["no_publicados"].append(f"{a}-{m:02d}")
            a, m = sumar_meses(a, m, 1)
    except requests.RequestException as e:
        resumen["error"] = str(e)[:300]
        print(f"ERROR: {resumen['error']}", file=sys.stderr)
    registrar_corrida("vertimiento", resumen, logs_dir)
    print({k: (len(v) if isinstance(v, list) else v) for k, v in resumen.items()})
    return 1 if resumen["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
