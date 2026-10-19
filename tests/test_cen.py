import json
from collections import Counter
from datetime import date, timedelta

import pytest
from conftest import FakeResp, FakeSession

from energia.ingest import cmg
from energia.ingest.cen import CENClient, ErrorCEN, LimiteAlcanzado, registros_y_paginas
from energia.ingest.comun import ayer_chile, leer_json_gz

CLAVE = "clave-super-secreta"


class Reloj:
    """Reloj falso: `sleep` avanza el tiempo en vez de dormir."""

    def __init__(self):
        self.t = 1_000_000_000.0
        self.esperas: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.esperas.append(s)
        self.t += s


def cliente(responder, **kw):
    r = Reloj()
    kw.setdefault("pausa_s", 0)
    c = CENClient(user_key=CLAVE, session=FakeSession(responder), sleep=r.sleep, reloj=r, **kw)
    return c, r


def test_error_no_expone_la_clave():
    c, _ = cliente(lambda u, p: FakeResp(401, text=f"user_key {CLAVE} invalida"))
    with pytest.raises(ErrorCEN) as e:
        c.get("costo-marginal-online/v4/findByDate", {})
    assert CLAVE not in str(e.value) and "***" in str(e.value) and e.value.status == 401


def test_429_con_reset_espera_hasta_el_reset():
    respuestas = iter([FakeResp(429, headers={"X-Rate-Limit-Reset": "1000000030"}), FakeResp(200, {"data": []})])
    c, r = cliente(lambda u, p: next(respuestas))
    assert c.get("x", {}) == {"data": []}
    assert r.esperas[0] == pytest.approx(32)  # 30 s hasta el reset + 2 de margen
    assert c.respuestas == {"429": 1, "200": 1}


def test_429_sin_cabeceras_espera_creciente_y_corta_por_presupuesto():
    c, r = cliente(lambda u, p: FakeResp(429), espera_429_s=300, espera_max_s=1000)
    with pytest.raises(LimiteAlcanzado):
        c.get("x", {})
    assert r.esperas == [300, 600]  # la tercera (900) superaría el presupuesto de 1000 s


def test_429_persistente_termina_como_limite_no_como_error():
    c, r = cliente(lambda u, p: FakeResp(429), espera_429_s=10, espera_max_s=10_000)
    with pytest.raises(LimiteAlcanzado):
        c.get("x", {}, reintentos=3)
    assert r.esperas == [10, 20, 30]


def test_ritmo_minimo_entre_requests():
    c, r = cliente(lambda u, p: FakeResp(200, {"data": []}), pausa_s=150)
    c.get("x", {})
    c.get("x", {})
    r.t += 100  # pasó tiempo entre medio: solo falta completar hasta 150 s
    c.get("x", {})
    assert r.esperas == [150, 50]


def test_registros_y_paginas_v4_y_v2():
    assert registros_y_paginas({"data": [1, 2], "totalPages": "3"}) == ([1, 2], 3)
    assert registros_y_paginas({"results": [1], "next": None}) == ([1], None)


def _api_cmg(paginas_por_dia):
    """Simula la API v4 con páginas desde 0. `paginas_por_dia(fecha)` → lista de listas de barras."""
    def responder(url, params):
        paginas = paginas_por_dia(params["startDate"])
        i = int(params["page"])
        regs = [{"fecha_hora": f"{params['startDate']} 00:00", "barra_transf": b, "cmg_usd_mwh_": "1.5"}
                for b in (paginas[i] if i < len(paginas) else [])]
        return FakeResp(200, {"data": regs, "page": i, "totalPages": len(paginas)})
    return responder


def test_cmg_pagina_desde_cero_filtra_barras_y_guarda_catalogo(tmp_path):
    c, _ = cliente(_api_cmg(lambda f: [["CRUCERO_______220", "OTRA"], ["CHARRUA_______220", "OTRA"]]))
    rc = cmg.main(["--desde", "2026-10-10"], raw_dir=tmp_path / "raw", ref_dir=tmp_path / "ref",
                  logs_dir=tmp_path / "logs", client=c)
    assert rc == 0
    assert [p["page"] for _, p in c.session.llamadas] == [0, 1]
    datos = leer_json_gz(tmp_path / "raw/cmg_online/fecha=2026-10-10.json.gz")
    assert [r["barra_transf"] for r in datos["registros"]] == ["CRUCERO_______220", "CHARRUA_______220"]
    assert datos["n_registros_api"] == 4 and datos["fuente"] == "Coordinador Eléctrico Nacional"
    assert json.loads((tmp_path / "ref/barras_cmg.json").read_text())["OTRA"] == 2
    log = json.loads((tmp_path / "logs/corridas_cmg_online.jsonl").read_text().splitlines()[0])
    assert log["requests"] == 2 and CLAVE not in json.dumps(log)


def test_cmg_checkpoint_retoma_y_no_repite(tmp_path):
    api = _api_cmg(lambda f: [["CRUCERO_______220"]] * 3)
    raw, d, barras = tmp_path / "raw", date(2026, 10, 10), ["CRUCERO_______220"]
    c1, _ = cliente(api)
    assert cmg.descargar_dia(c1, d, raw, barras, puede_seguir=lambda: c1.requests_hechos < 2) == "parcial"
    assert cmg.ruta_parcial(raw, d).exists()

    c2, _ = cliente(api)
    assert cmg.descargar_dia(c2, d, raw, barras) == "completo"
    assert [p["page"] for _, p in c2.session.llamadas] == [2]  # solo pidió la última página
    assert len(leer_json_gz(cmg.ruta_dia(raw, d))["registros"]) == 3
    assert not cmg.ruta_parcial(raw, d).exists()

    c3, _ = cliente(api)
    assert cmg.descargar_dia(c3, d, raw, barras) == "existe" and c3.requests_hechos == 0


def test_checkpoint_con_otro_tamano_de_pagina_se_descarta(tmp_path):
    raw, d = tmp_path / "raw", date(2026, 10, 10)
    p = cmg.ruta_parcial(raw, d)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"pagina": 10, "total_paginas": 32, "n_total": 50000, "registros": [{"x": 1}]}))
    c, _ = cliente(_api_cmg(lambda f: [["CRUCERO_______220"]]))
    assert cmg.descargar_dia(c, d, raw, ["CRUCERO_______220"]) == "completo"
    assert c.session.llamadas[0][1]["page"] == 0
    assert leer_json_gz(cmg.ruta_dia(raw, d))["registros"] == [
        {"fecha_hora": "2026-10-10 00:00", "barra_transf": "CRUCERO_______220", "cmg_usd_mwh_": "1.5"}]


def test_backfill_desc_corta_tras_dias_vacios(tmp_path):
    ayer = ayer_chile()
    con_datos = {(ayer - timedelta(days=i)).isoformat() for i in range(2)}
    c, _ = cliente(_api_cmg(lambda f: [["CRUCERO_______220"]] if f in con_datos else []))
    cmg.main(["--desde", (ayer - timedelta(days=30)).isoformat(), "--hasta", ayer.isoformat(), "--orden", "desc",
              "--parar-tras-vacios", "2"], raw_dir=tmp_path / "raw", ref_dir=tmp_path / "ref",
             logs_dir=tmp_path / "logs", client=c)
    pedidos = [p["startDate"] for _, p in c.session.llamadas]
    assert pedidos[0] == ayer.isoformat() and len(pedidos) == 4  # 2 con datos + 2 vacíos y corta
    log = json.loads((tmp_path / "logs/corridas_cmg_online.jsonl").read_text().splitlines()[0])
    assert "corte" in log


def test_presupuesto_de_requests_deja_parcial(tmp_path):
    c, _ = cliente(_api_cmg(lambda f: [["CRUCERO_______220"]] * 5))
    cmg.main(["--desde", "2026-10-10", "--max-requests", "3"], raw_dir=tmp_path / "raw", ref_dir=tmp_path / "ref",
             logs_dir=tmp_path / "logs", client=c)
    assert c.requests_hechos == 3 and cmg.ruta_parcial(tmp_path / "raw", date(2026, 10, 10)).exists()
    assert Counter(json.loads((tmp_path / "ref/barras_cmg.json").read_text())) == {"CRUCERO_______220": 3}


def test_ninguna_espera_pasa_la_hora_limite_de_la_corrida():
    c, r = cliente(lambda u, p: FakeResp(429), espera_429_s=1200, espera_max_s=10**6, duracion_max_s=3000)
    with pytest.raises(LimiteAlcanzado):
        c.get("x", {}, reintentos=5)
    assert sum(r.esperas) <= 3000 and r.esperas == [1200]  # la segunda (2400) se pasaría de los 3000 s
