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


HTML_INDICE = '<a href="/operacion/documentos/reducciones-de-generacion-renovable/reducciones-erv-2025/">2025</a>'
HTML_ANIO = (
    '<a href="https://www.coordinador.cl/wp-content/uploads/2026/10/'
    'Reducciones-de-Energia-Eolica-Solar-Hidro-en-el-SEN_Agosto-26-PE-PFV_Publicar.xlsx">Agosto</a>'
    '<a href="/wp-content/uploads/2026/08/otro.pdf">pdf</a>'
)


def test_vertimiento_extrae_enlaces():
    paginas = vertimiento.paginas_anuales(HTML_INDICE, [2025, 2026])
    assert any(p.endswith("reducciones-erv-2025/") for p in paginas)
    assert any(p.endswith("reducciones-erv-2026/") for p in paginas)
    xlsx = vertimiento.archivos_xlsx(HTML_ANIO, "https://www.coordinador.cl/")
    assert len(xlsx) == 1 and vertimiento.nombre_archivo(xlsx[0]).endswith("Agosto-26-PE-PFV_Publicar.xlsx")


def test_vertimiento_descarga_solo_nuevos(tmp_path):
    def responder(url, params):
        if url.endswith(".xlsx"):
            return FakeResp(200, content=b"PK-fake", text="")
        return FakeResp(200, text=HTML_INDICE if url == vertimiento.INDICE else HTML_ANIO)

    s = FakeSession(responder)
    vertimiento.main(["--anios", "2026"], raw_dir=tmp_path, logs_dir=tmp_path, session=s, pausa_s=0)
    archivos = list((tmp_path / "vertimiento").glob("*.xlsx"))
    assert len(archivos) == 1
    n = len(s.llamadas)
    vertimiento.main(["--anios", "2026"], raw_dir=tmp_path, logs_dir=tmp_path, session=s, pausa_s=0)
    assert len(s.llamadas) == n + 2  # índice + página del año, sin volver a bajar el xlsx
    log = [json.loads(x) for x in (tmp_path / "corridas_vertimiento.jsonl").read_text().splitlines()]
    assert log[0]["nuevos"] and not log[1]["nuevos"]
