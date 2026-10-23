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
import queue
import threading
from contextlib import closing

import httpx
from jsonschema import validate, ValidationError

from .cloud import CloudError, Groq, Tick, api_key, WHISPER_MODEL as GROQ_WHISPER


def bounded_schema(schema, name=''):
    """Bound local grammar generation, including arrays of transcript IDs."""
    result = dict(schema)
    if result.get('type') == 'string':
        result['maxLength'] = 160 if name in ('rationale', 'feedback', 'context') else 80
    if result.get('type') == 'array':
        items = result['items']
        result['maxItems'] = min(12, len(items.get('enum', [])) or 6)
        if name == 'sentence_ids':
            result['maxItems'] = min(120, len(items.get('enum', [])) or 120)
        elif name == 'indexes':
            result['maxItems'] = min(60, len(items.get('enum', [])) or 60)
        result['items'] = bounded_schema(items)
    if 'properties' in result:
        result['properties'] = {k: bounded_schema(v, k) for k, v in result['properties'].items()}
    return result


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
        self.model = os.environ.get("CORTES_OLLAMA_MODEL", "").strip() or "qwen3:4b"
        # Contexto configurável; o uso de memória cresce junto com este limite.
        self.context = int(os.environ.get("CORTES_OLLAMA_CTX", "8192"))
        self.max_seconds = 240
        self.max_tokens = 1200
        self.cache_identity = f'ollama-bounded-v1|{self.model}|ctx={self.context}'
        self.http = http or httpx.Client(timeout=httpx.Timeout(None, connect=10))

    def _stream(self, body, tick):
        """Keep cancellation and a deadline active during CPU prompt evaluation."""
        messages = queue.Queue(maxsize=8)
        stopped = threading.Event()
        def send(item):
            while not stopped.is_set():
                try:
                    messages.put(item, timeout=.1)
                    return
                except queue.Full:
                    pass
        def read():
            try:
                with self.http.stream('POST', self.url + '/api/chat', json=body) as response:
                    if response.status_code == 404:
                        raise CloudError(f'O modelo {self.model} não está instalado. Rode: ollama pull {self.model}')
                    if response.status_code != 200:
                        response.read()
                        raise CloudError(f'O Ollama respondeu {response.status_code}: {response.text[:300]}')
                    for line in response.iter_lines():
                        if stopped.is_set():
                            break
                        if line:
                            send(('line', line))
                send(('end', None))
            except Exception as exc:
                send(('error', exc))
        started, last, completed = time.monotonic(), 0.0, False
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        try:
            while True:
                now = time.monotonic()
                if now - started > self.max_seconds:
                    raise CloudError('A IA local demorou demais nesta etapa. O progresso está salvo; tente retomar.')
                if now - last >= 1:
                    tick('Analisando a transcrição com a IA local')
                    last = now
                try:
                    kind, item = messages.get(timeout=.1)
                except queue.Empty:
                    continue
                if kind == 'error':
                    raise item
                if kind == 'end':
                    completed = True
                    return
                yield item
        finally:
            stopped.set()
            if not completed:
                self.http.close()
            thread.join(timeout=1)

    def chat_json(self, system: str, user: str, schema: dict, tick: Tick) -> dict:
        """Uma pergunta ao modelo local com resposta no formato `schema`.

        A resposta vem em streaming para que o progresso avance e o botão
        Cancelar funcione enquanto o modelo escreve.
        """
        schema = bounded_schema(schema)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": True,
            # O Qwen3 "pensa" antes de responder; aqui isso só custaria tempo.
            "think": False,
            "options": {"temperature": 0, "num_ctx": self.context, "num_predict": self.max_tokens},
        }
        content, last, completed = [], 0.0, False
        tick('Consultando a IA local')
        try:
            with closing(self._stream(body, tick)) as stream:
                for line in stream:
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise CloudError(f"O Ollama falhou: {chunk['error']}")
                    content.append(chunk.get("message", {}).get("content", ""))
                    if time.monotonic() - last > 1:
                        last = time.monotonic()
                        tick(f"IA local escrevendo ({len(''.join(content))} caracteres)")
                    if chunk.get("done"):
                        if chunk.get('done_reason') == 'length':
                            raise CloudError('A IA local atingiu o limite da resposta. O progresso está salvo; tente retomar.')
                        completed = True
                        # Consume the end marker so a successful shared client
                        # remains open for the next editorial stage.
                        continue
        except httpx.TransportError as exc:
            raise CloudError(
                "Não foi possível falar com o Ollama. Abra o aplicativo Ollama "
                f"(ou rode `ollama serve`) e tente de novo. Endereço: {self.url}"
            ) from exc
        if not completed:
            raise CloudError('A resposta da IA local foi interrompida. Retome o projeto para continuar.')
        try:
            answer = json.loads("".join(content))
            validate(answer, schema)
            return answer
        except (ValueError, ValidationError) as exc:
            raise CloudError("O modelo local devolveu uma resposta fora do formato.") from exc
