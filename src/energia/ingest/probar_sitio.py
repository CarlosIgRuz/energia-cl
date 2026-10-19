"""Prueba mínima de acceso al sitio del Coordinador desde GitHub Actions (5 requests).

Registra en data/logs/probar_sitio.json, por URL: código HTTP, cabeceras del servidor/WAF y el inicio del cuerpo,
para saber si el 403 depende de la página o del origen de la conexión.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

from energia.ingest.comun import LOGS, USER_AGENT_NAVEGADOR, ahora_utc

URLS = [
    "https://www.coordinador.cl/wp-content/uploads/2026/10/Antecedentes_CMG_Real_pre_261014.zip",
    "https://www.coordinador.cl/wp-content/uploads/2026/10/"
    "Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_Agosto-26-PE-PFV_Publicar.xlsx",
    "https://www.coordinador.cl/robots.txt",
    "https://www.coordinador.cl/",
    "https://www.coordinador.cl/mercados/documentos/transferencias-economicas/costo-marginal-real/",
]
HEADERS = {
    "User-Agent": USER_AGENT_NAVEGADOR,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
}


def main(logs_dir: Path = LOGS, session=None, pausa_s: float = 3.0, urls: list[str] | None = None) -> int:
    s = session or requests.Session()
    s.headers.update(HEADERS)
    res = {}
    for u in urls or (sys.argv[1:] if __name__ == "__main__" and len(sys.argv) > 1 else URLS):
        try:
            r = s.get(u, timeout=60, stream=True)
            cuerpo = next(r.iter_content(600), b"") if hasattr(r, "iter_content") else r.content[:600]
            res[u] = {
                "status": r.status_code,
                "headers": {k: v for k, v in r.headers.items()
                            if k.lower() in ("server", "content-type", "content-length", "cf-ray", "x-cache",
                                             "x-sucuri-id", "x-iinfo", "set-cookie", "via", "x-akamai-request-id")},
                "inicio_cuerpo": cuerpo[:400].decode("latin-1", errors="replace") if r.status_code != 200
                or "text" in r.headers.get("content-type", "") else f"<{len(cuerpo)} bytes binarios>",
            }
        except requests.RequestException as e:
            res[u] = {"error": str(e)[:200]}
        print(u[-60:], res[u].get("status"))
        time.sleep(pausa_s)
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "probar_sitio.json").write_text(json.dumps({"ejecutado_en": ahora_utc(), "resultados": res},
                                                            ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
