"""Download pelo link do Google Drive, contra um Drive simulado (sem internet)."""
import httpx
import pytest

from cortes import drive
from cortes.config import Cancelled, InvalidInput

FID = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
VIDEO = bytes(range(256)) * 40_000          # ~10 MB de "vídeo"
WARNING_PAGE = f"""<html><body><p>O Google Drive não pode verificar este arquivo quanto a vírus.</p>
<form id="download-form" action="https://drive.usercontent.google.com/download" method="get">
<input type="submit" id="uc-download-link" value="Fazer o download assim mesmo"/>
<input type="hidden" name="id" value="{FID}"><input type="hidden" name="export" value="download">
<input type="hidden" name="confirm" value="t"><input type="hidden" name="uuid" value="abc-123"></form></body></html>"""


class FakeDrive:
    def __init__(self, mode="grande"):
        self.mode, self.requests = mode, []

    def file_response(self, request):
        start = 0
        if "range" in request.headers:
            start = int(request.headers["range"].split("=")[1].rstrip("-"))
        body = VIDEO[start:]
        headers = {"content-disposition": "attachment; filename=\"CEO cultura.MOV\"; filename*=UTF-8''CEO%20cultura.MOV",
                   "content-length": str(len(body)), "content-type": "video/quicktime"}
        return httpx.Response(206 if start else 200, headers=headers, content=body)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = request.url
        if url.host == "accounts.google.com":
            return httpx.Response(200, html="<html>Fazer login</html>")
        if self.mode == "restrito":
            return httpx.Response(302, headers={"location": "https://accounts.google.com/ServiceLogin?continue=x"})
        if self.mode == "cota":
            return httpx.Response(200, html='<p class="uc-error-subcaption">Cota de download excedida.</p>')
        if url.host == "drive.google.com" and self.mode == "grande":
            return httpx.Response(200, html=WARNING_PAGE)
        if url.host == "drive.usercontent.google.com" or self.mode == "pequeno":
            if self.mode == "grande":
                q = url.params
                assert (q["id"], q["confirm"], q["uuid"]) == (FID, "t", "abc-123")
            return self.file_response(request)
        return httpx.Response(404)


def client(fake):
    return httpx.Client(transport=httpx.MockTransport(fake), follow_redirects=True)


@pytest.mark.parametrize("link", [
    f"https://drive.google.com/file/d/{FID}/view?usp=sharing",
    f"https://drive.google.com/file/d/{FID}/view?usp=drive_link",
    f"https://drive.google.com/open?id={FID}",
    f"https://drive.google.com/uc?id={FID}&export=download",
    f"  https://drive.google.com/u/1/file/d/{FID}/view  ",
])
def test_reconhece_os_formatos_de_link(link):
    assert drive.is_drive_link(link)
    assert drive.file_id(link) == FID


def test_link_de_pasta_ou_invalido_explica_o_que_fazer():
    with pytest.raises(InvalidInput, match="pasta"):
        drive.file_id(f"https://drive.google.com/drive/folders/{FID}")
    with pytest.raises(InvalidInput, match="Copiar link"):
        drive.file_id("https://drive.google.com/drive/my-drive")
    assert not drive.is_drive_link(r"C:\Videos\ceo.mp4")


def test_video_grande_passa_pela_pagina_de_aviso_e_e_baixado(tmp_path):
    fake = FakeDrive("grande")
    steps = []
    path = drive.download(f"https://drive.google.com/file/d/{FID}/view", tmp_path,
                          lambda f, label: steps.append((f, label)), client(fake))
    assert path == tmp_path / FID / "CEO cultura.MOV"
    assert path.read_bytes() == VIDEO
    assert [r.url.host for r in fake.requests] == ["drive.google.com", "drive.usercontent.google.com"]
    assert steps[-1][0] == 1.0 and any("Baixando do Google Drive" in l for _, l in steps)

    # Segunda vez: reaproveita o arquivo, sem tocar na rede.
    again = FakeDrive("grande")
    assert drive.download(f"https://drive.google.com/open?id={FID}", tmp_path, http=client(again)) == path
    assert again.requests == []


def test_cancelar_no_meio_e_retomar_de_onde_parou(tmp_path):
    fake = FakeDrive("pequeno")

    def cancel_at_half(fraction, label):
        if fraction > 0.5:
            raise Cancelled()
    with pytest.raises(Cancelled):
        drive.download(f"https://drive.google.com/open?id={FID}", tmp_path, cancel_at_half, client(fake))
    partial = tmp_path / f"{FID}.parte"
    already = partial.stat().st_size
    assert 0 < already < len(VIDEO)

    fake.requests.clear()
    path = drive.download(f"https://drive.google.com/open?id={FID}", tmp_path, http=client(fake))
    assert fake.requests[0].headers["range"] == f"bytes={already}-"
    assert path.read_bytes() == VIDEO and not partial.exists()


def test_arquivo_restrito_explica_como_liberar(tmp_path):
    with pytest.raises(InvalidInput, match="Qualquer pessoa com o link"):
        drive.download(f"https://drive.google.com/open?id={FID}", tmp_path, http=client(FakeDrive("restrito")))


def test_cota_excedida_mostra_o_motivo_do_drive(tmp_path):
    with pytest.raises(InvalidInput, match="Cota de download excedida"):
        drive.download(f"https://drive.google.com/open?id={FID}", tmp_path, http=client(FakeDrive("cota")))


def test_arquivo_que_nao_e_video_e_recusado(tmp_path):
    class Planilha(FakeDrive):
        def file_response(self, request):
            return httpx.Response(200, headers={"content-disposition": 'attachment; filename="custos.xlsx"'}, content=b"x")
    with pytest.raises(InvalidInput, match="custos.xlsx"):
        drive.download(f"https://drive.google.com/open?id={FID}", tmp_path, http=client(Planilha("pequeno")))
