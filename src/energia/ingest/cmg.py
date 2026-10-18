"""Ingesta diaria del costo marginal (CMg) desde la API SIP del Coordinador Eléctrico Nacional.

La API v4 (`costo-marginal-online/v4/findByDate`) entrega el CMg cada 15 minutos para ~1.650 barras
(~158 mil registros/día) y no filtra por barra en el servidor: se pagina el día completo y se guardan solo
las barras elegidas (`--barras`). Además se lleva un catálogo de todas las barras vistas
(`data/ref/barras_cmg.json`) para poder cambiar la selección más adelante.

Límite de la API (medido el 2026-10-18 con trazas): responde 429 sin cabeceras de reset; tolera ~1 página
de 10.000 registros (~2,7 MB) cada ~20 min, mientras que requests mínimos (limit=1) pasan cada ~3 min. Por eso
se va a un ritmo fijo (`--intervalo-s`, 20 min) con presupuesto de tiempo por corrida; si igual llega un 429
se espera y, si no alcanza, se corta sin error y la próxima corrida retoma desde el checkpoint.

Salida: data/raw/cmg_online/fecha=YYYY-MM-DD.json.gz (+ checkpoint `.parcial.json` si la corrida se corta).
Uso:    python -m energia.ingest.cmg --desde 2026-10-01 --hasta 2026-10-07
        python -m energia.ingest.cmg --desde 2024-07-15 --hasta ayer --orden desc   (backfill, lo que hace cmg.yml)
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

from energia.ingest.cen import FUENTE, CENClient, ErrorCEN, LimiteAlcanzado, registros_y_paginas
from energia.ingest.comun import (
    DATA_RAW, DATA_REF, LOGS, ahora_utc, ayer_chile, escribir_json_gz, rango, registrar_corrida,
)

RECURSO_DEFAULT = "costo-marginal-online/v4/findByDate"
# Un nodo de 220 kV por zona: norte solar (Crucero, Kimal, Diego de Almagro, Cardones), centro (Quillota,
# Polpaico, Alto Jahuel) y sur (Charrúa, Puerto Montt). Nombres exactos de `barra_transf`.
BARRAS_DEFAULT = [
    "CRUCERO_______220", "KIMAL_________220", "D.ALMAGRO_____220", "CARDONES______220",
    "QUILLOTA______220", "POLPAICO______220", "A.JAHUEL______220", "CHARRUA_______220", "P.MONTT_______220",
]
CAMPOS_BARRA = ("barra_transf", "barra_mnemotecnico", "barra", "nombre_barra", "barra_info")


class SinTiempo(Exception):
    """Se acabó el presupuesto de requests o de minutos de la corrida."""


def campo_barra(reg: dict) -> str | None:
    for c in CAMPOS_BARRA:
        if c in reg:
            return c
    return None


def ruta_dia(raw_dir: Path, d: date) -> Path:
    return raw_dir / "cmg_online" / f"fecha={d.isoformat()}.json.gz"


def ruta_parcial(raw_dir: Path, d: date) -> Path:
    return raw_dir / "cmg_online" / f"fecha={d.isoformat()}.parcial.json"


def actualizar_catalogo(barras: Counter, ref_dir: Path) -> None:
    if not barras:
        return
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
    barras: list[str],
    recurso: str = RECURSO_DEFAULT,
    limit: int = 10000,
    puede_seguir=lambda: True,
    vistas: Counter | None = None,
) -> str:
    """Pagina un día completo (páginas desde 0). Devuelve 'completo', 'parcial' o 'existe'.
    `vistas` acumula cuántos registros trae cada barra (para el catálogo), aunque la corrida se corte."""
    final = ruta_dia(raw_dir, d)
    if final.exists():
        return "existe"
    vistas = vistas if vistas is not None else Counter()
    elegidas = set(barras)
    parcial = ruta_parcial(raw_dir, d)
    estado = json.loads(parcial.read_text(encoding="utf-8")) if parcial.exists() else None
    if not estado or estado.get("limit") != limit or estado.get("base") != 0:
        # Sin checkpoint, o hecho con otro tamaño de página / numeración: se parte de cero.
        estado = {"base": 0, "limit": limit, "siguiente": 0, "total_paginas": None, "n_total": 0, "registros": []}

    while estado["total_paginas"] is None or estado["siguiente"] < estado["total_paginas"]:
        if not puede_seguir():
            return "parcial"
        pagina = estado["siguiente"]
        regs, total = registros_y_paginas(client.find_by_date(recurso, d, d, pagina=pagina, limit=limit))
        estado["total_paginas"] = total if total is not None else (pagina + 2 if len(regs) >= limit else pagina + 1)
        estado["n_total"] += len(regs)
        for r in regs:
            c = campo_barra(r)
            b = str(r.get(c, "")) if c else ""
            vistas[b] += 1
            if b in elegidas:
                estado["registros"].append(r)
        estado["siguiente"] = pagina + 1
        if not regs:
            break
        parcial.parent.mkdir(parents=True, exist_ok=True)
        parcial.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")

    escribir_json_gz(final, {
        "fuente": FUENTE, "recurso": recurso, "fecha": d.isoformat(), "descargado_en": ahora_utc(),
        "n_registros_api": estado["n_total"], "barras": barras, "registros": estado["registros"],
    })
    parcial.unlink(missing_ok=True)
    return "completo"


def main(argv: list[str] | None = None, raw_dir: Path = DATA_RAW, ref_dir: Path = DATA_REF, logs_dir: Path = LOGS,
         client: CENClient | None = None, reloj=time.monotonic) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Descarga el CMg del Coordinador por día")
    p.add_argument("--desde", type=date.fromisoformat, help="YYYY-MM-DD (por defecto: ayer, hora de Chile)")
    p.add_argument("--hasta", type=date.fromisoformat, help="YYYY-MM-DD (por defecto: igual a --desde)")
    p.add_argument("--orden", choices=["asc", "desc"], default="asc", help="desc = días recientes primero (backfill)")
    p.add_argument("--recurso", default=RECURSO_DEFAULT)
    p.add_argument("--limit", type=int, default=10000, help="registros por página (50.000 hace caer al servidor)")
    p.add_argument("--barras", default=",".join(BARRAS_DEFAULT), help="nombres exactos de barra_transf, con comas")
    p.add_argument("--intervalo-s", type=float, default=1200,
                   help="segundos mínimos entre requests (medido: la API tolera ~1 página de 10.000 cada 20 min)")
    p.add_argument("--max-requests", type=int, default=100, help="tope de requests por corrida")
    p.add_argument("--max-minutos", type=float, default=330, help="presupuesto de tiempo por corrida")
    p.add_argument("--parar-tras-vacios", type=int, default=3, help="corta si encuentra N días seguidos sin datos")
    args = p.parse_args(argv)
    desde = args.desde or ayer_chile()
    hasta = min(args.hasta or desde, ayer_chile())
    dias = rango(desde, hasta) if desde <= hasta else []
    if args.orden == "desc":
        dias.reverse()
    barras = [b.strip() for b in args.barras.split(",") if b.strip()]
    # Ante un 429 se espera lo mismo que el intervalo (mínimo 5 min): los reintentos rápidos solo alargan el bloqueo.
    client = client or CENClient(pausa_s=args.intervalo_s, espera_429_s=max(300, args.intervalo_s),
                                 espera_max_s=args.max_minutos * 60)
    inicio = reloj()

    def puede_seguir() -> bool:
        return client.requests_hechos < args.max_requests and (reloj() - inicio) / 60 < args.max_minutos

    resumen: dict = {"recurso": args.recurso, "limit": args.limit, "dias": {}, "error": None}
    vistas: Counter = Counter()
    vacios = 0
    try:
        for d in dias:
            estado = descargar_dia(client, d, raw_dir, barras, args.recurso, args.limit, puede_seguir, vistas)
            if estado == "existe":
                continue
            resumen["dias"][d.isoformat()] = estado
            print(f"{d}: {estado}")
            if estado == "parcial":
                break  # se acabó el presupuesto; la próxima corrida retoma desde el checkpoint
            if _n_registros(ruta_dia(raw_dir, d)) == 0:
                vacios += 1
                if vacios >= args.parar_tras_vacios:
                    resumen["corte"] = f"{vacios} días seguidos sin datos: probable inicio de la serie"
                    break
            else:
                vacios = 0
    except LimiteAlcanzado as e:  # no es una falla: la próxima corrida retoma desde el checkpoint
        resumen["limite"] = client.ocultar(str(e))
        print(resumen["limite"])
    except ErrorCEN as e:
        resumen["error"] = client.ocultar(str(e))
        print(f"ERROR: {resumen['error']}", file=sys.stderr)
    finally:
        actualizar_catalogo(vistas, ref_dir)
        pendientes = [d for d in dias if not ruta_dia(raw_dir, d).exists()]
        resumen.update(requests=client.requests_hechos, respuestas_http=dict(client.respuestas),
                       espera_rate_limit_s=round(client.espera_total_s), minutos=round((reloj() - inicio) / 60, 1),
                       dias_pendientes_en_rango=len(pendientes), barras_distintas_vistas=len(vistas),
                       traza=client.traza)
        registrar_corrida("cmg_online", resumen, logs_dir)
    return 1 if resumen["error"] else 0


def _n_registros(path: Path) -> int:
    from energia.ingest.comun import leer_json_gz

    return int(leer_json_gz(path).get("n_registros_api", 0))


if __name__ == "__main__":
    sys.exit(main())
