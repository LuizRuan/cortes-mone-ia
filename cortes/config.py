"""Parâmetros de corte e validação da entrada."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Formatos aceitos no upload. O ffmpeg lê muito mais que isso; a lista existe
# para dar um erro claro antes de gastar tempo com um arquivo que não é vídeo.
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]


class InvalidInput(ValueError):
    """Erro de entrada do usuário (arquivo ou parâmetro). A UI mostra a mensagem."""


class Cancelled(Exception):
    """Levantada pelo callback de progresso quando o usuário clica em Cancelar.

    Todo o trabalho longo chama o callback com frequência (por segmento de
    transcrição, a cada ~0,5 s de ffmpeg, a cada segundo de espera da API),
    então o cancelamento é atendido em poucos segundos e o ffmpeg em execução
    é encerrado junto.
    """


@dataclass
class CutParams:
    # --- Silêncio -----------------------------------------------------------
    # Volume abaixo do qual o áudio conta como silêncio. Mais perto de 0 = mais
    # agressivo (-25 dB corta até respiração; -45 dB só corta silêncio absoluto).
    silence_db: float = -35.0
    # Só pausas mais longas que isto são removidas.
    min_silence_s: float = 0.6
    # Margem preservada antes/depois de cada trecho mantido, para não comer sílabas.
    padding_s: float = 0.12
    # Além do volume, remove trechos em que o Whisper não encontrou fala
    # (música, ruído, respiração) — é o que funciona em gravações com ruído de fundo.
    remove_non_speech: bool = True

    # --- O que exportar -----------------------------------------------------
    export_full: bool = False         # vídeo inteiro sem os silêncios (lento em vídeo longo)
    export_highlights: bool = True    # clipes curtos dos melhores momentos
    num_highlights: int = 8           # quantas sugestões de corte a análise devolve
    clip_min_s: float = 20.0
    clip_max_s: float = 60.0
    vertical: bool = False            # recorte central 9:16 nos highlights

    # --- Transcrição --------------------------------------------------------
    # "groq": Whisper large-v3-turbo na nuvem (plano gratuito, exige GROQ_API_KEY).
    # "local": faster-whisper no computador, com o modelo `whisper_model`.
    transcriber: str = "local"
    whisper_model: str = "small"
    language: str | None = "pt"       # None = detecção automática

    # --- Exportação ---------------------------------------------------------
    crf: int = 20                     # qualidade H.264: 18 ≈ sem perda visível, 23 = padrão
    # "veryfast" codifica várias vezes mais rápido que "medium"; o custo é um
    # arquivo um pouco maior para a mesma qualidade.
    preset: str = "veryfast"
    # Limite do lado MENOR do vídeo, em pixels (1080 = Full HD; 0 = manter o
    # original). Exportar em 4K leva cerca do dobro do tempo e da memória de
    # 1080p, e as redes sociais reduzem para 1080p de qualquer forma.
    max_side: int = 1080

    def validate(self) -> None:
        if not (self.export_full or self.export_highlights):
            raise InvalidInput("Escolha pelo menos uma saída: vídeo sem silêncios ou highlights.")
        if not -80 <= self.silence_db <= -5:
            raise InvalidInput("A sensibilidade de silêncio deve ficar entre -80 e -5 dB.")
        if self.min_silence_s <= 0:
            raise InvalidInput("A duração mínima do silêncio deve ser maior que zero.")
        if self.padding_s < 0 or 2 * self.padding_s >= self.min_silence_s:
            raise InvalidInput(
                "A margem precisa ser menor que metade da duração mínima do silêncio "
                "(senão não sobra nada para cortar)."
            )
        if self.export_highlights:
            if self.num_highlights < 1:
                raise InvalidInput("Peça pelo menos 1 highlight.")
            if not 0 < self.clip_min_s <= self.clip_max_s:
                raise InvalidInput("O tamanho mínimo do clipe deve ser maior que zero e não passar do máximo.")
        if self.max_side != 0 and self.max_side < 240:
            raise InvalidInput("A resolução máxima deve ser 0 (original) ou pelo menos 240.")
        if self.transcriber not in ("local", "groq"):
            raise InvalidInput(f"Transcrição desconhecida: {self.transcriber}")
        if self.whisper_model not in WHISPER_MODELS:
            raise InvalidInput(f"Modelo Whisper desconhecido: {self.whisper_model}")

    @property
    def needs_transcript(self) -> bool:
        """A transcrição é a etapa mais lenta; só roda quando alguém vai usá-la."""
        return self.export_highlights or self.remove_non_speech


def check_video_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_file():
        raise InvalidInput(f"Arquivo não encontrado: {p}")
    if p.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise InvalidInput(
            f"Formato {p.suffix or '(sem extensão)'} não suportado. "
            f"Use: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return p
