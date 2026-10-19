"""Utilidades compartidas por las ingestas: rutas, fechas en hora de Chile, escritura atómica y bitácora."""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[3]
DATA_RAW = RAIZ / "data" / "raw"
DATA_REF = RAIZ / "data" / "ref"
LOGS = RAIZ / "data" / "logs"
TZ_CHILE = ZoneInfo("America/Santiago")
USER_AGENT = "Mozilla/5.0 (compatible; energia-cl/0.1; +https://github.com/CarlosIgRuz/energia-cl)"
# El sitio web del Coordinador responde 403 a clientes que no se identifican como navegador. Carlos autorizó
# (2026-10-19) usar un User-Agent de navegador estándar solo para sus archivos públicos, con pocas descargas y pausa.
USER_AGENT_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
SITIO_CEN = "https://www.coordinador.cl"


def hoy_chile() -> date:
    return datetime.now(TZ_CHILE).date()


def ayer_chile() -> date:
    return hoy_chile() - timedelta(days=1)


def rango(desde: date, hasta: date) -> list[date]:
    if hasta < desde:
        raise ValueError(f"hasta ({hasta}) es anterior a desde ({desde})")
    return [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]


def ahora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def escribir_json_gz(path: Path, obj) -> int:
    """Escribe de forma atómica (archivo temporal + rename) y devuelve el tamaño en bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)
    return path.stat().st_size


def leer_json_gz(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def registrar_corrida(fuente: str, resumen: dict, logs_dir: Path = LOGS) -> None:
    """Agrega una línea a data/logs/corridas_<fuente>.jsonl (los logs de Actions no son legibles desde el agente).
    Un archivo por fuente: si dos workflows escribieran el mismo archivo, el `git pull --rebase` chocaría."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    linea = {"fuente": fuente, "terminada_en": ahora_utc(), **resumen}
    with open(logs_dir / f"corridas_{fuente}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def parser_fechas(descripcion: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=descripcion)
    p.add_argument("--desde", type=date.fromisoformat, help="YYYY-MM-DD (por defecto: ayer, hora de Chile)")
    p.add_argument("--hasta", type=date.fromisoformat, help="YYYY-MM-DD (por defecto: igual a --desde)")
    return p


def resolver_fechas(args) -> list[date]:
    desde = args.desde or ayer_chile()
    hasta = args.hasta or desde
    return rango(desde, hasta)
