"""A interface espera o upload ficar completo antes de processar."""
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

import app
from cortes.config import InvalidInput
from cortes.media import probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg não instalado")


def test_espera_arquivo_que_ainda_esta_sendo_copiado(tmp_path):
    full = tmp_path / "completo.mp4"       # MP4 comum: o índice (moov) fica no FIM
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=5",
                    "-f", "lavfi", "-i", "sine=d=5", "-pix_fmt", "yuv420p", str(full)], check=True)
    data = full.read_bytes()

    upload = tmp_path / "upload.mp4"
    upload.write_bytes(data[: len(data) // 2])            # cópia pela metade
    with pytest.raises(InvalidInput, match="moov atom not found"):
        probe(upload)                                      # a mensagem traz o motivo do ffprobe

    threading.Timer(1.5, lambda: upload.write_bytes(data)).start()   # a cópia termina depois
    labels = []
    app._wait_for_upload(str(upload), lambda f, desc: labels.append(desc))
    assert labels and "upload" in labels[0]
    assert probe(upload).duration == pytest.approx(5, abs=0.2)


def test_arquivo_invalido_nao_fica_esperando_para_sempre(tmp_path):
    fake = tmp_path / "falso.mp4"
    fake.write_text("isto não é um vídeo")
    start = time.monotonic()
    app._wait_for_upload(str(fake), lambda f, desc: None)
    assert time.monotonic() - start < 8
