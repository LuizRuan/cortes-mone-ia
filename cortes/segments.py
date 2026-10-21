"""Aritmética de intervalos de tempo — funções puras, sem ffmpeg nem IA.

Um intervalo é uma tupla (início, fim) em segundos. Toda a decisão de "o que
fica no vídeo" é feita aqui, o que permite testá-la sem processar mídia.
"""
from __future__ import annotations

Interval = tuple[float, float]

# Trechos menores que isto não rendem nem dois quadros de vídeo; são descartados.
MIN_KEEP_S = 0.05


def merge(intervals: list[Interval], gap: float = 0.0) -> list[Interval]:
    """Ordena e funde intervalos sobrepostos ou separados por até `gap` segundos."""
    out: list[Interval] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if out and start - out[-1][1] <= gap:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def invert(intervals: list[Interval], total: float) -> list[Interval]:
    """Complemento dentro de [0, total]: o que NÃO está em `intervals`."""
    out, cursor = [], 0.0
    for start, end in merge(intervals):
        if start > cursor:
            out.append((cursor, min(start, total)))
        cursor = max(cursor, end)
    if cursor < total:
        out.append((cursor, total))
    return [(s, e) for s, e in out if e > s]


def intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    """Partes presentes em `a` e em `b` (ambos já fundidos e ordenados)."""
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        start, end = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if end > start:
            out.append((start, end))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def total_duration(intervals: list[Interval]) -> float:
    return sum(end - start for start, end in intervals)


def compute_keep(
    silences: list[Interval],
    duration: float,
    padding: float,
    speech: list[Interval] | None = None,
    min_silence: float = 0.0,
) -> list[Interval]:
    """Decide quais trechos do vídeo original são mantidos.

    silences: trechos de volume baixo (ffmpeg silencedetect), já filtrados pela
              duração mínima.
    speech:   intervalos das palavras reconhecidas pelo Whisper. Se informado,
              pausas entre palavras maiores que `min_silence` também saem, mesmo
              que haja som (música, ruído) nelas.
    padding:  margem preservada em volta de cada trecho mantido.
    """
    # Encolher o silêncio em `padding` de cada lado = deixar margem na fala.
    # Nas pontas do vídeo não há fala do outro lado, então o silêncio sai inteiro.
    shrunk = [
        (s + padding if s > 0 else 0.0,
         e - padding if e < duration - MIN_KEEP_S else duration)
        for s, e in silences
    ]
    keep = invert(shrunk, duration)

    if speech is not None:
        # Os timestamps de palavra do Whisper erram por ~0,1-0,2 s, então a fala
        # recebe a mesma margem antes de virar critério de corte.
        padded = [(max(0.0, s - padding), min(duration, e + padding)) for s, e in speech]
        # Pausas de até min_silence entre palavras são fala contínua. O gap é
        # medido depois da margem, daí o desconto de 2*padding.
        spoken = merge(padded, gap=max(0.0, min_silence - 2 * padding))
        keep = intersect(keep, spoken)

    return [(s, e) for s, e in keep if e - s >= MIN_KEEP_S]
