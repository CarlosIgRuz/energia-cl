import json

from conftest import FakeResp, FakeSession

from energia.ingest import sondeo
from energia.ingest.cen import CENClient


def test_sondeo_registra_estado_por_ruta_sin_la_clave(tmp_path):
    def responder(url, params):
        if "costo-marginal-online" in url:
            return FakeResp(200, {"data": [{"barra_transf": "CRUCERO", "cmg_usd_mwh_": "0"}], "totalPages": 15})
        return FakeResp(404, text=f"no existe ({params['user_key']})")

    c = CENClient(user_key="CLAVE123", session=FakeSession(responder), pausa_s=0, sleep=lambda s: None)
    sondeo.main(logs_dir=tmp_path, client=c)
    texto = (tmp_path / "sondeo_cen.json").read_text()
    res = json.loads(texto)["resultados"]
    assert res["cmg_online"]["status"] == 200 and res["cmg_online"]["total_paginas"] == 15
    assert res["cmg_online"]["ejemplo"]["barra_transf"] == "CRUCERO"
    assert res["generacion_real_v3"]["status"] == 404
    assert "CLAVE123" not in texto
    assert c.requests_hechos == len(sondeo.CANDIDATOS)
