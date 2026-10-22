"""Modo local: faster-whisper transcreve e o Ollama monta as histórias.

Nada sai do computador e não há chave nem custo por uso. O preço é tempo:
sem placa de vídeo dedicada, tudo roda no processador.

CORTES_IA escolhe o motor: "local" ou "groq". Sem a variável, usa o Groq
quando existe GROQ_API_KEY e o modo local caso contrário.
"""
from __future__ import annotations

import json
import os
import time

import httpx

from .cloud import CloudError, Groq, Tick, api_key, WHISPER_MODEL as GROQ_WHISPER


def provider() -> str:
    choice = os.environ.get("CORTES_IA", "").strip().lower()
    if choice in ("local", "groq"):
        return choice
    return "groq" if api_key() else "local"


def whisper_model() -> str:
    return os.environ.get("CORTES_WHISPER_LOCAL", "small").strip() or "small"


def transcription() -> tuple[str, str, str]:
    """(motor, modelo do faster-whisper, nome que entra na chave do cache)."""
    if provider() == "local":
        return "local", whisper_model(), "local-" + whisper_model()
    return "groq", "small", GROQ_WHISPER


def editor():
    """Cliente que responde chat_json(system, user, schema, tick)."""
    return Ollama() if provider() == "local" else Groq()


def missing_setup() -> str | None:
    """Mensagem para o usuário quando o motor escolhido não pode ser usado."""
    if provider() == "groq":
        return None if api_key() else "Configure GROQ_API_KEY no arquivo .env e reinicie o aplicativo."
    return None


class Ollama:
    def __init__(self, http: httpx.Client | None = None):
        self.url = os.environ.get("CORTES_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
        self.model = os.environ.get("CORTES_OLLAMA_MODEL", "qwen3:1.7b")
        # Contexto de 8 mil tokens cobre uma janela de ~10 min de fala.
        self.context = int(os.environ.get("CORTES_OLLAMA_CTX", "8192"))
        # Sem limite de leitura: no processador uma resposta pode levar minutos.
        self.http = http or httpx.Client(timeout=httpx.Timeout(None, connect=10))

    def chat_json(self, system: str, user: str, schema: dict, tick: Tick) -> dict:
        """Uma pergunta ao modelo local com resposta no formato `schema`.

        A resposta vem em streaming para que o progresso avance e o botão
        Cancelar funcione enquanto o modelo escreve.
        """
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": True,
            # O Qwen3 "pensa" antes de responder; aqui isso só custaria tempo.
            "think": False,
            "options": {"temperature": 0, "num_ctx": self.context},
        }
        content, last = [], 0.0
        try:
            with self.http.stream("POST", self.url + "/api/chat", json=body) as response:
                if response.status_code == 404:
                    raise CloudError(f"O modelo {self.model} não está instalado. Rode: ollama pull {self.model}")
                if response.status_code != 200:
                    response.read()
                    raise CloudError(f"O Ollama respondeu {response.status_code}: {response.text[:300]}")
                for line in response.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise CloudError(f"O Ollama falhou: {chunk['error']}")
                    content.append(chunk.get("message", {}).get("content", ""))
                    if time.monotonic() - last > 1:
                        last = time.monotonic()
                        tick(f"IA local escrevendo ({len(''.join(content))} caracteres)")
                    if chunk.get("done"):
                        break
        except httpx.TransportError as exc:
            raise CloudError(
                "Não foi possível falar com o Ollama. Abra o aplicativo Ollama "
                f"(ou rode `ollama serve`) e tente de novo. Endereço: {self.url}"
            ) from exc
        try:
            return json.loads("".join(content))
        except ValueError as exc:
            raise CloudError("O modelo local devolveu uma resposta fora do formato.") from exc
