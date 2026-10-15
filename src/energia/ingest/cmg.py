"""Ingesta diaria del costo marginal (CMg) horario desde la API SIP del Coordinador Eléctrico Nacional.

La API v4 no filtra por barra en el servidor (~150 mil registros/día con todas las barras), así que se
pagina el día completo y se guardan solo las barras de interés (`--patrones`). Además se mantiene un
catálogo de todas las barras vistas en `data/ref/barras_cmg.json` para poder elegir otras más adelante.

Salida: data/raw/cmg_online/fecha=YYYY-MM-DD.json.gz  (+ checkpoint `.parcial.json` si la corrida se corta).
Uso:    python -m energia.ingest.cmg --desde 2026-10-01 --hasta 2026-10-07 --max-requests 50
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from energia.ingest.cen import FUENTE, CENClient, ErrorCEN, LimiteAlcanzado, registros_y_paginas
from energia.ingest.comun import (
    DATA_RAW, DATA_REF, LOGS, ahora_utc, escribir_json_gz, parser_fechas, registrar_corrida, resolver_fechas,
)

RECURSO_DEFAULT = "costo-marginal-online/v4/findByDate"
# Barras representativas de norte (solar), centro (consumo) y sur (hidro/eólica). Se afinan con el catálogo.
PATRONES_DEFAULT = [
    r"CRUCERO", r"KIMAL", r"D\.?\s*ALMAGRO|DIEGO", r"CARDONES", r"QUILLOTA", r"POLPAICO",
    r"A\.?\s*JAHUEL|ALTO\s*JAHUEL", r"CHARRUA", r"P\.?\s*MONTT|PUERTO\s*MONTT",
]
CAMPOS_BARRA = ("barra_transf", "barra_mnemotecnico", "barra", "nombre_barra", "barra_info")


def campo_barra(reg: dict) -> str | None:
    for c in CAMPOS_BARRA:
        if c in reg:
            return c
    return None


def compilar(patrones: list[str]) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patrones), re.IGNORECASE)


def ruta_dia(raw_dir: Path, d: date) -> Path:
    return raw_dir / "cmg_online" / f"fecha={d.isoformat()}.json.gz"


def ruta_parcial(raw_dir: Path, d: date) -> Path:
    return raw_dir / "cmg_online" / f"fecha={d.isoformat()}.parcial.json"


def actualizar_catalogo(barras: Counter, ref_dir: Path) -> None:
    ref_dir.mkdir(parents=True, exist_ok=True)
    path = ref_dir / "barras_cmg.json"
    previo = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for b, n in barras.items():
        previo[b] = previo.get(b, 0) + n
    path.write_text(json.dumps(dict(sorted(previo.items())), ensure_ascii=False, indent=0), encoding="utf-8")


def descargar_dia(
    client: CENClient,
    d: date,
    raw_dir: Path,
    patron: re.Pattern,
    patrones: list[str],
    recurso: str = RECURSO_DEFAULT,
    limit: int = 5000,
    max_requests: int | None = None,
) -> tuple[str, Counter]:
    """Devuelve ('completo'|'parcial'|'existe', barras vistas en esta llamada)."""
    final = ruta_dia(raw_dir, d)
    if final.exists():
        return "existe", Counter()
    parcial = ruta_parcial(raw_dir, d)
    estado = json.loads(parcial.read_text(encoding="utf-8")) if parcial.exists() else {
        "pagina": 0, "total_paginas": None, "n_total": 0, "registros": [],
    }
    vistas: Counter = Counter()
    pagina = estado["pagina"] + 1
    while estado["total_paginas"] is None or pagina <= estado["total_paginas"]:
        if max_requests is not None and client.requests_hechos >= max_requests:
            break
        resp = client.find_by_date(recurso, d, d, pagina=pagina, limit=limit)
        regs, total = registros_y_paginas(resp)
        estado["total_paginas"] = total if total is not None else (pagina + 1 if len(regs) >= limit else pagina)
        estado["n_total"] += len(regs)
        for r in regs:
            c = campo_barra(r)
            b = str(r.get(c, "")) if c else ""
            vistas[b] += 1
            if b and patron.search(b):
                estado["registros"].append(r)
        estado["pagina"] = pagina
        pagina += 1
        if not regs:
            break
        parcial.parent.mkdir(parents=True, exist_ok=True)
        parcial.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")

    if estado["total_paginas"] is not None and estado["pagina"] >= estado["total_paginas"]:
        escribir_json_gz(final, {
            "fuente": FUENTE, "recurso": recurso, "fecha": d.isoformat(), "descargado_en": ahora_utc(),
            "n_registros_api": estado["n_total"], "patrones_barra": patrones, "registros": estado["registros"],
        })
        parcial.unlink(missing_ok=True)
        return "completo", vistas
    return "parcial", vistas


def main(argv: list[str] | None = None, raw_dir: Path = DATA_RAW, ref_dir: Path = DATA_REF, logs_dir: Path = LOGS,
         client: CENClient | None = None) -> int:
    p = parser_fechas("Descarga CMg horario del Coordinador por día")
    p.add_argument("--recurso", default=RECURSO_DEFAULT)
    p.add_argument("--limit", type=int, default=5000, help="registros por página")
    p.add_argument("--max-requests", type=int, default=50, help="tope de requests por corrida (límite API: 60/h)")
    p.add_argument("--patrones", default=",".join(PATRONES_DEFAULT), help="regex de barras, separadas por coma")
    args = p.parse_args(argv)
    patrones = [x for x in args.patrones.split(",") if x.strip()]
    patron = compilar(patrones)
    client = client or CENClient()

    resumen = {"recurso": args.recurso, "dias": {}, "error": None}
    vistas_total: Counter = Counter()
    try:
        for d in resolver_fechas(args):
            estado, vistas = descargar_dia(client, d, raw_dir, patron, patrones, args.recurso, args.limit,
                                           args.max_requests)
            vistas_total.update(vistas)
            resumen["dias"][d.isoformat()] = estado
            print(f"{d}: {estado}")
            if estado == "parcial":
                break  # se acabó el cupo de la corrida; la próxima retoma desde el checkpoint
    except LimiteAlcanzado as e:  # no es una falla: la próxima corrida retoma desde el checkpoint
        resumen["limite"] = client.ocultar(str(e))
        print(f"Límite de la API: {resumen['limite']}")
    except ErrorCEN as e:
        resumen["error"] = client.ocultar(str(e))
        print(f"ERROR: {resumen['error']}", file=sys.stderr)
    finally:
        if vistas_total:
            actualizar_catalogo(vistas_total, ref_dir)
        resumen.update(requests=client.requests_hechos, respuestas_http=dict(client.respuestas),
                       espera_rate_limit_s=round(client.espera_total_s), rate_limit=client.ultimo_rate,
                       barras_distintas_vistas=len(vistas_total))
        registrar_corrida("cmg_online", resumen, logs_dir)
    return 1 if resumen["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
