"""Repeatable local media benchmark. AI is explicitly simulated, never billed."""
import json
import runpy
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
from cortes.studio_store import Store
from cortes.studio_worker import Worker
from cortes.media import probe


def main():
    fixture = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tests/test_studio.py'))
    root = Path('.cache/benchmark-studio')
    store = Store(root)
    data = store.create('teste-sintetico.mp4', 1, 'f' * 64)
    key, folder = data['id'], store.directory(data['id'])
    source = folder / 'source.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=s=640x360:r=30:d=20',
                    '-f','lavfi','-i','sine=frequency=440:duration=20','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(source)], check=True)
    import hashlib
    store.update(key, extension='.mp4', source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
                 params=dict(count=5,min_seconds=10,max_seconds=20))
    stop = threading.Event()
    samples = []
    process = psutil.Process()
    def sample():
        while not stop.is_set():
            memory = 0
            for p in [process, *process.children(recursive=True)]:
                try: memory += p.memory_info().rss
                except psutil.Error: pass
            samples.append(memory)
            stop.wait(.05)
    thread = threading.Thread(target=sample, daemon=True);thread.start()
    worker = Worker(store)
    started = time.monotonic()
    with patch('cortes.studio_worker.Groq', fixture['Editor']), patch('cortes.studio_worker.transcribe', return_value=fixture['transcript']()):
        worker.process(key)
        preview_seconds = time.monotonic() - started
        clip = store.get(key)['clips'][0]
        export_start = time.monotonic()
        worker.export(key, clip['id'])
        export_seconds = time.monotonic() - export_start
        reuse_start = time.monotonic()
        worker.export(key, clip['id'])
        reuse_seconds = time.monotonic() - reuse_start
    stop.set();thread.join()
    report = dict(fixture='20 seconds, 640x360, 30fps; synthetic tone/video; simulated transcript and editorial AI',
                  source_bytes=source.stat().st_size, proxy_bytes=(folder/'proxy.mp4').stat().st_size,
                  preview_seconds=round(preview_seconds,3),original_export_seconds=round(export_seconds,3),
                  reuse_seconds=round(reuse_seconds,3),peak_rss_parent_and_children_mb=round(max(samples)/1024**2,1),
                  disk_bytes=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file()),
                  stage_seconds=store.get(key)['timings'],preview_resolution=[probe(folder/'proxy.mp4').width,probe(folder/'proxy.mp4').height],
                  original_resolution=[probe(folder/f'{clip["id"]}.original.mp4').width,probe(folder/f'{clip["id"]}.original.mp4').height])
    target = Path('docs/studio-benchmark.json');target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':main()
