import json
from datetime import date

import pytest
from conftest import FakeResp, FakeSession

from energia.ingest import cmg
from energia.ingest.cen import CENClient, ErrorCEN, LimiteAlcanzado, registros_y_paginas

CLAVE = "clave-super-secreta"


def cliente(responder, **kw):
    esperas = []
    c = CENClient(user_key=CLAVE, session=FakeSession(responder), pausa_s=0, sleep=esperas.append,
                  reloj=lambda: 1_000_000_000.0, **kw)
    return c, esperas


def test_error_no_expone_la_clave():
    c, _ = cliente(lambda u, p: FakeResp(401, text=f"user_key {CLAVE} invalida"))
    with pytest.raises(ErrorCEN) as e:
        c.get("costo-marginal-online/v4/findByDate", {})
    assert CLAVE not in str(e.value) and "***" in str(e.value) and e.value.status == 401


def test_429_espera_hasta_el_reset_y_reintenta():
    respuestas = iter([FakeResp(429, headers={"X-Rate-Limit-Reset": "1000000030"}), FakeResp(200, {"data": []})])
    c, esperas = cliente(lambda u, p: next(respuestas))
    assert c.get("x", {}) == {"data": []}
    assert esperas[0] == pytest.approx(32)  # 30 s hasta el reset + 2 de margen
    assert c.respuestas == {"429": 1, "200": 1}


def test_429_con_espera_excesiva_corta_la_corrida():
    c, _ = cliente(lambda u, p: FakeResp(429, headers={"Retry-After": "3600"}), espera_max_s=600)
    with pytest.raises(LimiteAlcanzado):
        c.get("x", {})


def test_registros_y_paginas_v4_y_v2():
    assert registros_y_paginas({"data": [1, 2], "totalPages": "3"}) == ([1, 2], 3)
    assert registros_y_paginas({"results": [1], "next": None}) == ([1], None)


def _api_cmg(paginas):
    """Simula la API v4: `paginas` es una lista de listas de barras."""
    def responder(url, params):
        i = int(params["page"]) - 1
        regs = [{"fecha_hora": f"{params['startDate']} 00:00", "barra_transf": b, "cmg_usd_mwh_": "1,5"}
                for b in paginas[i]]
        return FakeResp(200, {"data": regs, "page": i + 1, "totalPages": len(paginas)})
    return responder


def test_cmg_filtra_barras_y_guarda_catalogo(tmp_path):
    c, _ = cliente(_api_cmg([["CRUCERO_______220", "OTRA_BARRA"], ["CHARRUA______220", "OTRA_BARRA"]]))
    rc = cmg.main(["--desde", "2026-10-10"], raw_dir=tmp_path / "raw", ref_dir=tmp_path / "ref",
                  logs_dir=tmp_path / "logs", client=c)
    assert rc == 0
    from energia.ingest.comun import leer_json_gz

    datos = leer_json_gz(tmp_path / "raw/cmg_online/fecha=2026-10-10.json.gz")
    assert [r["barra_transf"] for r in datos["registros"]] == ["CRUCERO_______220", "CHARRUA______220"]
    assert datos["n_registros_api"] == 4 and datos["fuente"] == "Coordinador Eléctrico Nacional"
    catalogo = json.loads((tmp_path / "ref/barras_cmg.json").read_text())
    assert catalogo["OTRA_BARRA"] == 2
    log = json.loads((tmp_path / "logs/corridas.jsonl").read_text().splitlines()[0])
    assert log["requests"] == 2 and CLAVE not in json.dumps(log)


def test_cmg_checkpoint_retoma_y_no_repite(tmp_path):
    api = _api_cmg([["CRUCERO_1"], ["CRUCERO_2"], ["CRUCERO_3"]])
    raw = tmp_path / "raw"
    c1, _ = cliente(api)
    estado, _ = cmg.descargar_dia(c1, date(2026, 10, 10), raw, cmg.compilar(["CRUCERO"]), ["CRUCERO"], max_requests=2)
    assert estado == "parcial" and cmg.ruta_parcial(raw, date(2026, 10, 10)).exists()

    c2, _ = cliente(api)
    estado, _ = cmg.descargar_dia(c2, date(2026, 10, 10), raw, cmg.compilar(["CRUCERO"]), ["CRUCERO"])
    assert estado == "completo" and c2.requests_hechos == 1  # solo pidió la página 3
    assert not cmg.ruta_parcial(raw, date(2026, 10, 10)).exists()

    c3, _ = cliente(api)
    assert cmg.descargar_dia(c3, date(2026, 10, 10), raw, cmg.compilar(["X"]), ["X"])[0] == "existe"
    assert c3.requests_hechos == 0


def test_patrones_por_defecto_reconocen_barras_tipicas():
    p = cmg.compilar(cmg.PATRONES_DEFAULT)
    for b in ["CRUCERO_______220", "D.ALMAGRO____220", "QUILLOTA_____220", "P.MONTT______220", "A.JAHUEL_____220"]:
        assert p.search(b), b
    assert not p.search("LAGUNILLAS___220")
