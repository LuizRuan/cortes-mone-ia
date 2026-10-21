"""Uso pela linha de comando:  python cli.py video.mp4 --saida saida/

Rode `python cli.py --help` para ver todos os parâmetros.
"""
from __future__ import annotations

import argparse
import sys

from cortes.cloud import CloudError
from cortes.config import WHISPER_MODELS, CutParams, InvalidInput
from cortes.media import FFmpegError, lower_priority
from cortes.pipeline import process


def main() -> int:
    d = CutParams()  # os padrões da CLI são os mesmos da biblioteca
    ap = argparse.ArgumentParser(description="Cortes automáticos de vídeo com IA.")
    ap.add_argument("video", help="arquivo .mp4, .mov, .avi, .mkv ou .webm")
    ap.add_argument("--saida", default="saida", help="pasta de saída (padrão: saida/)")
    ap.add_argument("--silencio-db", type=float, default=d.silence_db,
                    help="volume abaixo do qual é silêncio; mais perto de 0 corta mais")
    ap.add_argument("--silencio-min", type=float, default=d.min_silence_s,
                    help="pausas mais longas que isto (s) são removidas")
    ap.add_argument("--margem", type=float, default=d.padding_s,
                    help="margem (s) mantida em volta da fala")
    ap.add_argument("--manter-sem-fala", action="store_true",
                    help="não remove música/ruído sem fala; corta só por volume")
    ap.add_argument("--video-completo", action="store_true",
                    help="exporta também o vídeo inteiro sem silêncios (lento em vídeo longo)")
    ap.add_argument("--highlights", type=int, default=d.num_highlights,
                    help="quantidade de cortes sugeridos e exportados (0 desliga)")
    ap.add_argument("--nuvem", action="store_true",
                    help="transcreve no Groq (gratuito; exige a variável GROQ_API_KEY)")
    ap.add_argument("--clipe-min", type=float, default=d.clip_min_s, help="duração mínima do clipe (s)")
    ap.add_argument("--clipe-max", type=float, default=d.clip_max_s, help="duração máxima do clipe (s)")
    ap.add_argument("--vertical", action="store_true", help="highlights em 9:16 (recorte central)")
    ap.add_argument("--modelo", default=d.whisper_model, choices=WHISPER_MODELS)
    ap.add_argument("--idioma", default=d.language, help="pt, en, es… ou 'auto'")
    ap.add_argument("--crf", type=int, default=d.crf, help="qualidade H.264 (menor = melhor)")
    ap.add_argument("--resolucao", type=int, default=d.max_side,
                    help="limite do lado menor em pixels (1080 = Full HD; 0 = original)")
    a = ap.parse_args()

    params = CutParams(
        silence_db=a.silencio_db, min_silence_s=a.silencio_min, padding_s=a.margem,
        remove_non_speech=not a.manter_sem_fala,
        export_full=a.video_completo, transcriber="groq" if a.nuvem else "local",
        export_highlights=a.highlights > 0, num_highlights=max(1, a.highlights),
        clip_min_s=a.clipe_min, clip_max_s=a.clipe_max, vertical=a.vertical,
        whisper_model=a.modelo, language=None if a.idioma == "auto" else a.idioma,
        crf=a.crf, max_side=a.resolucao,
    )
    lower_priority()
    shown = [""]

    def show(fraction: float, label: str) -> None:
        line = f"[{fraction:4.0%}] {label}"
        if line != shown[0]:            # o progresso chega várias vezes por segundo
            shown[0] = line
            print(line, flush=True)

    try:
        result = process(a.video, a.saida, params, progress=show)
    except (InvalidInput, FFmpegError, CloudError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1

    print(f"\nOriginal: {result.original_duration:.1f}s → sem silêncios: {result.kept_duration:.1f}s")
    if params.export_highlights:
        print(f"Highlights via {result.highlight_method}")
    for f in result.files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
