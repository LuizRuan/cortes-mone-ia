"""Transcrição com timestamps por palavra, em blocos de ~10 minutos.

Por que em blocos: o faster-whisper calcula a análise espectral do áudio
inteiro de uma vez. Medido aqui: 1 hora de áudio chega a 3,2 GB de RAM só
nessa etapa — 4 horas passariam de 12 GB. Em blocos de 10 min o pico fica
constante, seja o vídeo de 5 minutos ou de 5 horas.

Os cortes entre blocos caem no trecho mais silencioso perto da marca de
10 min, para não partir uma palavra ao meio. Cada bloco é guardado em cache
assim que termina: cancelar, fechar o app ou bater no limite diário da API
não perde o que já foi feito — a próxima execução continua de onde parou.

Dois motores, com a mesma saída:
- local: faster-whisper (pesos do Whisper da OpenAI no CTranslate2, sem PyTorch);
- groq:  Whisper large-v3-turbo na nuvem, plano gratuito (ver cloud.py).
"""
from __future__ import annotations

import gc
import hashlib
import json
import os
import tempfile
import wave
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from .segments import Interval

def _cache_dir() -> Path:
    configured = os.environ.get("CORTES_CACHE_DIR", "").strip()
    return Path(configured).expanduser() if configured else Path(tempfile.gettempdir()) / "cortes_ia_transcricoes"


CACHE_DIR = _cache_dir()
CHUNK_S = 600.0      # tamanho-alvo de cada bloco
SEARCH_S = 90.0      # janela em volta do alvo onde se procura o ponto mais silencioso
RATE = 16000

# progress(fração 0-1 da transcrição inteira, rótulo)
Progress = Callable[[float, str], None]


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Sentence:
    """Um segmento do Whisper — em geral uma frase ou oração."""
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    sentences: list[Sentence]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.sentences)

    def speech_intervals(self) -> list[Interval]:
        """Intervalo de cada palavra reconhecida; base para achar trechos sem fala."""
        words = [(w.start, w.end) for s in self.sentences for w in s.words]
        # Sem timestamps de palavra (não deveria acontecer), cai para a frase.
        return words or [(s.start, s.end) for s in self.sentences]


# ---------------------------------------------------------------------------
# Leitura do WAV em pedaços
# ---------------------------------------------------------------------------

def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def read_wav(path: Path, start: float = 0.0, end: float | None = None) -> np.ndarray:
    """Lê só o trecho [start, end) do WAV mono 16 kHz / 16 bits como float32 em [-1, 1].

    O faster-whisper aceita um caminho de arquivo, mas aí decodifica com o PyAV,
    e a combinação faster-whisper 1.2 + PyAV 19 quebra com
    "open() got an unexpected keyword argument 'metadata_errors'". Como o áudio
    já foi convertido pelo ffmpeg para o formato exato que o modelo espera,
    entregamos as amostras prontas.
    """
    with wave.open(str(path), "rb") as w:
        if (w.getnchannels(), w.getframerate(), w.getsampwidth()) != (1, RATE, 2):
            raise ValueError(f"WAV fora do formato esperado (mono, 16 kHz, 16 bits): {path}")
        total = w.getnframes()
        first = min(total, max(0, int(start * RATE)))
        last = total if end is None else min(total, max(first, int(end * RATE)))
        w.setpos(first)
        frames = w.readframes(last - first)
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def _frame_rms(audio: np.ndarray, frame_s: float = 0.05) -> np.ndarray:
    n = int(frame_s * RATE)
    usable = len(audio) // n * n
    if usable == 0:
        return np.zeros(1, dtype=np.float32)
    return np.sqrt(np.mean(audio[:usable].reshape(-1, n) ** 2, axis=1))


def chunk_bounds(path: Path, duration: float, target: float = CHUNK_S, search: float = SEARCH_S) -> list[Interval]:
    """Divide o áudio em blocos de ~`target` s, cortando no ponto mais silencioso perto de cada marca.

    Depende só do áudio (não dos parâmetros de corte), então os mesmos blocos —
    e o mesmo cache — servem para qualquer sensibilidade escolhida depois.
    """
    cuts, cursor = [0.0], 0.0
    while duration - cursor > target + search:
        lo, hi = cursor + target - search, cursor + target + search / 3
        rms = _frame_rms(read_wav(path, lo, hi))
        # Média móvel de 0,4 s: procura uma pausa, não um único quadro quieto.
        smooth = np.convolve(rms, np.ones(8) / 8, mode="valid")
        cut = round(lo + (int(np.argmin(smooth)) + 4) * 0.05, 2)
        cuts.append(cut)
        cursor = cut
    cuts.append(duration)
    return list(zip(cuts, cuts[1:]))


def is_silent(audio: np.ndarray) -> bool:
    """Menos de 1% do bloco acima de -40 dBFS: não há fala para transcrever (nem pagar)."""
    return float(np.mean(_frame_rms(audio) > 0.01)) < 0.01


# ---------------------------------------------------------------------------
# Cache por bloco
# ---------------------------------------------------------------------------

def _audio_id(path: Path) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        while block := f.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()[:20]


def _read_cache(path: Path) -> Transcript | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Transcript(data["language"], [
            Sentence(s["start"], s["end"], s["text"], [Word(**w) for w in s["words"]])
            for s in data["sentences"]
        ])
    except (OSError, ValueError, KeyError, TypeError):
        return None      # não existe ou está corrompido: transcreve de novo


def _write_cache(path: Path, part: Transcript) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(part), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass             # sem cache o resultado é o mesmo, só mais lento da próxima vez


# ---------------------------------------------------------------------------
# Motores
# ---------------------------------------------------------------------------

def _load_model(size: str):
    """Carrega o faster-whisper (o download ocorre no primeiro uso)."""
    import ctranslate2
    from faster_whisper import WhisperModel

    if ctranslate2.get_cuda_device_count() > 0:
        return WhisperModel(size, device="cuda", compute_type="float16")
    # int8 reduz memória e tempo em CPU com perda desprezível de precisão.
    # O padrão da biblioteca são 4 threads; usamos ~1 por núcleo físico.
    threads = max(4, (os.cpu_count() or 4) // 2)
    return WhisperModel(size, device="cpu", compute_type="int8", cpu_threads=threads)


def _local_engine(model_size: str):
    model = _load_model(model_size)

    def run(audio: np.ndarray, offset: float, language: str | None, tick: Callable[[float], None]) -> Transcript:
        segments, info = model.transcribe(
            audio,
            language=language,
            word_timestamps=True,
            # Gulosa (o padrão é beam_size=5): bem mais rápida, e para decidir
            # cortes importa onde há fala e o sentido, não cada palavra perfeita.
            beam_size=1,
            # O VAD pula trechos sem voz: evita frases "inventadas" em silêncio
            # e o tempo gasto transcrevendo nada.
            vad_filter=True,
            condition_on_previous_text=False,
        )
        sentences = []
        for seg in segments:          # gerador: a transcrição acontece aqui
            text = seg.text.strip()
            if text:
                words = [Word(offset + w.start, offset + w.end, w.word.strip()) for w in (seg.words or [])]
                sentences.append(Sentence(offset + seg.start, offset + seg.end, text, words))
            if info.duration:
                tick(min(1.0, seg.end / info.duration))
        return Transcript(info.language, sentences)

    return run


def sentences_from_api(data: dict, offset: float) -> list[Sentence]:
    """Converte o verbose_json do Whisper (OpenAI/Groq) em frases com palavras.

    A API devolve frases e palavras em listas separadas; cada palavra vai para a
    frase que contém o seu ponto médio. Frases que o próprio Whisper marca como
    provável não-fala (silêncio, música) ou repetitivas são descartadas — sem o
    VAD local, é o filtro contra texto inventado.
    """
    words = sorted(data.get("words") or [], key=lambda w: w["start"])
    out, k = [], 0
    for seg in data.get("segments") or []:
        text = (seg.get("text") or "").strip()
        bogus = (
            (seg.get("no_speech_prob", 0) > 0.6 and seg.get("avg_logprob", 0) < -1.0)
            or seg.get("compression_ratio", 0) > 2.4
        )
        start, end = float(seg["start"]), float(seg["end"])
        mine = []
        while k < len(words) and (words[k]["start"] + words[k]["end"]) / 2 < end:
            w = words[k]
            if (w["start"] + w["end"]) / 2 >= start:
                mine.append(Word(offset + w["start"], offset + w["end"], str(w["word"]).strip()))
            k += 1
        if text and not bogus:
            out.append(Sentence(offset + start, offset + end, text, mine))
    return out


def _groq_engine(client):
    from .cloud import Groq

    client = client or Groq()

    def run(audio: np.ndarray, offset: float, language: str | None, tick, wait_tick) -> Transcript:
        data = client.transcribe(audio, language, wait_tick)
        tick(1.0)
        return Transcript(data.get("language") or language or "", sentences_from_api(data, offset))

    return run


# ---------------------------------------------------------------------------

def transcribe(
    wav: Path,
    backend: str = "local",
    model_size: str = "small",
    language: str | None = None,
    progress: Progress | None = None,
    client=None,
) -> Transcript:
    """Transcreve o WAV inteiro, bloco a bloco. `client` substitui o Groq nos testes."""
    notify = progress or (lambda fraction, label: None)
    model_name = model_size if backend == "local" else "groq-whisper"
    name = "Groq (nuvem)" if backend == "groq" else f"Whisper {model_size} (local)"

    duration = wav_duration(wav)
    notify(0.0, "Dividindo o áudio em blocos")
    blocks = chunk_bounds(wav, duration)
    audio_id = _audio_id(wav)
    engine = None
    sentences: list[Sentence] = []
    found_language = None

    try:
        for k, (a, b) in enumerate(blocks):
            label = f"Transcrevendo com {name} — bloco {k + 1} de {len(blocks)}"
            base, span = a / duration, (b - a) / duration
            notify(base, label)
            cache = CACHE_DIR / f"{audio_id}_{a:.2f}_{b:.2f}_{model_name}_{language or 'auto'}.json"
            part = _read_cache(cache)
            if part is None:
                audio = read_wav(wav, a, b)
                if is_silent(audio):
                    part = Transcript(language or "", [])
                else:
                    if engine is None:
                        engine = _local_engine(model_size) if backend == "local" else _groq_engine(client)
                    tick = lambda f, base=base, span=span, label=label: notify(base + span * f, label)
                    if backend == "local":
                        part = engine(audio, a, language, tick)
                    else:
                        part = engine(audio, a, language, tick,
                                      lambda msg, base=base, k=k: notify(base, f"{msg} (bloco {k + 1} de {len(blocks)})"))
                del audio
                _write_cache(cache, part)
            sentences.extend(part.sentences)
            found_language = found_language or part.language or None
    finally:
        # Solta o modelo (centenas de MB) antes da exportação, a outra etapa pesada.
        del engine
        gc.collect()

    notify(1.0, "Transcrição concluída")
    return Transcript(found_language or language or "", sentences)
