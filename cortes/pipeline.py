"""Orquestra o fluxo em duas etapas: analisar o vídeo e exportar os cortes escolhidos.

    analyze():  vídeo ─► áudio WAV ─┬─► silencedetect ─────────┐
                                    └─► Whisper (em blocos) ───┼─► trechos com fala
                                                │              │
                                                └─► sugestões de corte (LLM ou heurística)
    export():   sugestões escolhidas ─► ffmpeg (só a janela de cada corte) ─► corte_NN.mp4

Separar as etapas importa em vídeo longo: a análise de 4 h é o que demora; a
exportação de cada corte depende só da duração do corte, porque o ffmpeg salta
direto para o trecho em vez de decodificar o vídeo inteiro. Assim dá para
revisar as sugestões e exportar só as boas.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import media, premiere, segments
from .config import CutParams, InvalidInput, check_video_path
from .highlights import Highlight, select_highlights
from .render import render
from .transcribe import Transcript, transcribe

# progress(fração de 0 a 1, descrição da etapa)
Progress = Callable[[float, str], None]


@dataclass
class Analysis:
    src: Path
    out_dir: Path
    params: CutParams
    original_duration: float
    keep: list[segments.Interval]
    transcript: Transcript | None
    highlights: list[Highlight] = field(default_factory=list)
    highlight_method: str = ""
    report: Path | None = None
    video: media.VideoInfo | None = None     # formato do original (para o XML do Premiere)

    @property
    def kept_duration(self) -> float:
        return segments.total_duration(self.keep)


@dataclass
class Result:
    """Resultado de process(): análise + arquivos exportados."""
    analysis: Analysis
    full_video: Path | None = None
    highlight_files: list[Path] = field(default_factory=list)
    premiere_xml: Path | None = None

    # Atalhos usados pela CLI e pelos testes.
    @property
    def original_duration(self) -> float:
        return self.analysis.original_duration

    @property
    def kept_duration(self) -> float:
        return self.analysis.kept_duration

    @property
    def highlights(self) -> list[Highlight]:
        return self.analysis.highlights

    @property
    def highlight_method(self) -> str:
        return self.analysis.highlight_method

    @property
    def transcript(self) -> Transcript | None:
        return self.analysis.transcript

    @property
    def report(self) -> Path | None:
        return self.analysis.report

    @property
    def files(self) -> list[Path]:
        return ([self.full_video] if self.full_video else []) + self.highlight_files


def analyze(
    video_path: str | Path,
    out_dir: str | Path,
    params: CutParams | None = None,
    progress: Progress | None = None,
    transcriber: Callable[..., Transcript] | None = None,
    groq=None,
) -> Analysis:
    """Transcreve, acha os trechos com fala e sugere os cortes. Não exporta vídeo.

    `transcriber` e `groq` existem para os testes trocarem as partes que
    dependem de modelo ou de rede; em uso normal ficam None.
    """
    params = params or CutParams()
    notify = progress or (lambda fraction, label: None)

    params.validate()
    src = check_video_path(video_path)
    info = media.probe(src)
    if not info.has_audio:
        raise InvalidInput("O vídeo não tem faixa de áudio — não há o que analisar para cortar.")
    out = Path(out_dir)

    # Faixas da barra: áudio 0-8%, transcrição 8-85%, sugestões 85-100%.
    with tempfile.TemporaryDirectory(prefix="cortes_") as tmp:
        wav = media.extract_audio(
            src, Path(tmp) / "audio.wav",
            lambda t: notify(0.06 * min(1.0, t / info.duration), "Extraindo o áudio"),
        )
        notify(0.06, "Detectando silêncios")
        silences = media.detect_silences(wav, params.silence_db, params.min_silence_s, info.duration)

        transcript = None
        if params.needs_transcript:
            if transcriber is not None:
                transcript = transcriber(wav, params.whisper_model, params.language,
                                         lambda f: notify(0.08 + 0.77 * f, "Transcrevendo"))
            else:
                transcript = transcribe(
                    wav, params.transcriber, params.whisper_model, params.language,
                    lambda f, label: notify(0.08 + 0.77 * f, label), client=groq,
                )

    speech = transcript.speech_intervals() if (transcript and params.remove_non_speech) else None
    keep = segments.compute_keep(silences, info.duration, params.padding_s, speech, params.min_silence_s)
    if not keep:
        raise InvalidInput(
            "Nada restou depois do corte: nenhuma fala foi detectada. "
            "Diminua a sensibilidade de silêncio (ex.: -45 dB) ou desligue 'remover trechos sem fala'."
        )
    analysis = Analysis(src, out, params, info.duration, keep, transcript, video=info)

    if params.export_highlights:
        analysis.highlights, analysis.highlight_method = select_highlights(
            transcript.sentences, keep, params.num_highlights, params.clip_min_s, params.clip_max_s,
            groq=groq, progress=lambda f, label: notify(0.85 + 0.15 * f, label),
        )
        # Em ordem cronológica: mais fácil de revisar ao lado do vídeo.
        analysis.highlights.sort(key=lambda h: h.start)

    out.mkdir(parents=True, exist_ok=True)      # só agora: análise cancelada não deixa pasta vazia
    analysis.report = out / f"{src.stem}_relatorio.json"
    analysis.report.write_text(json.dumps({
        "arquivo": str(src),
        "duracao_original_s": round(info.duration, 2),
        "duracao_com_fala_s": round(analysis.kept_duration, 2),
        "metodo_highlights": analysis.highlight_method,
        "sugestoes": [asdict(h) for h in analysis.highlights],
        "idioma": transcript.language if transcript else None,
        "transcricao": [
            {"inicio": round(s.start, 2), "fim": round(s.end, 2), "texto": s.text}
            for s in (transcript.sentences if transcript else [])
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    notify(1.0, "Análise concluída")
    return analysis


def export(
    analysis: Analysis,
    chosen: list[int] | None = None,
    full_video: bool = False,
    progress: Progress | None = None,
    render_clips: bool = True,
) -> Result:
    """Exporta as sugestões de índice `chosen` (padrão: todas) e, se pedido, o vídeo inteiro sem silêncios.

    Sempre grava também o XML para o Premiere (instantâneo). Com
    `render_clips=False`, grava só o XML e não renderiza nenhum vídeo.
    """
    notify = progress or (lambda fraction, label: None)
    p, src, out = analysis.params, analysis.src, analysis.out_dir
    picks = list(range(len(analysis.highlights))) if chosen is None else sorted(set(chosen))
    jobs = (len(picks) + (1 if full_video else 0)) if render_clips else 0
    if render_clips and jobs == 0:
        raise InvalidInput("Marque pelo menos um corte para exportar.")
    result = Result(analysis)
    result.premiere_xml = premiere.write_xml(
        out / f"{src.stem}_premiere.xml", src, analysis.video or media.VideoInfo(analysis.original_duration, True),
        src.stem,
        [(f"Corte {k + 1:02d} — {analysis.highlights[k].title}", analysis.highlights[k].reason,
          segments.intersect(analysis.keep, [(analysis.highlights[k].start, analysis.highlights[k].end)]))
         for k in picks],
        full=analysis.keep,
    )
    if not render_clips:
        notify(1.0, "XML do Premiere gerado")
        return result
    done = 0

    def run(name: str, parts: list[segments.Interval], vertical: bool) -> Path:
        nonlocal done
        label = f"Exportando {name} ({done + 1} de {jobs})"
        base = done / jobs
        notify(base, label)
        path = render(src, parts, out / name, p.crf, p.preset, vertical, p.max_side,
                      lambda f: notify(base + f / jobs, label))
        done += 1
        return path

    for k in picks:
        h = analysis.highlights[k]
        # O corte é a janela do highlight já sem os silêncios internos.
        parts = segments.intersect(analysis.keep, [(h.start, h.end)])
        result.highlight_files.append(run(f"{src.stem}_corte_{k + 1:02d}.mp4", parts, p.vertical))
    if full_video:
        result.full_video = run(f"{src.stem}_sem_silencio.mp4", analysis.keep, vertical=False)

    notify(1.0, "Concluído")
    return result


def process(
    video_path: str | Path,
    out_dir: str | Path,
    params: CutParams | None = None,
    progress: Progress | None = None,
    transcriber: Callable[..., Transcript] | None = None,
    groq=None,
) -> Result:
    """Análise + exportação de todas as sugestões, numa chamada (usado pela CLI)."""
    params = params or CutParams()
    notify = progress or (lambda fraction, label: None)
    analysis = analyze(video_path, out_dir, params, lambda f, label: notify(0.7 * f, label), transcriber, groq)
    return export(analysis, None if params.export_highlights else [], params.export_full,
                  lambda f, label: notify(0.7 + 0.3 * f, label))
