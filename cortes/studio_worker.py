import hashlib
import json
import os
import threading
import time
from dataclasses import asdict

from .cloud import Groq, WHISPER_MODEL
from .config import Cancelled
from .media import probe, detect_silences
from .segments import compute_keep, merge
from .transcribe import transcribe, Transcript, Sentence, Word
from .studio_media import prepare, render_edit
from .studio_stories import select_stories, complete_sentences, VERSION


def atomic_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temp, path)


class Worker:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.events = {}
        self.active = None
        self.thread = None

    def start(self):
        self.store.recover()
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def cancel(self, key):
        self.events.setdefault(key, threading.Event()).set()
        self.store.cancel_jobs(key)
        for clip in self.store.get(key)['clips']:
            if clip['original_status'] == 'queued':
                self.store.clip(key, clip['id'], original_status='cancelled')

    def notify(self, key, stage, progress):
        if self.stop.is_set() or self.events.setdefault(key, threading.Event()).is_set():
            raise Cancelled()
        self.store.update(key, stage=stage, progress=round(progress, 3))

    def loop(self):
        while not self.stop.is_set():
            with self.store.lock:
                job = self.store.claim()
                if job:
                    self.active = job[1]
            if not job:
                self.stop.wait(.3)
                continue
            job_id, key, kind, clip = job
            started = time.monotonic()
            try:
                self.notify(key, 'Iniciando', 0)
                if kind == 'process':
                    self.process(key)
                else:
                    self.export(key, clip)
                self.store.finish(job_id)
            except Cancelled:
                interrupted = self.stop.is_set()
                self.store.update(key, status='queued' if interrupted else 'cancelled', stage='Pausado. Você pode retomar.')
                if clip:
                    self.store.clip(key, clip, original_status='queued' if interrupted else 'cancelled')
                self.store.finish(job_id, 'queued' if interrupted else 'cancelled')
            except Exception as exc:
                import logging
                logging.exception('Project %s failed', key)
                message = str(exc)[-800:] or type(exc).__name__
                if clip:
                    self.store.clip(key, clip, original_status='error', original_error=message)
                else:
                    self.store.update(key, status='error', error=message, stage='Não foi possível concluir')
                self.store.finish(job_id, 'error')
            finally:
                data = self.store.get(key)
                timings = data.get('timings', {})
                timings[kind + (':' + clip if clip else '')] = round(time.monotonic() - started, 2)
                self.store.update(key, timings=timings)
                self.active = None

    def process(self, key):
        store, folder = self.store, self.store.directory(key)
        data = store.get(key)
        src = folder / ('source' + data['extension'])
        client = Groq()  # Fail clearly before expensive work if not configured.
        store.update(key, status='processing', error=None)
        metrics = data.get('timings', {})
        def stage(name, fn):
            start = time.monotonic()
            result = fn()
            metrics[name] = round(time.monotonic() - start, 2)
            store.update(key, timings=metrics)
            return result
        info = probe(src)
        proxy, audio = stage('proxy', lambda: prepare(src, folder, info, lambda f: self.notify(key, 'Preparando vídeo', f)))
        transcript_key = hashlib.sha256((data['source_hash'] + WHISPER_MODEL + '|pt|transcript-v1').encode()).hexdigest()[:20]
        transcript_path = folder / f'transcript-{transcript_key}.json'
        if transcript_path.exists():
            saved = json.loads(transcript_path.read_text(encoding='utf-8'))
            transcript = Transcript(saved['language'], [Sentence(s['start'], s['end'], s['text'], [Word(**w) for w in s['words']]) for s in saved['sentences']])
        else:
            transcript = stage('transcription', lambda: transcribe(audio, 'groq', 'small', 'pt', lambda f, label: self.notify(key, 'Transcrevendo · ' + label, f), client=client))
            atomic_json(transcript_path, asdict(transcript))
        transcript = complete_sentences(transcript)
        atomic_json(folder / f'editorial-transcript-{transcript_key}.json', asdict(transcript))
        edit_key = hashlib.sha256((transcript_key + client.model + VERSION + json.dumps(data['params'], sort_keys=True)).encode()).hexdigest()[:20]
        clip_path = folder / f'edits-{edit_key}.json'
        if clip_path.exists():
            clips = json.loads(clip_path.read_text(encoding='utf-8'))
        else:
            self.notify(key, 'Montando histórias', 0)
            silences = detect_silences(audio, -35, .8, info.duration)
            keep = compute_keep(silences, info.duration, .2, None, .8)
            # Quiet syllables are not necessarily silence. Protect every known
            # word, including a short breathing margin, before removing pauses.
            keep = merge(keep + [(max(0, a - .15), min(info.duration, b + .15))
                                 for a, b in transcript.speech_intervals()])
            clips = stage('stories', lambda: select_stories(transcript, keep, data['params'], client, folder,
                                                           lambda f, msg: self.notify(key, 'Montando histórias · ' + msg, f)))
            atomic_json(clip_path, clips)
        # Merge persisted render statuses rather than overwriting finished exports.
        old = {c['id']: c for c in store.get(key)['clips']}
        clips = [{**c, **{k: v for k, v in old.get(c['id'], {}).items()
                         if k.startswith('preview_') or k.startswith('original_')}} for c in clips]
        store.update(key, clips=clips)
        for i, clip in enumerate(clips):
            dest = folder / f"{clip['id']}.preview.mp4"
            if not dest.exists():
                store.clip(key, clip['id'], preview_status='rendering')
                stage('preview:' + clip['id'], lambda: render_edit(proxy, clip['parts'], dest, False,
                      lambda f: self.notify(key, f'Preparando prévias · {i + 1} de {len(clips)}', (i + f) / len(clips))))
            store.clip(key, clip['id'], preview_status='ready')
        store.update(key, status='ready', progress=1, stage='Seus cortes estão prontos',
                     notice=f'Encontramos {len(clips)} {"história completa" if len(clips) == 1 else "histórias completas"} entre os {data["params"]["count"]} cortes pedidos.' if len(clips) < data['params']['count'] else None,
                     disk_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()))

    def export(self, key, clip_id):
        data, folder = self.store.get(key), self.store.directory(key)
        clip = next(c for c in data['clips'] if c['id'] == clip_id)
        dest = folder / f'{clip_id}.original.mp4'
        if not dest.exists():
            self.store.clip(key, clip_id, original_status='rendering', original_progress=0, original_error=None)
            def progress(f):
                self.notify(key, 'Exportando qualidade original', f)
                self.store.clip(key, clip_id, original_progress=round(f, 3))
            render_edit(folder / ('source' + data['extension']), clip['parts'], dest, True, progress)
        self.store.clip(key, clip_id, original_status='ready', original_progress=1)
