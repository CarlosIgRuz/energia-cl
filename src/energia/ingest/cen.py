"""Cliente de la API pública (SIP) del Coordinador Eléctrico Nacional.

Portal y clave: https://portal.api.coordinador.cl (plan "Sistema de Información Pública").
Endpoints v4 tipo `https://sipub.api.coordinador.cl/<recurso>/v4/findByDate?startDate&endDate&page&limit&user_key`.
Límite por defecto documentado: 60 consultas/hora por cuenta (HTTP 429 al excederlo, con cabeceras
X-Rate-Limit-*). El cliente respeta esas cabeceras y nunca expone la clave en errores ni logs.
"""
from __future__ import annotations

import os
import time
from collections import Counter
from datetime import date

import requests

from energia.ingest.comun import USER_AGENT

BASE_URL = "https://sipub.api.coordinador.cl"
FUENTE = "Coordinador Eléctrico Nacional"


class ErrorCEN(Exception):
    def __init__(self, mensaje: str, status: int | None = None):
        super().__init__(mensaje)
        self.status = status


class LimiteAlcanzado(ErrorCEN):
    """La espera pedida por la API supera lo que estamos dispuestos a esperar en esta corrida."""


class CENClient:
    def __init__(
        self,
        user_key: str | None = None,
        session: requests.Session | None = None,
        pausa_s: float = 1.0,
        espera_max_s: float = 900,
        sleep=time.sleep,
        reloj=time.time,
    ):
        self.user_key = user_key or os.getenv("CEN_USER_KEY")
        if not self.user_key:
            raise ValueError("Falta CEN_USER_KEY (secret del repo o .env)")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.pausa_s = pausa_s
        self.espera_max_s = espera_max_s
        self._sleep = sleep
        self._reloj = reloj
        self.requests_hechos = 0
        self.respuestas: Counter[str] = Counter()
        self.espera_total_s = 0.0
        self.ultimo_rate: dict = {}

    # ---- utilidades -------------------------------------------------------
    def ocultar(self, texto: str) -> str:
        return texto.replace(self.user_key, "***")

    def _esperar(self, segundos: float) -> None:
        if segundos > self.espera_max_s:
            raise LimiteAlcanzado(f"La API pide esperar {segundos:.0f} s (máximo {self.espera_max_s:.0f} s)", 429)
        self.espera_total_s += segundos
        self._sleep(segundos)

    def segundos_hasta_reset(self, headers) -> float:
        """Retry-After (segundos) o X-Rate-Limit-Reset (timestamp Unix o segundos). Por defecto 60 s."""
        ra = headers.get("Retry-After")
        if ra and str(ra).strip().isdigit():
            return float(ra) + 1
        reset = headers.get("X-Rate-Limit-Reset")
        try:
            r = float(reset)
        except (TypeError, ValueError):
            return 60.0
        if r > 1e9:  # timestamp Unix (s o ms)
            if r > 1e12:
                r /= 1000
            return max(1.0, r - self._reloj()) + 2
        return r + 2

    # ---- request ----------------------------------------------------------
    def get(self, ruta: str, params: dict, reintentos: int = 4) -> dict | list:
        url = f"{BASE_URL}/{ruta.lstrip('/')}"
        ultimo = "sin respuesta"
        for intento in range(reintentos):
            try:
                resp = self.session.get(url, params={**params, "user_key": self.user_key}, timeout=120)
            except requests.RequestException as e:
                self.respuestas["red"] += 1
                ultimo = self.ocultar(str(e))
                self._sleep(2 ** intento * 5)
                continue
            self.requests_hechos += 1
            self.respuestas[str(resp.status_code)] += 1
            self.ultimo_rate = {
                k: resp.headers.get(k) for k in ("X-Rate-Limit", "X-Rate-Limit-Remaining", "X-Rate-Limit-Reset")
            }
            if resp.status_code == 200:
                if str(resp.headers.get("X-Rate-Limit-Remaining", "")).strip() == "0":
                    self._esperar(self.segundos_hasta_reset(resp.headers))
                else:
                    self._sleep(self.pausa_s)
                try:
                    return resp.json()
                except ValueError:
                    raise ErrorCEN(f"Respuesta no JSON en {ruta}", 200) from None
            if resp.status_code == 429:
                ultimo = "HTTP 429"
                self._esperar(self.segundos_hasta_reset(resp.headers))
                continue
            if resp.status_code < 500:  # 4xx distinto de 429: no tiene sentido reintentar
                cuerpo = self.ocultar(resp.text[:300])
                raise ErrorCEN(f"HTTP {resp.status_code} en {ruta}: {cuerpo}", resp.status_code) from None
            ultimo = f"HTTP {resp.status_code}"
            self._sleep(2 ** intento * 5)
        raise ErrorCEN(f"Fallo al consultar {ruta}: {ultimo}") from None

    def find_by_date(self, ruta: str, desde: date, hasta: date, pagina: int = 1, limit: int = 5000):
        params = {"startDate": desde.isoformat(), "endDate": hasta.isoformat(), "page": pagina, "limit": limit}
        return self.get(ruta, params)


def registros_y_paginas(resp) -> tuple[list[dict], int | None]:
    """Normaliza las respuestas paginadas: v4 trae {data, page, limit, totalPages}; v2 traía {results, next}."""
    if isinstance(resp, list):
        return resp, 1
    regs: list = []
    for clave in ("data", "results", "registros", "items"):
        if isinstance(resp.get(clave), list):
            regs = resp[clave]
            break
    total = resp.get("totalPages", resp.get("total_pages"))
    try:
        total = int(total) if total is not None else None
    except (TypeError, ValueError):
        total = None
    return regs, total
