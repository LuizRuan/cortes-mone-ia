"""Configuração local/Docker, sem modelos ou chamadas a serviços externos."""
import tempfile
from pathlib import Path

import app
from cortes import transcribe


def test_servidor_local_por_padrao(monkeypatch):
    for key in ("GRADIO_SERVER_NAME", "GRADIO_SERVER_PORT", "CORTES_OPEN_BROWSER"):
        monkeypatch.delenv(key, raising=False)
    assert app.launch_options() == {"server_name": "127.0.0.1", "server_port": 7860, "inbrowser": True,
                                    "max_file_size": 20_000_000_000}


def test_servidor_configurado_para_docker(monkeypatch):
    monkeypatch.setenv("GRADIO_SERVER_NAME", "0.0.0.0")
    monkeypatch.setenv("GRADIO_SERVER_PORT", "7861")
    monkeypatch.setenv("CORTES_OPEN_BROWSER", "false")
    assert app.launch_options() == {"server_name": "0.0.0.0", "server_port": 7861, "inbrowser": False,
                                    "max_file_size": 20_000_000_000}


def test_cache_temporario_por_padrao(monkeypatch):
    monkeypatch.delenv("CORTES_CACHE_DIR", raising=False)
    assert transcribe._cache_dir() == Path(tempfile.gettempdir()) / "cortes_ia_transcricoes"


def test_cache_persistente_configuravel(monkeypatch, tmp_path):
    monkeypatch.setenv("CORTES_CACHE_DIR", str(tmp_path / "persistente"))
    cache = transcribe._cache_dir()
    part = transcribe.Transcript("pt", [transcribe.Sentence(0, 1, "Teste.", [])])
    transcribe._write_cache(cache / "bloco.json", part)
    assert transcribe._read_cache(cache / "bloco.json") == part
