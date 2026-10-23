"""Real local editorial benchmark; never calls paid providers.

Uses a saved transcript, so timings explicitly exclude ASR, upload and rendering.
--repeat exercises longer timelines with repeated content, not independent stories.
Run on Windows to include native Ollama RSS. Output stays outside Git by default.
"""
import argparse
import json
import sys
import threading
import time
import subprocess
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
from cortes.local_ai import Ollama
from cortes.studio_stories import select_stories
from cortes.transcribe import Transcript, Sentence, Word


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('transcript', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--baseline-commit', help='Compare an earlier tracked implementation, e.g. 1ebfcdf')
    args = parser.parse_args()
    selection = select_stories
    if args.baseline_commit:
        source = subprocess.run(['git','show',f'{args.baseline_commit}:cortes/studio_stories.py'],
                                check=True,capture_output=True,encoding='utf-8').stdout
        module = types.ModuleType('cortes._benchmark_baseline')
        module.__package__ = 'cortes'
        exec(compile(source,'<baseline studio_stories>','exec'),module.__dict__)
        selection = module.select_stories
    raw = json.loads(args.transcript.read_text(encoding='utf-8'))
    duration = max(s['end'] for s in raw['sentences'])
    sentences = []
    for repeat in range(args.repeat):
        offset = repeat * (duration + 1)
        for s in raw['sentences']:
            words = [Word(w['start']+offset,w['end']+offset,w['text']) for w in s.get('words',[])]
            sentences.append(Sentence(s['start']+offset,s['end']+offset,s['text'],words))
    client = Ollama()
    client.check_ready()
    args.output.mkdir(parents=True,exist_ok=True)
    warm = (args.output/'editorial').exists()
    peak = dict(backend=0,ollama_windows=0)
    stop = threading.Event()
    def sample():
        while not stop.is_set():
            peak['backend'] = max(peak['backend'],psutil.Process().memory_info().rss)
            total = 0
            for process in psutil.process_iter(['name','memory_info']):
                try:
                    if any(name in (process.info['name'] or '').lower() for name in ('ollama','llama-server')):
                        total += process.info['memory_info'].rss
                except psutil.Error:
                    pass
            peak['ollama_windows'] = max(peak['ollama_windows'],total)
            stop.wait(1)
    thread = threading.Thread(target=sample,daemon=True);thread.start()
    started = time.monotonic()
    last = 0
    def notify(fraction, message):
        nonlocal last
        now = time.monotonic()
        if now-last > 20:
            print(round(now-started),message,flush=True);last=now
    result = dict(kind='real Ollama; saved synthetic-speech transcript; editorial only',
                  model=client.model, repeat=args.repeat, input_seconds=duration*args.repeat,
                  cache_at_start=warm, client_protocol=client.cache_identity)
    result['baseline_commit'] = args.baseline_commit
    try:
        result['clips'] = selection(Transcript(raw['language'],sentences),[(0,sentences[-1].end+1)],
            dict(count=args.count,min_seconds=30,max_seconds=90),client,args.output,notify)
    except Exception as exc:
        result['error'] = str(exc)
        raise
    finally:
        stop.set();thread.join()
        result.update(seconds=round(time.monotonic()-started,2),peak_rss_bytes=peak,
                      disk_bytes=sum(p.stat().st_size for p in args.output.rglob('*') if p.is_file()))
        (args.output/'benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='clips'},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
