import json
from datetime import date

from conftest import FakeResp, FakeSession

from energia.ingest import clima, vertimiento
from energia.ingest.comun import leer_json_gz


def _respuesta_clima(params):
    lats = params["latitude"].split(",")
    d0, d1 = date.fromisoformat(params["start_date"]), date.fromisoformat(params["end_date"])
    tiempos = [f"{date.fromordinal(o).isoformat()}T{h:02d}:00" for o in range(d0.toordinal(), d1.toordinal() + 1)
               for h in range(24)]
    return [{"latitude": float(la), "longitude": 0, "hourly": {"time": tiempos, **{v: [1.0] * len(tiempos)
                                                                                   for v in clima.VARIABLES}}}
            for la in lats]


def test_tramos_agrupa_dias_contiguos():
    fechas = [date(2026, 1, d) for d in (1, 2, 3, 7, 8)]
    assert clima.tramos(fechas) == [(date(2026, 1, 1), date(2026, 1, 3)), (date(2026, 1, 7), date(2026, 1, 8))]


def test_clima_un_archivo_por_dia_y_no_repite(tmp_path):
    s = FakeSession(lambda u, p: FakeResp(200, _respuesta_clima(p)))
    rc = clima.main(["--desde", "2026-10-01", "--hasta", "2026-10-03"], raw_dir=tmp_path, logs_dir=tmp_path, session=s)
    assert rc == 0 and len(s.llamadas) == 1
    datos = leer_json_gz(tmp_path / "clima/fecha_utc=2026-10-02.json.gz")
    assert set(datos["ubicaciones"]) == set(clima.UBICACIONES)
    assert len(datos["ubicaciones"]["santiago"]["time"]) == 24
    assert "Open-Meteo" in datos["fuente"]
    clima.main(["--desde", "2026-10-01", "--hasta", "2026-10-03"], raw_dir=tmp_path, logs_dir=tmp_path, session=s)
    assert len(s.llamadas) == 1  # todo existía: no hubo llamadas nuevas


def test_vertimiento_urls_candidatas():
    urls = vertimiento.urls_candidatas(2026, 8, date(2026, 10, 19))
    assert urls[0].endswith("/2026/09/Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_Agosto-26-PE-PFV_Publicar.xlsx")
    assert any("/2026/10/" in u for u in urls) and not any("/2026/11/" in u for u in urls)
    assert vertimiento.urls_candidatas(2025, 12, date(2026, 10, 19))[0].endswith(
        "/2026/01/Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_Diciembre-25-PE-PFV_Publicar.xlsx")


def test_vertimiento_descarga_solo_nuevos_y_reconoce_bloqueos(tmp_path):
    publicados = {"Julio-26": "/2026/08/", "Agosto-26": "/2026/10/"}

    def responder(url, params):
        for mes, carpeta in publicados.items():
            if mes in url and carpeta in url:
                return FakeResp(200, content=b"PK-fake", text="")
        return FakeResp(404, text="no")

    s = FakeSession(responder)
    hoy = date(2026, 10, 19)
    vertimiento.main(["--desde", "2026-07"], raw_dir=tmp_path, logs_dir=tmp_path, session=s, pausa_s=0, hoy=hoy)
    assert sorted(p.name for p in (tmp_path / "vertimiento").glob("*.xlsx")) == ["mes=2026-07.xlsx", "mes=2026-08.xlsx"]
    n = len(s.llamadas)
    vertimiento.main(["--desde", "2026-07"], raw_dir=tmp_path, logs_dir=tmp_path, session=s, pausa_s=0, hoy=hoy)
    nuevas = [u for u, _ in s.llamadas[n:]]
    assert nuevas and all("Septiembre-26" in u for u in nuevas)  # solo reintenta el mes aún no publicado
    log = [json.loads(x) for x in (tmp_path / "corridas_vertimiento.jsonl").read_text().splitlines()]
    assert len(log[0]["nuevos"]) == 2 and log[1]["nuevos"] == [] and log[1]["no_publicados"] == ["2026-09"]
