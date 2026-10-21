"""Escolha dos melhores momentos (highlights) a partir da transcrição.

Três caminhos, com a mesma saída:

1. LLM do Groq (gratuito), quando existe GROQ_API_KEY — o limite gratuito é
   de 8 mil tokens por minuto, então a transcrição é lida em janelas de
   ~10 min; cada janela sugere até 3 trechos e os melhores do vídeo inteiro
   são escolhidos no fim. Respostas ficam em cache: reanalisar o mesmo vídeo
   não gasta a cota de novo.
2. Claude, quando existe ANTHROPIC_API_KEY — lê a transcrição inteira de uma vez.
3. Heurística local, sem rede — pontua cada frase por densidade de
   palavras-chave do vídeo, ritmo de fala e marcas de ênfase. É um critério
   grosseiro: serve de fallback, não substitui o LLM.

Nos dois casos um highlight é sempre uma sequência de frases inteiras, então o
clipe nunca começa nem termina no meio de uma frase.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from .config import Cancelled
from .segments import Interval
from .transcribe import CACHE_DIR, Sentence

LLM_MODEL = os.environ.get("CORTES_LLM_MODEL", "claude-sonnet-5-5")


@dataclass
class Highlight:
    start: float       # tempo no vídeo ORIGINAL
    end: float
    score: float       # 0 a 10
    title: str
    reason: str


# ---------------------------------------------------------------------------
# Duração "editada": quanto um trecho dura depois de removidos os silêncios.
# Os limites mínimo/máximo do clipe valem para o que o espectador vai assistir.
# ---------------------------------------------------------------------------

def kept_clock(keep: list[Interval]) -> Callable[[float], float]:
    """Devolve K(t): quantos segundos mantidos existem antes do instante t."""
    starts = [s for s, _ in keep]
    before = [0.0]
    for s, e in keep:
        before.append(before[-1] + (e - s))

    def clock(t: float) -> float:
        i = bisect_right(starts, t) - 1
        if i < 0:
            return 0.0
        s, e = keep[i]
        return before[i] + min(t, e) - s

    return clock


def fit_window(
    sentences: list[Sentence], i: int, j: int,
    clock: Callable[[float], float], min_s: float, max_s: float,
) -> tuple[int, int] | None:
    """Ajusta o trecho de frases i..j para caber entre min_s e max_s.

    Encolhe pelo fim se passou do máximo; cresce (primeiro para a frente, depois
    para trás) se ficou abaixo do mínimo. Devolve None se não houver ajuste.
    """
    def dur(a: int, b: int) -> float:
        return clock(sentences[b].end) - clock(sentences[a].start)

    while j > i and dur(i, j) > max_s:
        j -= 1
    if dur(i, j) > max_s:          # uma única frase maior que o clipe máximo
        return None
    while dur(i, j) < min_s and j + 1 < len(sentences) and dur(i, j + 1) <= max_s:
        j += 1
    while dur(i, j) < min_s and i > 0 and dur(i - 1, j) <= max_s:
        i -= 1
    return (i, j) if dur(i, j) >= min_s else None


def _take_best(candidates: list[tuple[float, int, int, str, str]], n: int,
               sentences: list[Sentence]) -> list[Highlight]:
    """Pega os n candidatos de maior nota que não se sobrepõem."""
    chosen: list[tuple[float, int, int, str, str]] = []
    for cand in sorted(candidates, key=lambda c: -c[0]):
        _, i, j, _, _ = cand
        if all(j < ci or i > cj for _, ci, cj, _, _ in chosen):
            chosen.append(cand)
        if len(chosen) == n:
            break
    return [
        Highlight(sentences[i].start, sentences[j].end, round(score, 1), title, reason)
        for score, i, j, title, reason in chosen
    ]


# ---------------------------------------------------------------------------
# Caminho 1: LLM
# ---------------------------------------------------------------------------

_TOOL = {
    "name": "registrar_highlights",
    "description": "Registra os trechos escolhidos como highlights do vídeo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "highlights": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "inicio": {"type": "integer", "description": "Número da primeira frase do trecho"},
                        "fim": {"type": "integer", "description": "Número da última frase do trecho (inclusive)"},
                        "titulo": {"type": "string", "description": "Título curto e chamativo para o clipe"},
                        "motivo": {"type": "string", "description": "Uma frase: por que este trecho se destaca"},
                        "nota": {"type": "number", "description": "0 a 10: potencial como clipe curto"},
                    },
                    "required": ["inicio", "fim", "titulo", "motivo", "nota"],
                },
            }
        },
        "required": ["highlights"],
    },
}

_SYSTEM = (
    "Você é um editor de vídeo que seleciona cortes para Shorts, Reels e TikTok. "
    "Um bom corte funciona sozinho, sem o resto do vídeo: abre com um gancho "
    "(pergunta, afirmação forte, promessa), desenvolve UMA ideia completa e "
    "termina numa conclusão, não no meio do raciocínio. Prefira momentos com "
    "informação concreta, histórias, opiniões fortes, humor ou emoção. Evite "
    "saudações, avisos, pedidos de inscrição e trechos que dependem de contexto anterior."
)


def _pick_with_llm(sentences, clock, n, min_s, max_s, client) -> list[tuple[float, int, int, str, str]]:
    def stamp(t: float) -> str:
        return f"{int(t // 60):02d}:{int(t % 60):02d}"

    lines = "\n".join(
        f"[{k}] ({stamp(clock(s.start))}) {s.text}" for k, s in enumerate(sentences)
    )
    prompt = (
        f"Transcrição numerada por frase, com o instante (mm:ss) em que cada frase começa:\n\n"
        f"{lines}\n\n"
        f"Escolha os {n + 2} melhores trechos, sem sobreposição. Cada trecho é uma "
        f"sequência contínua de frases e deve durar entre {min_s:.0f} e {max_s:.0f} segundos "
        f"(calcule pela diferença entre os instantes). Registre-os com a ferramenta."
    )
    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=2000,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": _TOOL["name"]},  # força saída estruturada
        messages=[{"role": "user", "content": prompt}],
    )
    items = next(b.input for b in response.content if b.type == "tool_use")["highlights"]

    # A resposta do modelo é entrada não confiável: índices são conferidos e a
    # duração é reajustada aqui, não importa o que ele tenha calculado.
    candidates = []
    for item in items:
        i, j = int(item["inicio"]), int(item["fim"])
        if not 0 <= i <= j < len(sentences):
            continue
        fitted = fit_window(sentences, i, j, clock, min_s, max_s)
        if fitted:
            score = max(0.0, min(10.0, float(item["nota"])))
            candidates.append((score, *fitted, str(item["titulo"]), str(item["motivo"])))
    return candidates


# ---------------------------------------------------------------------------
# Caminho 2: heurística local
# ---------------------------------------------------------------------------

_STOPWORDS = set("""
a o e é de do da dos das em no na nos nas um uma uns umas por para pra com sem que se
como mais mas ou eu tu ele ela nós vocês você eles elas me te lhe nos isso isto aquilo
esse essa este esta aquele aquela seu sua meu minha foi ser são era tem têm ter tinha
está estão estar estava vai vou vão ir já não sim também muito muita pouco só ainda
então aqui ali lá quando onde porque porquê qual quem sobre entre até depois antes
gente coisa coisas assim tipo bem agora cara né tá ah eh
the and for that this with you your are was were have has had not but from they them
what when where which will would can could just about into than then there their it's
""".split())

_HOOKS = (
    "segredo", "importante", "dica", "erro", "nunca", "sempre", "melhor", "pior",
    "verdade", "problema", "resultado", "atenção", "por isso", "na prática",
    "exemplo", "imagina", "descobri", "ninguém", "todo mundo", "o motivo",
    "secret", "important", "mistake", "never", "always", "best", "worst", "truth",
)

_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)


def _sentence_scores(sentences: list[Sentence]) -> list[float]:
    """Nota de 0 a 1 por frase. Cada componente é normalizado pelo maior valor do vídeo."""
    tokens = [[t for t in _TOKEN.findall(s.text.lower()) if len(t) >= 4 and t not in _STOPWORDS]
              for s in sentences]
    freq = Counter(t for toks in tokens for t in toks)

    topic, rate, emphasis = [], [], []
    for s, toks in zip(sentences, tokens):
        n_words = max(1, len(s.text.split()))
        # Palavras que se repetem ao longo do vídeo indicam o assunto central.
        topic.append(sum(math.log1p(freq[t]) for t in toks) / n_words)
        # Fala rápida costuma marcar trechos mais animados.
        rate.append(n_words / max(0.5, s.end - s.start))
        text = s.text.lower()
        emphasis.append(
            ("?" in text) + ("!" in text) + bool(re.search(r"\d", text))
            + sum(h in text for h in _HOOKS)
        )

    def norm(values: list[float]) -> list[float]:
        top = max(values) or 1.0
        return [v / top for v in values]

    return [0.5 * t + 0.2 * r + 0.3 * e for t, r, e in zip(norm(topic), norm(rate), norm(emphasis))]


def _pick_with_heuristic(sentences, clock, min_s, max_s, lo=0, hi=None) -> list[tuple[float, int, int, str, str]]:
    """Candidatos que começam entre as frases lo e hi (padrão: todas)."""
    scores = _sentence_scores(sentences)
    candidates = []
    for i in range(lo, len(sentences) if hi is None else hi):
        weighted = total = 0.0
        for j in range(i, len(sentences)):
            d = sentences[j].end - sentences[j].start
            weighted += scores[j] * d
            total += d
            dur = clock(sentences[j].end) - clock(sentences[i].start)
            if dur > max_s:
                break
            if dur >= min_s and total > 0:
                # Nota do trecho = média das frases, ponderada pela duração.
                title = sentences[i].text[:60].rstrip() + ("…" if len(sentences[i].text) > 60 else "")
                candidates.append((10 * weighted / total, i, j, title, "Pontuação heurística local"))
    return candidates


# ---------------------------------------------------------------------------
# Caminho 1: LLM gratuito do Groq, em janelas
# ---------------------------------------------------------------------------

WINDOW_S = 600.0     # ~10 min de fala ≈ 4-5 mil tokens: cabe nos 8 mil/min do plano gratuito
OVERLAP_S = 60.0     # um bom trecho na divisa entre janelas não se perde

_GROQ_SCHEMA = {
    "type": "object",
    "properties": {
        "trechos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "inicio": {"type": "integer"},
                    "fim": {"type": "integer"},
                    "titulo": {"type": "string"},
                    "motivo": {"type": "string"},
                    "nota": {"type": "number"},
                },
                "required": ["inicio", "fim", "titulo", "motivo", "nota"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["trechos"],
    "additionalProperties": False,
}


def _hms(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def _windows(sentences: list[Sentence]) -> list[tuple[int, int]]:
    """Faixas [lo, hi) de frases, cada uma cobrindo ~WINDOW_S segundos, com sobreposição."""
    out, lo = [], 0
    while lo < len(sentences):
        hi = lo
        while hi < len(sentences) and sentences[hi].start < sentences[lo].start + WINDOW_S:
            hi += 1
        out.append((lo, hi))
        if hi >= len(sentences):
            break
        nxt = hi
        while nxt > lo + 1 and sentences[nxt - 1].start > sentences[hi - 1].end - OVERLAP_S:
            nxt -= 1
        lo = nxt
    return out


def _cached_chat(client, system: str, user: str, tick) -> dict:
    key = hashlib.sha1(f"{getattr(client, 'model', '')}|{system}|{user}".encode()).hexdigest()
    path = CACHE_DIR / "llm" / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    answer = client.chat_json(system, user, _GROQ_SCHEMA, tick)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(answer, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return answer


def _pick_with_groq(sentences, clock, min_s, max_s, client, notify) -> tuple[list, str]:
    windows = _windows(sentences)
    candidates, done = [], 0
    failure = None
    for k, (lo, hi) in enumerate(windows):
        label = f"Escolhendo os melhores momentos — parte {k + 1} de {len(windows)}"
        notify(k / len(windows), label)
        if failure is None:
            lines = "\n".join(f"[{i}] ({_hms(sentences[i].start)}) {sentences[i].text}" for i in range(lo, hi))
            user = (
                f"Trecho de uma gravação longa ({_hms(sentences[lo].start)} a {_hms(sentences[hi - 1].end)}), "
                f"numerado por frase:\n\n{lines}\n\n"
                f"Indique até 3 trechos deste pedaço que funcionem sozinhos como corte curto. "
                f"Cada trecho é uma sequência contínua de frases (use os números entre colchetes) "
                f"e deve durar entre {min_s:.0f} e {max_s:.0f} segundos. Se nada aqui for bom, "
                f"devolva uma lista vazia. Nota de 0 a 10 comparando com um corte excelente, "
                f"não só com o resto deste pedaço. Título e motivo em português."
            )
            try:
                answer = _cached_chat(client, _SYSTEM, user, lambda msg: notify(k / len(windows), f"{msg} ({label.lower()})"))
                for item in answer.get("trechos", []):
                    i, j = int(item["inicio"]), int(item["fim"])
                    if not lo <= i <= j < hi:      # resposta é entrada não confiável
                        continue
                    fitted = fit_window(sentences, i, j, clock, min_s, max_s)
                    if fitted:
                        score = max(0.0, min(10.0, float(item["nota"])))
                        candidates.append((score, *fitted, str(item["titulo"]), str(item["motivo"])))
                done += 1
                continue
            except Cancelled:
                raise
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
        # Janela sem LLM (falhou nesta ou numa anterior): heurística só nela.
        candidates += _pick_with_heuristic(sentences, clock, min_s, max_s, lo, hi)

    if failure is None:
        return candidates, f"LLM gratuito do Groq ({len(windows)} partes)"
    return candidates, f"LLM do Groq em {done} de {len(windows)} partes; o resto por heurística ({failure})"


# ---------------------------------------------------------------------------

def select_highlights(
    sentences: list[Sentence],
    keep: list[Interval],
    n: int,
    min_s: float,
    max_s: float,
    client=None,
    groq=None,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[list[Highlight], str]:
    """Devolve (highlights em ordem de nota, descrição do método usado).

    Prioridade: Groq (GROQ_API_KEY) → Claude (ANTHROPIC_API_KEY) → heurística.
    `client` (Anthropic) e `groq` substituem os clientes reais nos testes.
    Qualquer falha de LLM cai na heurística e o motivo vai na descrição.
    """
    if not sentences:
        return [], "nenhuma fala encontrada"
    clock = kept_clock(keep)
    notify = progress or (lambda fraction, label: None)

    from .cloud import api_key as groq_key
    if groq is None and client is None and groq_key():
        from .cloud import Groq
        groq = Groq()
    if groq is not None:
        candidates, method = _pick_with_groq(sentences, clock, min_s, max_s, groq, notify)
        return _take_best(candidates, n, sentences), method

    method = "heurística local (defina GROQ_API_KEY para usar o LLM gratuito)"
    if client is None and os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()

    if client is not None:
        try:
            candidates = _pick_with_llm(sentences, clock, n, min_s, max_s, client)
            if candidates:
                return _take_best(candidates, n, sentences), f"LLM ({LLM_MODEL})"
            method = "heurística local (o LLM não devolveu trechos válidos)"
        except Exception as exc:  # rede, chave inválida, resposta fora do formato…
            method = f"heurística local (LLM falhou: {type(exc).__name__}: {exc})"

    candidates = _pick_with_heuristic(sentences, clock, min_s, max_s)
    return _take_best(candidates, n, sentences), method
