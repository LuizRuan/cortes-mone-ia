"""Leitura de mídia com ffmpeg/ffprobe: inspeção, extração de áudio e silêncio."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import InvalidInput
from .segments import Interval


class FFmpegError(RuntimeError):
    pass


@dataclass
class VideoInfo:
    duration: float
    has_audio: bool
    # Usados pelo XML do Premiere; os padrões só valem se o ffprobe não informar.
    fps: float = 30.0
    width: int = 1920
    height: int = 1080
    audio_channels: int = 2
    sample_rate: int = 48000


def _fps(stream: dict) -> float:
    for key in ("avg_frame_rate", "r_frame_rate"):
        num, _, den = str(stream.get(key, "0/0")).partition("/")
        try:
            value = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            continue
        if 1 <= value <= 240:
            return value
    return 30.0


def _rotation(stream: dict) -> int:
    """Celular gravando em pé guarda o vídeo deitado + um aviso de rotação."""
    try:
        rotate = int(float(stream.get("tags", {}).get("rotate", 0)))
    except ValueError:
        rotate = 0
    for side in stream.get("side_data_list", []) or []:
        if "rotation" in side:
            rotate = int(float(side["rotation"]))
    return abs(rotate) % 180


# No Windows, ffmpeg/ffprobe rodam com prioridade abaixo do normal: usam a CPU
# que estiver livre, mas cedem a vez para o que o usuário estiver fazendo.
_LOW_PRIORITY = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


def lower_priority() -> None:
    """Baixa a prioridade deste processo (e do Whisper, que roda dentro dele).

    O processamento continua usando todos os núcleos quando a máquina está
    ociosa; a diferença é que navegador, IDE etc. passam na frente. Falhar aqui
    não pode impedir o app de abrir, por isso qualquer erro é ignorado.
    """
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
        else:
            os.nice(10)
    except Exception:
        pass


def _check_installed(tool: str) -> None:
    if shutil.which(tool) is None:
        raise FFmpegError(
            f"'{tool}' não foi encontrado. Instale o FFmpeg e confirme que ele está no PATH."
        )


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Executa ffmpeg/ffprobe e transforma falha em exceção com o final do log."""
    _check_installed(cmd[0])
    # Lista de argumentos (sem shell): caminhos com espaço ou acento funcionam
    # igual no Windows e no Linux, e nada do nome do arquivo é interpretado.
    proc = subprocess.run(
        cmd, capture_output=True, stdin=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="replace", creationflags=_LOW_PRIORITY,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"{cmd[0]} falhou:\n{proc.stderr[-1500:]}")
    return proc


def run_with_progress(cmd: list[str], on_time: Callable[[float], None]) -> None:
    """Executa o ffmpeg avisando, a cada ~0,5 s, quantos segundos de saída já foram gravados.

    Usa `-progress pipe:1`, que escreve pares chave=valor no stdout. O stderr vai
    para um arquivo temporário: se fosse um pipe que ninguém lê, um log grande
    travaria o ffmpeg.
    """
    _check_installed(cmd[0])
    cmd = [cmd[0], "-progress", "pipe:1", "-nostats", *cmd[1:]]
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=err, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", creationflags=_LOW_PRIORITY,
        )
        try:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit():   # microssegundos; "N/A" no início
                    on_time(int(value) / 1e6)
            code = proc.wait()
        finally:
            if proc.poll() is None:      # exceção no meio (ex.: cancelamento): não deixa órfão
                proc.kill()
        if code != 0:
            err.seek(0)
            log = err.read().decode("utf-8", errors="replace")
            raise FFmpegError(f"{cmd[0]} falhou:\n{log[-1500:]}")


def probe(path: Path) -> VideoInfo:
    """Confere que o arquivo é mesmo um vídeo e devolve o que o pipeline precisa."""
    try:
        proc = run([
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ])
    except FFmpegError as exc:
        if "não foi encontrado" in str(exc):
            raise
        # As últimas linhas do ffprobe dizem o motivo real (ex.: "moov atom not
        # found" = arquivo incompleto), então elas vão junto na mensagem.
        detail = " | ".join(str(exc).strip().splitlines()[-2:])[-300:]
        raise InvalidInput(
            "Não foi possível ler o arquivo — ele está corrompido, incompleto ou não é um vídeo. "
            f"(ffprobe: {detail})"
        ) from exc

    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    # Capas de álbum aparecem como stream de vídeo "attached_pic"; não contam.
    video = next(
        (s for s in streams
         if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")),
        None,
    )
    if video is None:
        raise InvalidInput("O arquivo não tem faixa de vídeo.")
    duration = float(data.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise InvalidInput("Não foi possível determinar a duração do vídeo.")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    width, height = int(video.get("width") or 1920), int(video.get("height") or 1080)
    if _rotation(video) == 90:
        width, height = height, width
    return VideoInfo(
        duration=duration,
        has_audio=audio is not None,
        fps=_fps(video),
        width=width,
        height=height,
        audio_channels=int((audio or {}).get("channels") or 2),
        sample_rate=int((audio or {}).get("sample_rate") or 48000),
    )


def extract_audio(video: Path, wav: Path, on_time: Callable[[float], None] | None = None) -> Path:
    """Extrai o áudio em WAV mono 16 kHz — o formato que o Whisper espera.

    `first_pts=0` preenche com silêncio qualquer atraso inicial da faixa de
    áudio, de modo que o tempo t do WAV seja o mesmo tempo t do vídeo. Sem isso,
    em arquivos cujo áudio começa depois do vídeo, todos os cortes sairiam
    deslocados.
    """
    run_with_progress([
        "ffmpeg", "-y", "-v", "error", "-i", str(video),
        "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
        "-af", "aresample=async=1:first_pts=0",
        "-c:a", "pcm_s16le", str(wav),
    ], on_time or (lambda t: None))
    return wav


_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silences(wav: Path, noise_db: float, min_silence_s: float, duration: float) -> list[Interval]:
    """Trechos com volume abaixo de `noise_db` por pelo menos `min_silence_s`.

    Usa o filtro `silencedetect` do ffmpeg, que mede o áudio real com precisão
    de amostra (bem mais exato que os timestamps do Whisper).
    """
    proc = run([
        "ffmpeg", "-v", "info", "-nostats", "-i", str(wav),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
        "-f", "null", "-",
    ])
    silences: list[Interval] = []
    start: float | None = None
    for line in proc.stderr.splitlines():
        if m := _SILENCE_START.search(line):
            start = max(0.0, float(m.group(1)))
        elif (m := _SILENCE_END.search(line)) and start is not None:
            silences.append((start, min(duration, float(m.group(1)))))
            start = None
    if start is not None:  # o arquivo terminou em silêncio
        silences.append((start, duration))
    return silences
