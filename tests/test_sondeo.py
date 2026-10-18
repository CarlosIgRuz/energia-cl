import json

from conftest import FakeResp, FakeSession

from energia.ingest import sondeo
from energia.ingest.cen import CENClient


def test_sondeo_detecta_parametro_que_filtra_y_no_guarda_la_clave(tmp_path):
    def responder(url, params):
        if params.get("barra") == sondeo.BARRA:
            return FakeResp(200, {"data": [{"barra_transf": sondeo.BARRA}], "totalPages": 96})
        if "nombre" in params:
            return FakeResp(404, text=f"no existe ({params['user_key']})")
        return FakeResp(200, {"data": [{"barra_transf": "OTRA"}], "totalPages": 158000})

    c = CENClient(user_key="CLAVE123", session=FakeSession(responder), pausa_s=0, sleep=lambda s: None)
    sondeo.main(logs_dir=tmp_path, client=c)
    texto = (tmp_path / "sondeo_cen.json").read_text()
    salida = json.loads(texto)
    assert salida["filtran_por_barra"] == ["barra"]
    assert salida["resultados"]["nombre"]["status"] == 404
    assert len(salida["traza"]) == len(sondeo.CANDIDATOS)
    assert "CLAVE123" not in texto
