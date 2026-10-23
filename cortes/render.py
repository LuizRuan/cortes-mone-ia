"""Corte, junção e exportação em MP4 com ffmpeg.

Por que chamar o ffmpeg direto, em vez de MoviePy ou ffmpeg-python: o MoviePy
passa cada quadro pelo Python (lento em vídeos longos) e o ffmpeg-python está
sem manutenção. O que é preciso aqui — trim + concat — cabe em um filtro.

Como o corte é feito
--------------------
Cada trecho mantido vira um par `trim`/`atrim` e o filtro `concat` emenda tudo.
O `atrim` corta na amostra exata e o `concat` realinha áudio e vídeo a cada
emenda, então o resultado não perde sincronia mesmo com centenas de cortes
(o que acontece ao cortar com `-c copy` ou ao emendar arquivos AAC soltos).

Um vídeo longo pode ter centenas de trechos, e um filtro com todos eles estoura
o limite de tamanho da linha de comando do Windows. Por isso os trechos são
processados em lotes: cada lote gera um arquivo intermediário (H.264 + áudio
PCM sem perdas) e, no fim, os lotes são unidos copiando o vídeo e codificando
o áudio em AAC uma única vez.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from .media import run, run_with_progress
from .segments import Interval, total_duration

CHUNK = 30  # trechos por chamada do ffmpeg


def _fit(max_side: int, vertical: bool) -> str:
    """Filtro final de vídeo: resolução, pixels quadrados e formato de cor.

    libx264 exige dimensões pares; yuv420p é o que todo player e rede social
    aceita. `max_side` limita o lado menor (1080 → Full HD em paisagem ou
    retrato) e nunca amplia um vídeo que já é menor que isso.
    """
    if vertical:
        # Recorte central 9:16 (Shorts/Reels/TikTok), válido para qualquer proporção de origem.
        w = min(1080, max_side or 1080)
        return (f"crop='min(iw,ih*9/16)':'min(ih,iw*16/9)',"
                f"scale={w}:{w * 16 // 9},setsar=1,format=yuv420p")
    if max_side:
        m = max_side
        return (f"scale='if(gt(iw,ih),-2,trunc(min(iw,{m})/2)*2)'"
                f":'if(gt(iw,ih),trunc(min(ih,{m})/2)*2,-2)',setsar=1,format=yuv420p")
    return "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,format=yuv420p"


def _filter_graph(segments: list[Interval], offset: float, fit: str) -> str:
    """Monta o filter_complex de um lote. Tempos relativos a `offset` (o -ss do lote)."""
    n = len(segments)
    parts = [
        f"[0:v]split={n}" + "".join(f"[v{k}]" for k in range(n)),
        f"[0:a]aresample=async=1:first_pts=0,asplit={n}" + "".join(f"[a{k}]" for k in range(n)),
    ]
    for k, (start, end) in enumerate(segments):
        s, e = start - offset, end - offset
        parts.append(f"[v{k}]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS[tv{k}]")
        parts.append(f"[a{k}]atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS[ta{k}]")
    pairs = "".join(f"[tv{k}][ta{k}]" for k in range(n))
    parts.append(f"{pairs}concat=n={n}:v=1:a=1[cv][a]")
    # A redução de resolução vem DEPOIS do corte: só os quadros que ficam são redimensionados.
    parts.append(f"[cv]{fit}[v]")
    return ";".join(parts)


def render(
    src: Path,
    segments: list[Interval],
    dst: Path,
    crf: int = 20,
    preset: str = "veryfast",
    vertical: bool = False,
    max_side: int = 1080,
    progress: Callable[[float], None] | None = None,
    video_filter: str = "",
    batch_size: int | None = None,
) -> Path:
    """Exporta para `dst` (MP4) apenas os `segments` de `src`, na ordem dada.

    `segments` deve estar ordenado no tempo e sem sobreposição.
    `progress` recebe a fração concluída (0 a 1) continuamente, não só por lote.
    """
    if not segments:
        raise ValueError("Nenhum trecho para exportar.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    batch = CHUNK if batch_size is None else max(1, min(CHUNK, batch_size))
    chunks = [segments[k:k + batch] for k in range(0, len(segments), batch)]
    notify = progress or (lambda fraction: None)
    total = total_duration(segments)
    fit = video_filter + _fit(max_side, vertical)

    # Temporários ao lado da saída: mesmo disco, e somem sozinhos ao final.
    with tempfile.TemporaryDirectory(dir=dst.parent, prefix=".cortes_") as tmp_name:
        tmp = Path(tmp_name)
        names, done = [], 0.0
        for k, chunk in enumerate(chunks):
            name = f"parte_{k:04d}.mkv"
            offset = chunk[0][0]
            chunk_dur = total_duration(chunk)
            run_with_progress([
                "ffmpeg", "-y", "-v", "error",
                # -ss antes do -i: o ffmpeg salta direto para o lote e mesmo
                # assim corta no quadro exato (decodifica a partir do keyframe
                # anterior e descarta o que vem antes).
                "-ss", f"{offset:.6f}", "-t", f"{chunk[-1][1] - offset + 0.5:.6f}",
                "-i", str(src),
                "-filter_complex", _filter_graph(chunk, offset, fit),
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", str(crf), "-preset", preset,
                "-c:a", "pcm_s16le",
                str(tmp / name),
            ], lambda t, base=done, limit=chunk_dur: notify(0.97 * (base + min(t, limit)) / total))
            names.append(name)
            done += chunk_dur

        # A lista usa nomes relativos (resolvidos a partir da pasta da lista),
        # o que dispensa escapar caminhos do Windows.
        (tmp / "lista.txt").write_text("".join(f"file '{n}'\n" for n in names), encoding="utf-8")
        notify(0.97)
        run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(tmp / "lista.txt"),
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
            # faststart põe o índice no início do arquivo: o vídeo começa a tocar
            # na web antes de terminar de baixar.
            "-movflags", "+faststart",
            str(dst),
        ])
    notify(1.0)
    return dst
