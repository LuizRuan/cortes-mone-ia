"""Limite de upload e recebimento em blocos, sem criar arquivos de 20 GB."""
import asyncio
from pathlib import Path
from unittest.mock import Mock

import gradio as gr
import pytest
from gradio.route_utils import upload_fn
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.requests import Request

import app


def test_upload_obrigatorio():
    with pytest.raises(gr.Error, match="Arraste um vídeo"):
        app._source(None, Mock())


@pytest.mark.parametrize("size", [20_000_000_000, 20_000_000_001])
def test_limite_de_20_gb_sem_carregar_arquivo(monkeypatch, size):
    monkeypatch.setattr(Path, "stat", lambda *a, **kw: Mock(st_size=size))
    wait = Mock()
    monkeypatch.setattr(app, "_wait_for_upload", wait)
    if size == 20_000_000_000:
        assert app._source("video.mp4", Mock()) == "video.mp4"
        wait.assert_called_once()
    else:
        with pytest.raises(gr.Error, match="limite de 20 GB"):
            app._source("video.mp4", Mock())
        wait.assert_not_called()


@pytest.mark.parametrize("size", [1024, 1025])
def test_recepcao_em_blocos_respeita_limite_e_limpa_rejeitados(tmp_path, size):
    # Exercita o mesmo receptor do Gradio com um limite reduzido e vários blocos.
    body = (b'--teste\r\nContent-Disposition: form-data; name="files"; filename="video.mp4"\r\n'
            b'Content-Type: video/mp4\r\n\r\n' + b'v' * size + b'\r\n--teste--\r\n')
    chunks = iter(body[i:i + 128] for i in range(0, len(body), 128))

    async def receive():
        chunk = next(chunks, b"")
        return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}

    headers = Headers({"content-type": "multipart/form-data; boundary=teste"})
    request = Request({"type": "http", "method": "POST", "path": "/upload",
                       "headers": headers.raw}, receive)
    call = upload_fn(request, tmp_path, 1024, None)
    if size == 1024:
        files, copies, locations = asyncio.run(call)
        assert Path(files[0]).read_bytes() == b"v" * size
        assert not copies and not locations
    else:
        with pytest.raises(MultiPartException, match="maximum allowed size"):
            asyncio.run(call)
        assert not list(tmp_path.iterdir())
