import asyncio
import hashlib
import os
import shutil
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .local_ai import missing_setup, provider
from .config import ALLOWED_EXTENSIONS
from .media import probe
from .studio_store import Store
from .studio_worker import Worker

MAX_BYTES = 20_000_000_000
CHUNK_BYTES = 8 * 1024 * 1024


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    size: int = Field(gt=0, le=MAX_BYTES)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class Parameters(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    min_seconds: int = Field(default=30, ge=5, le=180)
    max_seconds: int = Field(default=90, ge=10, le=180)

    @model_validator(mode='after')
    def duration(self):
        if self.min_seconds > self.max_seconds:
            raise ValueError('A duração mínima não pode superar a máxima.')
        return self


def create_app(root=None, run_worker=True, static_dir=None):
    store = Store(root or os.environ.get('CORTES_STUDIO_DIR', 'studio_data'))
    worker = Worker(store)
    upload_locks = {}
    uploading = set()

    @asynccontextmanager
    async def lifespan(app):
        if run_worker:
            worker.start()
        yield
        worker.stop.set()
        if worker.thread:
            await asyncio.to_thread(worker.thread.join, 10)

    app = FastAPI(title='Cortes Studio', lifespan=lifespan)
    app.state.store, app.state.worker = store, worker

    def project(key):
        try:
            return store.get(key)
        except KeyError:
            raise HTTPException(404, 'Projeto não encontrado.')

    def clip_for(key, clip_id):
        data = project(key)
        clip = next((c for c in data['clips'] if c['id'] == clip_id), None)
        if not clip:
            raise HTTPException(404, 'Corte não encontrado.')
        return data, clip

    @app.get('/api/health')
    def health():
        return {'ok': True, 'ai_configured': not missing_setup(), 'ai_provider': provider(), 'max_bytes': MAX_BYTES, 'chunk_bytes': CHUNK_BYTES}

    @app.post('/api/projects')
    def new_upload(body: Upload):
        extension = Path(body.name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, 'Selecione um vídeo MP4, MOV, MKV, AVI, WebM ou M4V.')
        if shutil.disk_usage(store.root).free < body.size + 512 * 1024**2:
            raise HTTPException(507, 'Não há espaço suficiente no servidor para este vídeo.')
        data = store.create(Path(body.name.replace('\\', '/')).name, body.size, body.fingerprint)
        return store.update(data['id'], extension=extension)

    @app.get('/api/projects/{key}')
    def get_project(key: str):
        data = project(key)
        if data['status'] == 'processing' and data.get('attempt_started'):
            data['elapsed_seconds'] = round(time.time() - data['attempt_started'], 1)
        data['previews_ready'] = sum(c['preview_status']=='ready' for c in data['clips'])
        return data

    @app.put('/api/projects/{key}/upload')
    async def upload_chunk(key: str, offset: int, request: Request):
        lock = upload_locks.setdefault(key, asyncio.Lock())
        async with lock:
            with store.lock:
                data = project(key)
                if data['status'] != 'uploading':
                    raise HTTPException(409, 'Este upload já foi concluído.')
                if offset != data['offset']:
                    raise HTTPException(409, 'Posição de upload divergente; consulte o projeto e retome.')
                folder = store.directory(key)
                temp, partial = folder / 'chunk.tmp', folder / 'upload.partial'
                uploading.add(key)
            try:
                digest, length = hashlib.sha256(), 0
                with temp.open('wb') as f:
                    async for chunk in request.stream():
                        length += len(chunk)
                        if length > CHUNK_BYTES or offset + length > data['size']:
                            raise HTTPException(413, 'Bloco maior que o permitido.')
                        if shutil.disk_usage(folder).free < len(chunk) + 64 * 1024**2:
                            raise HTTPException(507, 'O disco do servidor ficou sem espaço.')
                        f.write(chunk)
                        digest.update(chunk)
                    f.flush()
                    os.fsync(f.fileno())
                if not length or digest.hexdigest() != request.headers.get('x-chunk-sha256'):
                    raise HTTPException(400, 'Bloco corrompido; envie novamente.')
                with partial.open('r+b' if partial.exists() else 'wb') as dest, temp.open('rb') as source:
                    dest.truncate(offset)  # Recover an append interrupted before SQLite commit.
                    dest.seek(offset)
                    shutil.copyfileobj(source, dest, 1024 * 1024)
                    dest.flush()
                    os.fsync(dest.fileno())
                return store.update(key, offset=offset + length)
            except OSError as exc:
                raise HTTPException(507, 'Não foi possível gravar o upload. Verifique o espaço em disco.') from exc
            finally:
                uploading.discard(key)
                temp.unlink(missing_ok=True)

    @app.post('/api/projects/{key}/complete')
    def complete(key: str):
        with store.lock:
            data = project(key)
            if data['status'] != 'uploading':
                return data
            if key in uploading or data['offset'] != data['size']:
                raise HTTPException(409, 'Aguarde o envio do arquivo inteiro.')
            folder = store.directory(key)
            src = folder / ('source' + data['extension'])
            partial = folder / 'upload.partial'
            if not partial.exists() and src.exists():
                partial = src  # Recover rename completed before manifest commit.
            if not partial.exists() or partial.stat().st_size != data['size']:
                raise HTTPException(400, 'Arquivo incompleto.')
            store.update(key, status='validating', stage='Conferindo seu vídeo')
        try:
            info = probe(partial)
            if not info.has_audio:
                raise ValueError('O vídeo não tem áudio para transcrever.')
            digest = hashlib.sha256()
            with partial.open('rb') as f:
                while chunk := f.read(1024 * 1024):
                    digest.update(chunk)
            os.replace(partial, src)
            return store.update(key, status='uploaded', source_hash=digest.hexdigest(), duration=info.duration,
                                width=info.width, height=info.height, stage='Vídeo recebido')
        except Exception as exc:
            store.update(key, status='uploading', error=str(exc))
            raise HTTPException(400, str(exc)) from exc

    @app.post('/api/projects/{key}/start')
    def start(key: str, params: Parameters):
        with store.lock:
            data = project(key)
            if missing_setup():
                raise HTTPException(400, missing_setup())
            if data['status'] in ('uploading', 'validating'):
                raise HTTPException(409, 'Conclua o upload primeiro.')
            if worker.active == key or data['status'] in ('processing', 'queued'):
                return data
            if 'params' in data and data['params'] != params.model_dump():
                raise HTTPException(409, 'Para mudar as opções, crie um novo projeto. A retomada preserva os cortes.')
            if data['status'] == 'ready':
                return data
            worker.events.setdefault(key, threading.Event()).clear()
            data = store.update(key, status='queued', params=params.model_dump(), error=None, stage='Na fila')
            store.enqueue(key, 'process')
            return data

    @app.post('/api/projects/{key}/cancel')
    def cancel(key: str):
        with store.lock:
            data = project(key)
            if data['status'] in ('uploading', 'validating'):
                raise HTTPException(409, 'Aguarde a conferência ou pause o envio no navegador.')
            worker.cancel(key)
            return store.update(key, status='cancelling' if worker.active == key else 'cancelled', stage='Pausando')

    @app.post('/api/projects/{key}/clips/{clip_id}/export')
    def export_clip(key: str, clip_id: str):
        with store.lock:
            data, clip = clip_for(key, clip_id)
            if clip['preview_status'] != 'ready':
                raise HTTPException(409, 'Aguarde a prévia deste corte.')
            if clip['original_status'] in ('ready', 'queued', 'rendering'):
                return clip
            if data['status'] in ('cancelling', 'cancelled'):
                raise HTTPException(409, 'Retome o projeto antes de exportar.')
            store.clip(key, clip_id, original_status='queued', original_error=None)
            store.enqueue(key, 'export', clip_id)
            return clip_for(key, clip_id)[1]

    @app.get('/api/projects/{key}/clips/{clip_id}/{quality}')
    def download(key: str, clip_id: str, quality: str, download: bool = False):
        data, clip = clip_for(key, clip_id)
        if quality not in ('preview', 'original') or clip.get(quality + '_status') != 'ready':
            raise HTTPException(404, 'Arquivo ainda não está disponível.')
        path = store.directory(key) / f'{clip_id}.{quality}.mp4'
        if not path.exists():
            raise HTTPException(404, 'Arquivo não encontrado.')
        return FileResponse(path, media_type='video/mp4', filename=f'corte-{clip_id}-{quality}.mp4' if download else None)

    @app.delete('/api/projects/{key}')
    def delete(key: str):
        with store.lock:
            project(key)
            if worker.active == key or key in uploading or project(key)['status'] == 'validating':
                raise HTTPException(409, 'Pause o processamento ou envio antes de excluir.')
            store.cancel_jobs(key)
            folder = store.directory(key)
            shutil.rmtree(folder)
            store.delete(key)
            return {'deleted': True}

    dist = Path(static_dir or Path(__file__).resolve().parents[1] / 'frontend' / 'dist')
    if dist.exists():
        app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
    return app
