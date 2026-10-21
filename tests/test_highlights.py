from types import SimpleNamespace

from cortes.highlights import fit_window, kept_clock, select_highlights
from cortes.transcribe import Sentence


def frases(n=20, dur=5.0):
    """n frases de `dur` segundos, coladas uma na outra."""
    out = [Sentence(k * dur, (k + 1) * dur, f"frase comum número {k}") for k in range(n)]
    # Trecho claramente mais forte no meio (frases 8 a 11).
    for k in range(8, 12):
        out[k].text = "Qual é o segredo do investimento? O erro que 90% comete no investimento!"
    return out


FULL = [(0.0, 100.0)]


class FakeClaude:
    """Imita client.messages.create devolvendo um bloco tool_use."""
    def __init__(self, highlights=None, error=None):
        self.highlights, self.error, self.calls = highlights, error, 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return SimpleNamespace(content=[
            SimpleNamespace(type="tool_use", input={"highlights": self.highlights})
        ])


def test_kept_clock_desconta_trechos_removidos():
    clock = kept_clock([(0, 10), (20, 30)])
    assert clock(5) == 5
    assert clock(15) == 10      # dentro do trecho removido
    assert clock(25) == 15
    assert clock(99) == 20


def test_fit_window_encolhe_e_cresce():
    s, clock = frases(), kept_clock(FULL)
    assert fit_window(s, 0, 19, clock, 20, 30) == (0, 5)      # 100 s → 30 s
    assert fit_window(s, 4, 4, clock, 20, 30) == (4, 7)       # 5 s → 20 s
    assert fit_window(s, 19, 19, clock, 20, 30) == (16, 19)   # cresce para trás no fim
    assert fit_window(s, 0, 0, clock, 1, 3) is None           # frase maior que o máximo


def test_heuristica_acha_o_trecho_forte_sem_sobrepor(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    found, method = select_highlights(frases(), FULL, n=3, min_s=20, max_s=30)
    assert "heurística" in method
    assert len(found) == 3
    assert (found[0].start, found[0].end) == (40.0, 60.0)     # frases 8 a 11
    spans = sorted((h.start, h.end) for h in found)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    assert all(20 <= h.end - h.start <= 30 for h in found)


def test_duracao_do_clipe_conta_o_tempo_ja_sem_silencio(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Metade de cada frase é silêncio removido: 20 s no ar = 40 s de original.
    keep = [(k * 5.0, k * 5.0 + 2.5) for k in range(20)]
    found, _ = select_highlights(frases(), keep, n=1, min_s=20, max_s=30)
    clock = kept_clock(keep)
    assert 20 <= clock(found[0].end) - clock(found[0].start) <= 30
    assert found[0].end - found[0].start >= 37.5


def test_llm_resposta_e_validada_e_ajustada():
    fake = FakeClaude([
        {"inicio": 8, "fim": 11, "titulo": "O segredo", "motivo": "gancho forte", "nota": 9.5},
        {"inicio": 0, "fim": 19, "titulo": "Longo demais", "motivo": "x", "nota": 7},   # será encolhido
        {"inicio": 9, "fim": 10, "titulo": "Sobrepõe o 1º", "motivo": "x", "nota": 6},  # descartado
        {"inicio": 50, "fim": 60, "titulo": "Índice inexistente", "motivo": "x", "nota": 10},
    ])
    found, method = select_highlights(frases(), FULL, n=3, min_s=20, max_s=30, client=fake)
    assert method.startswith("LLM")
    assert [h.title for h in found] == ["O segredo", "Longo demais"]
    assert (found[1].start, found[1].end) == (0.0, 30.0)


def test_llm_com_falha_cai_na_heuristica():
    fake = FakeClaude(error=RuntimeError("sem rede"))
    found, method = select_highlights(frases(), FULL, n=2, min_s=20, max_s=30, client=fake)
    assert fake.calls == 1
    assert "LLM falhou" in method and "sem rede" in method
    assert len(found) == 2


def test_sem_fala_nao_ha_highlight():
    assert select_highlights([], FULL, 3, 20, 30) == ([], "nenhuma fala encontrada")


# ---------------------------------------------------------------------------
# LLM gratuito do Groq, em janelas
# ---------------------------------------------------------------------------
import re

import pytest

from cortes import highlights as hl
from cortes.config import Cancelled


@pytest.fixture(autouse=True)
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(hl, "CACHE_DIR", tmp_path / "cache")


def palestra(horas=4, dur=5.0):
    """Frases de 5 s cobrindo `horas` horas."""
    n = int(horas * 3600 / dur)
    return [Sentence(k * dur, (k + 1) * dur, f"frase {k} sobre a cultura da empresa") for k in range(n)]


class FakeGroq:
    """Responde cada janela apontando as 6 primeiras frases dela, e uma resposta inválida."""
    model = "fake"

    def __init__(self, fail_after=None):
        self.calls, self.fail_after = [], fail_after

    def chat_json(self, system, user, schema, tick):
        assert schema["additionalProperties"] is False      # formato estrito
        self.calls.append(user)
        if self.fail_after is not None and len(self.calls) > self.fail_after:
            raise RuntimeError("limite diário")
        idx = [int(i) for i in re.findall(r"^\[(\d+)\]", user, flags=re.M)]
        lo = idx[0]
        return {"trechos": [
            {"inicio": lo, "fim": lo + 5, "titulo": f"Bloco {lo}", "motivo": "bom", "nota": 5 + (lo % 7) / 2},
            {"inicio": 999999, "fim": 1000000, "titulo": "fora", "motivo": "x", "nota": 10},
        ]}


def test_janelas_cobrem_tudo_com_sobreposicao():
    s = palestra()
    windows = hl._windows(s)
    assert windows[0][0] == 0 and windows[-1][1] == len(s)
    for (lo, hi), (lo2, hi2) in zip(windows, windows[1:]):
        assert s[hi - 1].end - s[lo].start <= hl.WINDOW_S + 5
        assert s[hi - 1].end - s[lo2].start >= hl.OVERLAP_S - 5     # sobreposição
    assert 25 <= len(windows) <= 28                                  # ~27 pedidos para 4 h


def test_groq_escolhe_os_melhores_do_video_inteiro_e_usa_cache():
    s = palestra()
    fake = FakeGroq()
    found, method = select_highlights(s, [(0.0, 4 * 3600.0)], n=8, min_s=20, max_s=60, groq=fake)
    assert "Groq" in method and len(found) == 8
    assert all(20 <= h.end - h.start <= 60 for h in found)
    assert all(h.title != "fora" for h in found)                     # índice inválido descartado
    assert [h.score for h in found] == sorted((h.score for h in found), reverse=True)
    n_calls = len(fake.calls)
    # Cada pedido cabe com folga no limite de 8 mil tokens/min (~4 caracteres por token).
    assert max(len(u) for u in fake.calls) / 4 < 6000

    select_highlights(s, [(0.0, 4 * 3600.0)], n=8, min_s=20, max_s=60, groq=fake)
    assert len(fake.calls) == n_calls                                 # reanálise sem gastar cota


def test_groq_falhando_no_meio_completa_com_heuristica():
    s = palestra(horas=1)
    fake = FakeGroq(fail_after=2)
    found, method = select_highlights(s, [(0.0, 3600.0)], n=5, min_s=20, max_s=60, groq=fake)
    assert "em 2 de" in method and "heurística" in method and "limite diário" in method
    assert len(fake.calls) == 3                     # parou de chamar depois da falha
    assert len(found) == 5


def test_cancelar_interrompe_a_escolha():
    class Cancela(FakeGroq):
        def chat_json(self, *a):
            raise Cancelled()
    with pytest.raises(Cancelled):
        select_highlights(palestra(horas=1), [(0.0, 3600.0)], 3, 20, 60, groq=Cancela())
