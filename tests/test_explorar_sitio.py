import io
import json
import zipfile

from conftest import FakeResp

from energia.ingest import explorar_sitio


def test_muestra_csv_y_enlaces():
    info = explorar_sitio.muestra_archivo("cmg.csv", b"barra;fecha;hora;cmg\nCRUCERO;2026-10-14;1;3,2\n")
    assert info["primeras_lineas"][0] == "barra;fecha;hora;cmg" and info["n_lineas_aprox"] == 2
    html = '<a href="/wp-content/uploads/2026/10/Antecedentes_CMG_Real_pre_261014.zip">Descargar ZIP</a>'
    assert explorar_sitio.enlaces(html, "https://www.coordinador.cl/x/") == [
        "https://www.coordinador.cl/wp-content/uploads/2026/10/Antecedentes_CMG_Real_pre_261014.zip"]


def test_explorar_recorre_anio_mes_dia_y_lista_el_zip(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cmg_real.csv", "barra,hora,cmg\nCRUCERO,1,0\n")
    mes = ("/mercados/documentos/transferencias-economicas/costo-marginal-real/2026-costo-marginal-real/"
           "octubre-2026-costo-marginal-real")
    dia = ("/mercados/documentos/costo-marginal-real/2026-costo-marginal-real/octubre-2026-costo-marginal-real/"
           "14-octubre-2026-costo-marginal-real")

    class Sesion:
        headers: dict = {}

        def get(self, url, timeout=None):
            if url.endswith(".zip"):
                return FakeResp(200, content=buf.getvalue(), text="")
            if "14-octubre" in url:
                return FakeResp(200, text='<a href="/wp-content/uploads/2026/10/A_261014.zip">zip</a>')
            if "octubre-2026" in url:
                return FakeResp(200, text=f'<a href="{dia}">14</a>')
            return FakeResp(200, text=f'<a href="{mes}">oct</a>')

    monkeypatch.setattr(explorar_sitio.requests, "Session", Sesion)
    explorar_sitio.main(logs_dir=tmp_path, pausa_s=0)
    salida = json.loads((tmp_path / "explorar_cmg_sitio.json").read_text())
    m = salida["muestras"]["2026"]
    assert m["archivos_dia"][0].endswith("A_261014.zip")
    assert m["descargas"][0]["miembros"][0]["nombre"] == "cmg_real.csv"
    assert m["descargas"][0]["muestras"][0]["primeras_lineas"][0] == "barra,hora,cmg"


def test_probar_sitio_registra_status_y_cabeceras(tmp_path):
    from conftest import FakeSession

    from energia.ingest import probar_sitio

    s = FakeSession(lambda u, p: FakeResp(403, text="<html>Access denied</html>", headers={"Server": "cloudflare"}))
    s.get = lambda url, timeout=None, stream=None: FakeResp(403, text="<html>Access denied</html>",
                                                             headers={"Server": "cloudflare"})
    probar_sitio.main(logs_dir=tmp_path, session=s, pausa_s=0)
    res = json.loads((tmp_path / "probar_sitio.json").read_text())["resultados"]
    assert len(res) == len(probar_sitio.URLS)
    primero = next(iter(res.values()))
    assert primero["status"] == 403 and primero["headers"]["Server"] == "cloudflare"
