"""Cliente mínimo da API do Groq (plano gratuito): Whisper e modelo de linguagem.

Por que Groq: um único cadastro gratuito, sem cartão, dá acesso ao Whisper
large-v3-turbo (melhor que os modelos que cabem num notebook) e a um LLM bom o
bastante para escolher cortes. A API segue o formato da OpenAI.

O plano gratuito tem limites por hora e por dia (ex.: 2 h de áudio por hora no
Whisper, 8 mil tokens por minuto no LLM). Este cliente não tenta evitá-los:
quando a API responde 429, ele espera o tempo que ela pede, mostrando a
contagem regressiva no progresso, e continua. Se a espera passar de ~1 h
(limite diário), ele para com uma mensagem clara — o que já foi transcrito
fica no cache e a próxima execução continua de onde parou.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Callable

import httpx
import numpy as np

BASE_URL = "https://api.groq.com/openai/v1"
WHISPER_MODEL = os.environ.get("CORTES_GROQ_WHISPER", "whisper-large-v3-turbo")
LLM_MODEL = os.environ.get("CORTES_GROQ_LLM", "openai/gpt-oss-120b")

# tick(mensagem): chamado durante esperas, ~1x por segundo. Pode levantar
# Cancelled, e é assim que o botão Cancelar interrompe uma espera longa.
Tick = Callable[[str], None]


class CloudError(RuntimeError):
    """Erro da API com mensagem pronta para mostrar ao usuário."""


def api_key() -> str | None:
    return os.environ.get("GROQ_API_KEY", "").strip() or None


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(1.0, float(response.headers.get("retry-after", "")))
    except ValueError:
        return 60.0


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except Exception:
        return response.text[:300]


def flac_bytes(audio: np.ndarray) -> bytes:
    """Amostras float32 16 kHz mono → FLAC (sem perdas, ~metade do tamanho do WAV).

    10 min viram ~10 MB, abaixo do limite de 25 MB por arquivo do plano gratuito.
    """
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
         "-c:a", "flac", "-f", "flac", "pipe:1"],
        input=pcm, capture_output=True,
        creationflags=getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0),
    )
    if proc.returncode != 0:
        raise CloudError(f"Falha ao preparar o áudio para envio: {proc.stderr.decode(errors='replace')[-300:]}")
    return proc.stdout


class Groq:
    def __init__(
        self,
        key: str | None = None,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_wait_s: float = 65 * 60,
    ):
        key = key or api_key()
        if not key:
            raise CloudError(
                "Para usar a nuvem, defina a variável GROQ_API_KEY com a sua chave do Groq "
                "(console.groq.com → API Keys) e reinicie o app."
            )
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=httpx.Timeout(300, connect=20))
        self.http.headers["Authorization"] = f"Bearer {key}"
        self.model = LLM_MODEL
        self.sleep = sleep
        self.max_wait_s = max_wait_s

    def _wait(self, seconds: float, tick: Tick, reason: str) -> None:
        left = float(seconds)
        while left > 0:
            tick(f"{reason} — retomando em {int(left // 60):02d}:{int(left % 60):02d}")
            step = min(1.0, left)
            self.sleep(step)
            left -= step

    def _post(self, path: str, tick: Tick, **kwargs) -> dict:
        failures = 0
        while True:
            try:
                response = self.http.post(path, **kwargs)
            except httpx.TransportError as exc:
                failures += 1
                if failures > 3:
                    raise CloudError(f"Sem conexão com o Groq ({type(exc).__name__}). Verifique a internet.") from exc
                self._wait(5 * failures, tick, "Falha de rede")
                continue

            if response.status_code == 200:
                return response.json()
            if response.status_code == 429:
                wait = _retry_after(response)
                if wait > self.max_wait_s:
                    raise CloudError(
                        f"Limite diário do plano gratuito do Groq atingido (libera em ~{wait / 3600:.1f} h). "
                        "O que já foi processado está salvo; rode de novo depois para continuar."
                    )
                self._wait(wait, tick, "Limite gratuito do Groq")
                continue
            if response.status_code >= 500 and failures < 3:
                failures += 1
                self._wait(5 * failures, tick, f"Groq instável ({response.status_code})")
                continue
            if response.status_code == 401:
                raise CloudError("A chave do Groq foi recusada. Confira o valor de GROQ_API_KEY.")
            raise CloudError(f"O Groq respondeu {response.status_code}: {_error_message(response)}")

    def transcribe(self, audio: np.ndarray, language: str | None, tick: Tick) -> dict:
        """Transcreve um bloco de áudio. Devolve o verbose_json (segments + words)."""
        data = {
            "model": WHISPER_MODEL,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"],
            "temperature": "0",
        }
        if language:
            data["language"] = language
        files = {"file": ("bloco.flac", flac_bytes(audio), "audio/flac")}
        return self._post("/audio/transcriptions", tick, data=data, files=files)

    def chat_json(self, system: str, user: str, schema: dict, tick: Tick) -> dict:
        """Uma pergunta ao LLM com resposta obrigatoriamente no formato `schema`."""
        body = {
            "model": LLM_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "resposta", "strict": True, "schema": schema},
            },
            # Raciocínio curto: os tokens de raciocínio contam no limite por minuto.
            "reasoning_effort": "low",
            "max_completion_tokens": 3000,
        }
        data = self._post("/chat/completions", tick, json=body)
        try:
            return json.loads(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise CloudError("O LLM do Groq devolveu uma resposta fora do formato.") from exc
