"""XML para o Premiere (formato Final Cut Pro 7).

Sem Premiere aqui, a validação usa um leitor independente desse formato:
o adaptador fcp_xml do OpenTimelineIO (projeto da Pixar/ASWF). Se ele não
estiver instalado, só os testes de estrutura rodam.
"""
import xml.etree.ElementTree as ET

import pytest

from cortes.media import VideoInfo
from cortes.premiere import _rate, path_url, write_xml

INFO = VideoInfo(duration=4 * 3600.0, has_audio=True, fps=29.98, width=3840, height=2160,
                 audio_channels=2, sample_rate=48000)
SRC = r"C:\Users\SuporteMonetali\Vídeos\CEO cultura 4h.MOV"
CUT1 = [(100.0, 112.5), (113.2, 130.0), (131.0, 140.0)]
CUT2 = [(7200.0, 7230.0)]
FULL = [(0.5, 50.0), (51.0, 14399.0)]


@pytest.fixture
def xml_file(tmp_path):
    return write_xml(tmp_path / "x.xml", SRC, INFO, "CEO cultura 4h",
                     [("Corte 01 — Cultura", "gancho forte", CUT1), ("Corte 02 — Missão", "história", CUT2)],
                     full=FULL)


def test_caminho_do_windows_vira_url_que_o_premiere_le():
    assert path_url(SRC) == "file://localhost/C:/Users/SuporteMonetali/V%C3%ADdeos/CEO%20cultura%204h.MOV"


def test_taxa_de_quadros_do_celular_vira_29_97():
    assert _rate(29.98)[1:] == (30, True)
    assert _rate(25.0)[1:] == (25, False)
    assert _rate(59.9)[1:] == (60, True)


def test_estrutura_das_sequencias(xml_file):
    text = xml_file.read_text(encoding="utf-8")
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>')
    root = ET.fromstring(text.split("\n", 2)[2])
    seqs = root.findall("./project/children/sequence")
    assert [s.findtext("name") for s in seqs] == [
        "Corte 01 — Cultura", "Corte 02 — Missão", "CEO cultura 4h — gravação inteira sem pausas"]

    fps = 30000 / 1001
    first = seqs[0]
    items = first.findall("./media/video/track/clipitem")
    assert [(int(c.findtext("in")), int(c.findtext("out"))) for c in items] == [
        (round(a * fps), round(b * fps)) for a, b in CUT1]
    # Clipes colados um no outro, começando do zero, sem buracos.
    starts = [int(c.findtext("start")) for c in items]
    ends = [int(c.findtext("end")) for c in items]
    assert starts[0] == 0 and starts[1:] == ends[:-1]
    assert int(first.findtext("duration")) == ends[-1]
    # Estéreo: duas trilhas de áudio, uma por canal, com os mesmos trechos.
    atracks = first.findall("./media/audio/track")
    assert len(atracks) == 2
    assert [int(c.findtext("./sourcetrack/trackindex")) for t in atracks for c in t.findall("clipitem")][:1] == [1]
    # O arquivo é descrito uma vez só; o resto apenas o referencia.
    full_files = [f for f in root.iter("file") if f.find("pathurl") is not None]
    assert len(full_files) == 1
    assert full_files[0].findtext("./media/video/samplecharacteristics/width") == "3840"
    assert first.find("marker/comment").text == "gancho forte"


def test_leitor_independente_entende_o_xml(xml_file):
    otio = pytest.importorskip("opentimelineio")
    result = otio.adapters.read_from_file(str(xml_file), adapter_name="fcp_xml")
    timelines = list(result.find_children(descended_from_type=otio.schema.Timeline)) \
        if isinstance(result, otio.schema.SerializableCollection) else [result]
    assert [t.name for t in timelines][:2] == ["Corte 01 — Cultura", "Corte 02 — Missão"]

    first = timelines[0]
    assert len(first.video_tracks()) == 1 and len(first.audio_tracks()) == 2
    clips = list(first.video_tracks()[0].find_clips())
    # Os pontos de entrada lidos de volta batem com os tempos pedidos (precisão de 1 quadro).
    for clip, (a, b) in zip(clips, CUT1):
        assert clip.source_range.start_time.to_seconds() == pytest.approx(a, abs=1 / 29)
        assert clip.source_range.end_time_exclusive().to_seconds() == pytest.approx(b, abs=1 / 29)
        assert clip.media_reference.target_url.endswith("CEO%20cultura%204h.MOV")
    assert first.duration().to_seconds() == pytest.approx(sum(b - a for a, b in CUT1), abs=0.1)
