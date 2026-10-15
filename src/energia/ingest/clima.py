"""Ingesta de clima horario desde Open-Meteo (Historical Forecast API), sin clave.

Se usa la API de *pronósticos históricos* (lo que el modelo meteorológico pronosticaba en su momento) y no
el reanálisis, para que las variables de clima del modelo sean las mismas que estarían disponibles al
pronosticar el día siguiente: así el backtest no usa información del futuro.

Condiciones: uso gratuito solo no comercial, < 10.000 llamadas/día; datos CC BY 4.0 → atribuir
"Datos meteorológicos: Open-Meteo.com (CC BY 4.0)".
Salida: data/raw/clima/fecha_utc=YYYY-MM-DD.json.gz (horas en UTC, todas las ubicaciones del día).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

from energia.ingest.comun import (
    DATA_RAW, LOGS, USER_AGENT, ahora_utc, escribir_json_gz, parser_fechas, registrar_corrida, resolver_fechas,
)

URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
FUENTE = "Open-Meteo.com (CC BY 4.0)"
UBICACIONES = {
    "maria_elena": (-22.35, -69.67),      # polo solar del Norte Grande (cerca de Crucero/Kimal)
    "diego_de_almagro": (-26.39, -70.05),  # polo solar de Atacama
    "quillota": (-32.88, -71.25),          # centro
    "santiago": (-33.45, -70.66),          # mayor centro de consumo (temperatura → demanda)
    "charrua": (-37.13, -72.35),           # sur: hidro y eólica
}
VARIABLES = [
    "temperature_2m", "shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation",
    "cloud_cover", "wind_speed_100m", "precipitation",
]
MAX_DIAS_POR_LLAMADA = 31


def ruta_dia(raw_dir: Path, d: date) -> Path:
    return raw_dir / "clima" / f"fecha_utc={d.isoformat()}.json.gz"


def descargar_rango(session: requests.Session, desde: date, hasta: date) -> list[dict]:
    nombres = list(UBICACIONES)
    params = {
        "latitude": ",".join(str(UBICACIONES[n][0]) for n in nombres),
        "longitude": ",".join(str(UBICACIONES[n][1]) for n in nombres),
        "hourly": ",".join(VARIABLES),
        "start_date": desde.isoformat(),
        "end_date": hasta.isoformat(),
        "timezone": "GMT",
    }
    resp = session.get(URL, params=params, timeout=120)
    resp.raise_for_status()
    datos = resp.json()
    datos = datos if isinstance(datos, list) else [datos]  # con una sola ubicación la API devuelve un objeto
    if len(datos) != len(nombres):
        raise ValueError(f"Se esperaban {len(nombres)} ubicaciones y llegaron {len(datos)}")
    return [{**d, "ubicacion": n} for n, d in zip(nombres, datos)]


def dividir_por_dia(respuestas: list[dict]) -> dict[str, dict]:
    """De una respuesta multi-día y multi-ubicación a {fecha_utc: {ubicacion: {time: [...], var: [...]}}}."""
    por_dia: dict[str, dict] = defaultdict(dict)
    for r in respuestas:
        horas = r["hourly"]
        tiempos = horas["time"]
        for i, t in enumerate(tiempos):
            dia = t[:10]
            bloque = por_dia[dia].setdefault(r["ubicacion"], {
                "latitude": r.get("latitude"), "longitude": r.get("longitude"), "elevation": r.get("elevation"),
                "time": [], **{v: [] for v in VARIABLES},
            })
            bloque["time"].append(t)
            for v in VARIABLES:
                bloque[v].append(horas.get(v, [None] * len(tiempos))[i])
    return dict(por_dia)


def tramos(fechas: list[date]) -> list[tuple[date, date]]:
    """Agrupa fechas faltantes en tramos contiguos de hasta MAX_DIAS_POR_LLAMADA días."""
    out: list[tuple[date, date]] = []
    for d in sorted(fechas):
        if out and d == out[-1][1] + timedelta(days=1) and (d - out[-1][0]).days < MAX_DIAS_POR_LLAMADA:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def main(argv: list[str] | None = None, raw_dir: Path = DATA_RAW, logs_dir: Path = LOGS,
         session: requests.Session | None = None) -> int:
    args = parser_fechas("Descarga clima horario (Open-Meteo) por día UTC").parse_args(argv)
    session = session or requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    faltantes = [d for d in resolver_fechas(args) if not ruta_dia(raw_dir, d).exists()]
    resumen = {"dias_escritos": 0, "llamadas": 0, "bytes": 0, "error": None}
    try:
        for desde, hasta in tramos(faltantes):
            resp = descargar_rango(session, desde, hasta)
            resumen["llamadas"] += 1
            for dia, ubic in dividir_por_dia(resp).items():
                d = date.fromisoformat(dia)
                if desde <= d <= hasta:
                    resumen["bytes"] += escribir_json_gz(ruta_dia(raw_dir, d), {
                        "fuente": FUENTE, "api": URL, "fecha_utc": dia, "descargado_en": ahora_utc(),
                        "variables": VARIABLES, "ubicaciones": ubic,
                    })
                    resumen["dias_escritos"] += 1
    except (requests.RequestException, ValueError, KeyError) as e:
        resumen["error"] = str(e)[:300]
        print(f"ERROR: {resumen['error']}", file=sys.stderr)
    registrar_corrida("clima", resumen, logs_dir)
    print(resumen)
    return 1 if resumen["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
