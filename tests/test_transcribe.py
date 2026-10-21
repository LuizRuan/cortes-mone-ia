"""Transcrição em blocos: divisão do áudio, motores local e Groq, cache e cancelamento.

Nada aqui baixa modelo ou acessa a internet: o faster-whisper é trocado por um
modelo falso e a API do Groq por um servidor simulado (httpx.MockTransport).
"""
import json
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from cortes import transcribe as tr
from cortes.cloud import CloudError, Groq
from cortes.config import Cancelled

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg não instalado")


@pytest.fixture(autouse=True)
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "CACHE_DIR", tmp_path / "cache")


def make_wav(path, expr, seconds):
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"aevalsrc='{expr}':s=16000:d={seconds}",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(path),
    ], check=True)
    return path


@pytest.fixture(scope="module")
def long_wav(tmp_path_factory):
    """25 min: "fala" (tom) com uma pausa de 1 s em 10:20 e silêncio total de 20:35 até o fim."""
    expr = "0.3*sin(2*PI*300*t)*not(between(t,620,621))*lt(t,1235)"
    return make_wav(tmp_path_factory.mktemp("wav") / "longo.wav", expr, 1500)


def test_read_wav_le_so_o_trecho_pedido(long_wav):
    part = tr.read_wav(long_wav, 10.0, 12.5)
    assert part.dtype == np.float32 and len(part) == 2.5 * 16000
    assert tr.wav_duration(long_wav) == pytest.approx(1500)


def test_blocos_cortam_nas_pausas_e_cobrem_tudo(long_wav):
    blocks = tr.chunk_bounds(long_wav, 1500)
    assert blocks[0][0] == 0 and blocks[-1][1] == 1500
    assert all(a[1] == b[0] for a, b in zip(blocks, blocks[1:]))     # sem buracos nem sobreposição
    assert 620 <= blocks[0][1] <= 621                                  # caiu dentro da pausa
    assert 1235 <= blocks[1][1] <= 1250                                # no começo do silêncio final
    assert tr.is_silent(tr.read_wav(long_wav, blocks[-1][0] + 30, 1500))
    assert not tr.is_silent(tr.read_wav(long_wav, 0, 60))


class FakeModel:
    """Imita o faster-whisper: uma frase de 1 s a 3 s em cada bloco recebido."""
    def __init__(self, calls):
        self.calls = calls

    def transcribe(self, audio, **kwargs):
        self.calls.append(len(audio) / 16000)
        assert kwargs["word_timestamps"] and kwargs["beam_size"] == 1 and kwargs["vad_filter"]
        words = [SimpleNamespace(start=1.0, end=2.0, word=" Olá"), SimpleNamespace(start=2.0, end=3.0, word=" mundo")]
        seg = SimpleNamespace(start=1.0, end=3.0, text=" Olá mundo", words=words)
        return iter([seg]), SimpleNamespace(language="pt", duration=len(audio) / 16000)


def test_local_em_blocos_com_cache_e_retomada(long_wav, monkeypatch):
    calls, loads = [], []
    monkeypatch.setattr(tr, "_load_model", lambda size: loads.append(size) or FakeModel(calls))
    blocks = tr.chunk_bounds(long_wav, 1500)

    # Cancela no meio do segundo bloco: o primeiro já ficou salvo.
    def cancel_no_bloco_2(fraction, label):
        if "bloco 2 de" in label and calls:
            raise Cancelled()
    with pytest.raises(Cancelled):
        tr.transcribe(long_wav, "local", "small", "pt", cancel_no_bloco_2)
    assert len(calls) == 1

    calls.clear()
    steps = []
    result = tr.transcribe(long_wav, "local", "small", "pt", lambda f, label: steps.append(f))
    # Só o bloco 2 roda de novo; o último é silêncio puro e nem chega ao modelo.
    assert len(calls) == 1 and calls[0] == pytest.approx(blocks[1][1] - blocks[1][0], abs=0.01)
    assert [s.start for s in result.sentences] == [pytest.approx(b[0] + 1) for b in blocks[:2]]
    assert result.sentences[1].words[0].start == pytest.approx(blocks[1][0] + 1)
    assert result.language == "pt" and steps == sorted(steps) and steps[-1] == 1.0
    # Cada bloco que vai ao modelo tem no máximo ~11,5 min: a memória não cresce com o vídeo.
    assert max(b - a for a, b in blocks) <= tr.CHUNK_S + tr.SEARCH_S

    calls.clear()
    assert tr.transcribe(long_wav, "local", "small", "pt") == result      # tudo do cache
    assert calls == []
    tr.transcribe(long_wav, "local", "base", "pt")                       # outro modelo: transcreve
    assert len(calls) == 2


def test_frases_da_api_recebem_palavras_e_filtram_alucinacao():
    data = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": " Bom dia.", "no_speech_prob": 0.01, "avg_logprob": -0.2},
            {"start": 2.0, "end": 4.0, "text": " Obrigado.", "no_speech_prob": 0.9, "avg_logprob": -1.5},
            {"start": 4.0, "end": 6.0, "text": " a a a a a", "compression_ratio": 3.1},
            {"start": 6.0, "end": 8.0, "text": " Cultura é tudo.", "no_speech_prob": 0.1, "avg_logprob": -0.3},
        ],
        "words": [
            {"word": "Bom", "start": 0.1, "end": 0.5}, {"word": "dia.", "start": 0.6, "end": 1.2},
            {"word": "Obrigado.", "start": 2.5, "end": 3.0},
            {"word": "Cultura", "start": 6.1, "end": 6.6}, {"word": "é", "start": 6.7, "end": 6.8},
            {"word": "tudo.", "start": 6.9, "end": 7.5},
        ],
    }
    out = tr.sentences_from_api(data, offset=100.0)
    assert [s.text for s in out] == ["Bom dia.", "Cultura é tudo."]
    assert [w.text for w in out[1].words] == ["Cultura", "é", "tudo."]
    assert out[1].start == 106.0 and out[1].words[0].start == pytest.approx(106.1)


def verbose_json(text="Fala do CEO."):
    return {
        "language": "portuguese",
        "segments": [{"start": 1.0, "end": 3.0, "text": text, "no_speech_prob": 0.01, "avg_logprob": -0.2}],
        "words": [{"word": "Fala", "start": 1.0, "end": 1.5}, {"word": "do", "start": 1.6, "end": 1.8},
                  {"word": "CEO.", "start": 1.9, "end": 3.0}],
    }


def test_groq_espera_o_limite_gratuito_e_continua(long_wav):
    requests, sleeps = [], []

    def server(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 2:                      # 2ª chamada: limite por hora
            return httpx.Response(429, headers={"retry-after": "3"}, json={"error": {"message": "rate"}})
        return httpx.Response(200, json=verbose_json())

    http = httpx.Client(base_url="https://api.groq.com/openai/v1", transport=httpx.MockTransport(server))
    client = Groq(key="teste", http=http, sleep=sleeps.append)
    labels = []
    result = tr.transcribe(long_wav, "groq", "small", "pt", lambda f, label: labels.append(label), client=client)

    blocks = tr.chunk_bounds(long_wav, 1500)
    assert len(requests) == 3                       # 2 blocos com fala + 1 repetição; o silencioso não é enviado
    assert sum(sleeps) == pytest.approx(3, abs=0.01)
    assert any("Limite gratuito do Groq" in l for l in labels)
    assert [s.start for s in result.sentences] == [pytest.approx(b[0] + 1) for b in blocks[:2]]
    assert [w.text for w in result.sentences[0].words] == ["Fala", "do", "CEO."]

    body = requests[0].content
    assert b'name="timestamp_granularities[]"\r\n\r\nword' in body
    assert b'name="timestamp_granularities[]"\r\n\r\nsegment' in body
    assert b'name="language"\r\n\r\npt' in body and b'whisper-large-v3-turbo' in body
    assert b"fLaC" in body                          # o áudio vai em FLAC
    assert requests[0].headers["authorization"] == "Bearer teste"


def test_groq_erros_viram_mensagens_claras(long_wav):
    def client_with(response):
        http = httpx.Client(base_url="https://x", transport=httpx.MockTransport(lambda r: response))
        return Groq(key="k", http=http, sleep=lambda s: None)

    with pytest.raises(CloudError, match="recusada"):
        client_with(httpx.Response(401, json={})).transcribe(np.zeros(16000, np.float32), "pt", lambda m: None)
    with pytest.raises(CloudError, match="Limite diário"):
        client_with(httpx.Response(429, headers={"retry-after": "20000"})).transcribe(
            np.zeros(16000, np.float32), "pt", lambda m: None)


def test_groq_sem_chave_explica_o_que_fazer(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(CloudError, match="GROQ_API_KEY"):
        Groq()


def test_cancelar_durante_a_espera_do_limite(long_wav):
    http = httpx.Client(base_url="https://x", transport=httpx.MockTransport(
        lambda r: httpx.Response(429, headers={"retry-after": "600"})))
    client = Groq(key="k", http=http, sleep=lambda s: None)

    def progress(fraction, label):
        if "retomando" in label:
            raise Cancelled()
    with pytest.raises(Cancelled):
        tr.transcribe(long_wav, "groq", "small", "pt", progress, client=client)
