"""Teste de ponta a ponta com vídeo sintético e ffmpeg de verdade.

O Whisper é trocado por uma transcrição pronta (baixar o modelo em todo teste
seria lento); o resto — extração de áudio, silencedetect, corte, emenda e
exportação — roda como em produção.
"""
import json
import shutil
import subprocess

import pytest

from cortes.config import CutParams, InvalidInput
from cortes.media import detect_silences, extract_audio
from cortes.pipeline import process
from cortes.render import render
from cortes.transcribe import Sentence, Transcript, Word

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg não instalado")

# Roteiro do vídeo de teste (40 s). Tom de 440 Hz faz o papel de fala;
# 220 Hz é "música": tem som, mas a transcrição não tem palavras ali.
FALA = [(2, 8), (10, 18), (23, 34)]
MUSICA = (18, 22)
DURACAO = 40
P = 0.12  # margem padrão


def make_video(path, tone_expr, duration, extra=()):
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc=s=321x240:r=30:d={duration}",   # largura ímpar de propósito
        "-f", "lavfi", "-i", f"aevalsrc='{tone_expr}':s=44100:d={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p", "-c:a", "aac", *extra, str(path),
    ], check=True)
    return path


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    fala = "+".join(f"between(t,{a},{b})" for a, b in FALA)
    expr = f"0.5*sin(2*PI*440*t)*({fala})+0.5*sin(2*PI*220*t)*between(t,{MUSICA[0]},{MUSICA[1]})"
    return make_video(tmp_path_factory.mktemp("src") / "aula teste.mov", expr, DURACAO)


def fake_whisper(wav, model, language, progress):
    """Frases de 2 s com 4 palavras cada, cobrindo exatamente os trechos de FALA."""
    sentences = []
    for a, b in FALA:
        t = float(a)
        while t < b:
            end = min(t + 2, b)
            step = (end - t) / 4
            words = [Word(t + k * step, t + (k + 1) * step, f"palavra{k}") for k in range(4)]
            sentences.append(Sentence(t, end, f"Frase que começa em {t:.0f} segundos.", words))
            t = end
    return Transcript("pt", sentences)


def test_remove_silencio_e_musica_e_gera_highlights(video, tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    steps = []
    params = CutParams(num_highlights=2, clip_min_s=4, clip_max_s=8, vertical=True, preset="ultrafast",
                       export_full=True)
    result = process(video, tmp_path, params, lambda f, label: steps.append(f), fake_whisper)

    # Sobram só os três blocos de fala, cada um com a margem dos dois lados.
    expected = sum(b - a for a, b in FALA) + len(FALA) * 2 * P
    assert result.kept_duration == pytest.approx(expected, abs=0.05)

    streams = probe(result.full_video)
    assert streams["video"]["codec_name"] == "h264"
    assert streams["video"]["pix_fmt"] == "yuv420p"
    assert int(streams["video"]["width"]) % 2 == 0
    assert streams["audio"]["codec_name"] == "aac"
    assert float(streams["video"]["duration"]) == pytest.approx(expected, abs=0.1)
    assert float(streams["audio"]["duration"]) == pytest.approx(expected, abs=0.1)

    # O áudio exportado não tem mais nenhuma pausa longa.
    wav = extract_audio(result.full_video, tmp_path / "saida.wav")
    assert detect_silences(wav, -35, 0.6, expected) == []

    # faststart: o índice (moov) vem antes dos dados (mdat).
    head = result.full_video.read_bytes()
    assert head.find(b"moov") < head.find(b"mdat")

    assert len(result.highlight_files) == 2
    for clip in result.highlight_files:
        s = probe(clip)
        assert (int(s["video"]["width"]), int(s["video"]["height"])) == (1080, 1920)
        assert 4 - 0.1 <= float(s["video"]["duration"]) <= 8 + 0.1

    report = json.loads(result.report.read_text(encoding="utf-8"))
    assert len(report["sugestoes"]) == 2 and report["transcricao"]
    assert steps == sorted(steps) and steps[-1] == 1.0     # o progresso só avança


def test_sem_transcricao_corta_so_por_volume(video, tmp_path):
    def nao_chamar(*args):
        raise AssertionError("o Whisper não deveria rodar neste modo")

    params = CutParams(export_highlights=False, remove_non_speech=False, preset="ultrafast", export_full=True)
    result = process(video, tmp_path, params, transcriber=nao_chamar)
    # A música (18-22) fica: ela emenda com a fala de 10-18.
    expected = (8 - 2) + (22 - 10) + (34 - 23) + 3 * 2 * P
    assert result.kept_duration == pytest.approx(expected, abs=0.05)
    assert float(probe(result.full_video)["video"]["duration"]) == pytest.approx(expected, abs=0.1)


def test_muitos_cortes_passam_por_varios_lotes_sem_perder_sincronia(tmp_path):
    # 45 rajadas de 1 s separadas por 1 s de silêncio → 45 trechos → 2 lotes.
    src = make_video(tmp_path / "rajadas.mp4", "0.5*sin(2*PI*440*t)*lt(mod(t,2),1)", 90)
    params = CutParams(export_highlights=False, remove_non_speech=False, preset="ultrafast", export_full=True)
    result = process(src, tmp_path / "out", params)
    expected = 45 * 1 + 89 * P + P          # a primeira rajada começa em t=0: sem margem antes
    streams = probe(result.full_video)
    assert float(streams["video"]["duration"]) == pytest.approx(expected, abs=0.15)
    assert abs(float(streams["video"]["duration"]) - float(streams["audio"]["duration"])) < 0.05


def test_video_sem_audio_e_arquivo_invalido(tmp_path):
    mudo = tmp_path / "mudo.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=1",
                    "-pix_fmt", "yuv420p", str(mudo)], check=True)
    with pytest.raises(InvalidInput, match="áudio"):
        process(mudo, tmp_path / "out")

    falso = tmp_path / "falso.mp4"
    falso.write_text("isto não é um vídeo")
    with pytest.raises(InvalidInput, match="corrompido"):
        process(falso, tmp_path / "out")


@pytest.mark.parametrize("size, max_side, expected", [
    ("3840x2160", 1080, (1920, 1080)),     # 4K paisagem → Full HD
    ("2160x3840", 1080, (1080, 1920)),     # 4K retrato → Full HD em pé
    ("640x360", 1080, (640, 360)),         # menor que o limite: não amplia
    ("3840x2160", 0, (3840, 2160)),        # 0 = manter o original
])
def test_resolucao_maxima(tmp_path, size, max_side, expected):
    src = tmp_path / "fonte.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=s={size}:r=5:d=2",
        "-f", "lavfi", "-i", "sine=d=2", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(src),
    ], check=True)
    out = render(src, [(0.0, 1.0)], tmp_path / "saida.mp4", preset="ultrafast", max_side=max_side)
    video = probe(out)["video"]
    assert (int(video["width"]), int(video["height"])) == expected


def test_analisar_e_exportar_so_os_cortes_marcados(video, tmp_path, monkeypatch):
    from cortes import highlights
    from cortes.pipeline import analyze, export
    monkeypatch.setattr(highlights, "CACHE_DIR", tmp_path / "cache")

    class FakeGroq:
        model = "fake"
        def chat_json(self, system, user, schema, tick):
            return {"trechos": [{"inicio": 0, "fim": 2, "titulo": "Abertura", "motivo": "gancho", "nota": 8},
                                {"inicio": 5, "fim": 7, "titulo": "Meio", "motivo": "história", "nota": 9}]}

    params = CutParams(num_highlights=5, clip_min_s=4, clip_max_s=8, preset="ultrafast")
    a = analyze(video, tmp_path / "out", params, transcriber=fake_whisper, groq=FakeGroq())
    assert [h.title for h in a.highlights] == ["Abertura", "Meio"]       # ordem cronológica
    assert "Groq" in a.highlight_method
    assert list((tmp_path / "out").glob("*.mp4")) == []                   # a análise não exporta nada

    result = export(a, [1])
    assert [f.name for f in result.files] == ["aula teste_corte_02.mp4"]
    assert 4 - 0.1 <= float(probe(result.files[0])["video"]["duration"]) <= 8 + 0.1

    with pytest.raises(InvalidInput, match="Marque"):
        export(a, [])
