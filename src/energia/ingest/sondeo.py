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

# (nombre, ruta, días hacia atrás, parámetros: "v4" usa startDate/endDate/page/limit, "v2" usa fecha/limit)
CANDIDATOS = [
    # Confirmados el 2026-10-18: CMg en línea (cada 15 min, ~1.650 barras), CMg real definitivo (rezago de meses)
    # y generación real por central con tecnología (v3). Sin CMg programado ni demanda en v4.
    ("cmg_online", "costo-marginal-online/v4/findByDate", 2, "v4", 10),
    ("cmg_online_pagina_50k", "costo-marginal-online/v4/findByDate", 2, "v4", 50000),
    ("cmg_real", "costo-marginal-real/v4/findByDate", 120, "v4", 10),
    ("generacion_real_v3", "generacion-real/v3/findByDate", 2, "v4", 10),
]


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
    for nombre, ruta, atras, estilo, limit in CANDIDATOS:
        d = hoy_chile() - timedelta(days=atras)
        params = ({"startDate": d.isoformat(), "endDate": d.isoformat(), "page": 0, "limit": limit, "pageSize": limit}
                  if estilo == "v4" else {"fecha": d.isoformat(), "limit": limit})
        res = {"ruta": ruta, "params": params}
        try:
            res.update(status=200, **resumir(client.get(ruta, params, reintentos=2)))
        except ErrorCEN as e:
            res.update(status=e.status, error=client.ocultar(str(e))[:300])
        res["rate_limit"] = client.ultimo_rate
        resultados[nombre] = res
        print(nombre, res.get("status"), res.get("n_registros"), res.get("total_paginas"))
    logs_dir.mkdir(parents=True, exist_ok=True)
    salida = {"ejecutado_en": ahora_utc(), "requests": client.requests_hechos, "resultados": resultados}
    (logs_dir / "sondeo_cen.json").write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
