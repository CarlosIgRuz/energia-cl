"""Sondeo de endpoints de la API SIP del Coordinador (una request por candidato, ~10 en total).

La documentación pública está desactualizada (v2) y el catálogo v4 solo se ve dentro del portal, así que
este script prueba rutas candidatas y guarda en data/logs/sondeo_cen.json, por ruta: código HTTP, claves de
la respuesta, total de páginas, cantidad de registros y un registro de ejemplo. Nunca guarda la clave.
"""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

from energia.ingest.cen import CENClient, ErrorCEN, registros_y_paginas
from energia.ingest.comun import LOGS, ahora_utc, hoy_chile

# Sondeo de filtros: con limit=1, `totalPages` = cantidad total de registros que calzan. Si algún parámetro
# reduce ese número respecto de la base, la API sí filtra por barra (un día pasaría de 16 páginas a 1).
BARRA = "CRUCERO_______220"
CANDIDATOS = [
    ("base", {}),
    ("barra_transf", {"barra_transf": BARRA}),
    ("barra", {"barra": BARRA}),
    ("barraTransf", {"barraTransf": BARRA}),
    ("barra_mnemotecnico", {"barra_mnemotecnico": BARRA}),
    ("barra_info", {"barra_info": "BA S/E CRUCERO 220KV BP1"}),
    ("nombre", {"nombre": BARRA}),
]
RUTA = "costo-marginal-online/v4/findByDate"


def resumir(resp) -> dict:
    regs, total = registros_y_paginas(resp)
    claves = sorted(resp.keys()) if isinstance(resp, dict) else ["<lista>"]
    meta = {k: resp.get(k) for k in ("page", "limit", "totalPages", "total", "count") if isinstance(resp, dict) and k in resp}
    ejemplo = {k: (str(v)[:80] if v is not None else None) for k, v in (regs[0].items() if regs else [])}
    return {"claves_respuesta": claves, "meta": meta, "total_paginas": total, "n_registros": len(regs),
            "ejemplo": ejemplo}


def main(logs_dir: Path = LOGS, client: CENClient | None = None) -> int:
    client = client or CENClient(pausa_s=180, espera_max_s=600)
    resultados = {}
    d = hoy_chile() - timedelta(days=2)
    for nombre, extra in CANDIDATOS:
        params = {"startDate": d.isoformat(), "endDate": d.isoformat(), "page": 0, "limit": 1, **extra}
        res = {"ruta": RUTA, "params": params}
        try:
            res.update(status=200, **resumir(client.get(RUTA, params, reintentos=2)))
        except ErrorCEN as e:
            res.update(status=e.status, error=client.ocultar(str(e))[:300])
        res["rate_limit"] = client.ultimo_rate
        resultados[nombre] = res
        print(nombre, res.get("status"), res.get("n_registros"), res.get("total_paginas"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    base = resultados.get("base", {}).get("total_paginas")
    filtran = [n for n, r in resultados.items() if n != "base" and r.get("total_paginas") and base
               and r["total_paginas"] < base]
    salida = {"ejecutado_en": ahora_utc(), "requests": client.requests_hechos, "filtran_por_barra": filtran,
              "resultados": resultados, "traza": client.traza}
    (logs_dir / "sondeo_cen.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
