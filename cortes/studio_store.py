"""Persistent project manifests and a single durable processing queue."""
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, project TEXT NOT NULL,
                    kind TEXT NOT NULL, clip TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'queued');
                CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(project,kind,clip)
                    WHERE state IN ('queued','running');
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'studio.sqlite', timeout=30)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    def create(self, name, size, fingerprint):
        key = uuid.uuid4().hex
        data = dict(id=key, name=name, size=size, fingerprint=fingerprint, offset=0,
                    status='uploading', stage='Envie seu vídeo', progress=0, clips=[],
                    created=time.time(), error=None, timings={}, revision=1)
        self.directory(key).mkdir()
        with self.connect() as db:
            db.execute('INSERT INTO projects VALUES (?,?)', (key, json.dumps(data)))
        return data

    def directory(self, key):
        if len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
            raise KeyError(key)
        return self.root / key

    def get(self, key):
        self.directory(key)
        with self.connect() as db:
            row = db.execute('SELECT data FROM projects WHERE id=?', (key,)).fetchone()
        if not row:
            raise KeyError(key)
        return json.loads(row[0])

    def update(self, key, **changes):
        with self.lock:
            data = self.get(key)
            data.update(changes)
            with self.connect() as db:
                db.execute('UPDATE projects SET data=? WHERE id=?', (json.dumps(data), key))
            return data

    def clip(self, key, clip_id, **changes):
        with self.lock:
            data = self.get(key)
            clip = next(c for c in data['clips'] if c['id'] == clip_id)
            clip.update(changes)
            self.update(key, clips=data['clips'])

    def enqueue(self, key, kind, clip=''):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO jobs(project,kind,clip) VALUES (?,?,?)', (key, kind, clip))

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id,project,kind,clip FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE jobs SET state='running' WHERE id=?", (row[0],))
            return row

    def finish(self, job, state='done'):
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=? WHERE id=?', (state, job))

    def recover(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='queued' WHERE state='running'")
            rows = db.execute('SELECT id,data FROM projects').fetchall()
            for key, raw in rows:
                data = json.loads(raw)
                if data['status'] == 'validating':
                    data['status'] = 'uploading'
                    db.execute('UPDATE projects SET data=? WHERE id=?', (json.dumps(data), key))
                if data['status'] in ('queued', 'processing'):
                    db.execute("INSERT OR IGNORE INTO jobs(project,kind) VALUES (?, 'process')", (key,))
                if data['status'] == 'cancelling':
                    data['status'] = 'cancelled'
                    for clip in data['clips']:
                        if clip['original_status'] in ('queued', 'rendering'):
                            clip['original_status'] = 'cancelled'
                    db.execute("UPDATE jobs SET state='cancelled' WHERE project=? AND state='queued'", (key,))
                    db.execute('UPDATE projects SET data=? WHERE id=?', (json.dumps(data), key))
                else:
                    for clip in data['clips']:
                        if clip['original_status'] in ('queued', 'rendering'):
                            db.execute("INSERT OR IGNORE INTO jobs(project,kind,clip) VALUES (?,'export',?)", (key,clip['id']))

    def cancel_jobs(self, key):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='cancelled' WHERE project=? AND state='queued'", (key,))

    def delete(self, key):
        with self.connect() as db:
            db.execute('DELETE FROM jobs WHERE project=?', (key,))
            db.execute('DELETE FROM projects WHERE id=?', (key,))
