import pytest

from cortes.config import CutParams, InvalidInput, check_video_path
from cortes.segments import compute_keep, intersect, invert, merge, total_duration


def test_merge_junta_sobrepostos_e_proximos():
    assert merge([(5, 6), (0, 2), (1, 3)]) == [(0, 3), (5, 6)]
    assert merge([(0, 1), (1.2, 2)], gap=0.3) == [(0, 2)]
    assert merge([(3, 3), (4, 2)]) == []          # vazios e invertidos somem


def test_invert_cobre_inicio_meio_e_fim():
    assert invert([(2, 3), (5, 6)], 10) == [(0, 2), (3, 5), (6, 10)]
    assert invert([(0, 4)], 4) == []
    assert invert([], 4) == [(0, 4)]


def test_intersect():
    assert intersect([(0, 5), (8, 12)], [(3, 9), (11, 20)]) == [(3, 5), (8, 9), (11, 12)]


def test_keep_remove_silencio_deixando_margem():
    keep = compute_keep([(3, 5), (8, 10)], duration=12, padding=0.1)
    assert keep == [(0, 3.1), (4.9, 8.1), (9.9, 12)]


def test_keep_silencio_nas_pontas_sai_inteiro():
    # Sem sobrar 0,1 s de "margem" no começo e no fim do vídeo.
    keep = compute_keep([(0, 2), (8, 10.0)], duration=10.02, padding=0.1)
    assert keep == [(1.9, 8.1)]


def test_keep_remove_som_sem_fala_quando_ha_transcricao():
    # 0-2 silêncio, 2-8 fala, 8-12 música (há som, mas nenhuma palavra).
    words = [(2.0, 4.0), (4.2, 8.0)]             # pausa de 0,2 s não é corte
    keep = compute_keep([(0, 2)], 12, padding=0.1, speech=words, min_silence=0.6)
    assert keep == [(1.9, 8.1)]
    # Sem a transcrição, a música fica.
    assert compute_keep([(0, 2)], 12, padding=0.1) == [(1.9, 12)]


def test_keep_vazio_quando_tudo_e_silencio():
    assert compute_keep([(0, 10)], 10, padding=0.1) == []
    assert total_duration([]) == 0


@pytest.mark.parametrize("changes", [
    {"export_full": False, "export_highlights": False},
    {"padding_s": 0.3, "min_silence_s": 0.6},     # margem come o silêncio inteiro
    {"clip_min_s": 90, "clip_max_s": 60},
    {"silence_db": 10},
    {"whisper_model": "gigante"},
])
def test_parametros_invalidos_sao_recusados(changes):
    with pytest.raises(InvalidInput):
        CutParams(**changes).validate()


def test_extensao_nao_suportada(tmp_path):
    doc = tmp_path / "nota.txt"
    doc.write_text("x")
    with pytest.raises(InvalidInput, match="não suportado"):
        check_video_path(doc)
    with pytest.raises(InvalidInput, match="não encontrado"):
        check_video_path(tmp_path / "sumiu.mp4")
