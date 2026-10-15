"""Descarga de los reportes mensuales de Reducciones de generación renovable (vertimiento) del Coordinador.

El Coordinador publica un XLSX por mes (por central × día × hora, hojas por tecnología) con 1–2 meses de
rezago, en https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/ .
Se rastrean las páginas por año, se descargan solo los archivos nuevos (sin re-descargar) y se guardan
tal cual en data/raw/vertimiento/. Pocas requests y con pausa: es un sitio institucional.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date
from html import unescape
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from energia.ingest.comun import DATA_RAW, LOGS, USER_AGENT, registrar_corrida

INDICE = "https://www.coordinador.cl/operacion/documentos/reducciones-de-generacion-renovable/"
FUENTE = "Coordinador Eléctrico Nacional — Reducciones de generación renovable"
_HREF = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


def enlaces(html: str, base: str) -> list[str]:
    return [urljoin(base, unescape(h)) for h in _HREF.findall(html)]


def paginas_anuales(html_indice: str, anios: list[int]) -> list[str]:
    """Páginas por año enlazadas desde el índice, más la URL esperada para cada año pedido."""
    urls = {f"{INDICE}reducciones-erv-{a}/" for a in anios}
    for u in enlaces(html_indice, INDICE):
        if "reducciones-erv-" in u and any(str(a) in u for a in anios):
            urls.add(u if u.endswith("/") else u + "/")
    return sorted(urls)


def archivos_xlsx(html: str, base: str) -> list[str]:
    vistos: dict[str, None] = {}
    for u in enlaces(html, base):
        if urlparse(u).path.lower().endswith(".xlsx") and "reducciones" in u.lower():
            vistos[u] = None
    return list(vistos)


def nombre_archivo(url: str) -> str:
    return unquote(Path(urlparse(url).path).name)


def main(argv: list[str] | None = None, raw_dir: Path = DATA_RAW, logs_dir: Path = LOGS,
         session: requests.Session | None = None, pausa_s: float = 3.0) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Descarga reportes mensuales de vertimiento (Coordinador)")
    p.add_argument("--anios", default=None, help="años separados por coma (por defecto: actual y anterior)")
    args = p.parse_args(argv)
    hoy = date.today()
    anios = [int(a) for a in args.anios.split(",")] if args.anios else [hoy.year - 1, hoy.year]
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    destino = raw_dir / "vertimiento"
    destino.mkdir(parents=True, exist_ok=True)
    resumen = {"anios": anios, "requests": 0, "paginas": {}, "nuevos": [], "error": None}

    def get(url: str) -> requests.Response:
        resumen["requests"] += 1
        r = session.get(url, timeout=120)
        time.sleep(pausa_s)
        return r

    try:
        r = get(INDICE)
        r.raise_for_status()
        for pagina in paginas_anuales(r.text, anios):
            rp = get(pagina)
            resumen["paginas"][pagina] = rp.status_code
            if rp.status_code != 200:
                continue
            for url in archivos_xlsx(rp.text, pagina):
                archivo = destino / nombre_archivo(url)
                if archivo.exists():
                    continue
                rx = get(url)
                rx.raise_for_status()
                archivo.write_bytes(rx.content)
                resumen["nuevos"].append(archivo.name)
    except requests.RequestException as e:
        resumen["error"] = str(e)[:300]
        print(f"ERROR: {resumen['error']}", file=sys.stderr)
    registrar_corrida("vertimiento", resumen, logs_dir)
    print(resumen)
    return 1 if resumen["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
