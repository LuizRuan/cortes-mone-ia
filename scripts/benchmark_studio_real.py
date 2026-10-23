"""Full real-local benchmark against a running Studio (port 7860).

Use --source for each 5/10/60 minute fixture. No API calls are mocked.
Repeat the same --output to resume its project; a new folder creates a cold project.
Run on Windows to sample native Ollama memory as well as backend-reported RSS.
"""
import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx
import psutil


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--label',required=True,help='Synthetic speech or real user video')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    client=httpx.Client(base_url='http://localhost:7860',timeout=120)
    health=client.get('/api/health');health.raise_for_status()
    assert health.json()['ai_provider']=='local','This benchmark requires local AI'
    state=args.output/'project.json'
    resumed=state.exists()
    if resumed:
        project=client.get('/api/projects/'+json.loads(state.read_text())['id']).json()
    else:
        digest=hashlib.sha256()
        with args.source.open('rb') as stream:
            while part:=stream.read(8*1024**2):digest.update(part)
        response=client.post('/api/projects',json=dict(name=args.source.name,size=args.source.stat().st_size,fingerprint=digest.hexdigest()))
        response.raise_for_status();project=response.json()
        state.write_text(json.dumps(project),encoding='utf-8')
    base='/api/projects/'+project['id']
    started=time.monotonic();peak=0;report={}
    try:
        if project['status']=='uploading':
            with args.source.open('rb') as stream:
                stream.seek(project['offset'])
                while part:=stream.read(8*1024**2):
                    response=client.put(base+f'/upload?offset={project["offset"]}',content=part,headers={'x-chunk-sha256':hashlib.sha256(part).hexdigest()})
                    response.raise_for_status();project=response.json()
            response=client.post(base+'/complete');response.raise_for_status();project=response.json()
        if project['status'] not in ('ready','processing','queued'):
            response=client.post(base+'/start',json=dict(count=5,min_seconds=30,max_seconds=90));response.raise_for_status()
        while True:
            response=client.get(base);response.raise_for_status();project=response.json()
            rss=0
            for process in psutil.process_iter(['name','memory_info']):
                try:
                    if any(n in (process.info['name'] or '').lower() for n in ('ollama','llama-server')):
                        rss+=process.info['memory_info'].rss
                except psutil.Error:pass
            peak=max(peak,rss)
            print(round(time.monotonic()-started),project['stage'],flush=True)
            if project['status']=='ready':break
            if project['status'] in ('error','cancelled'):raise RuntimeError(project.get('error') or project['status'])
            time.sleep(20)
        report['processing_seconds_including_upload'] = round(time.monotonic()-started,2)
        for clip in project['clips']:
            response=client.get(base+f'/clips/{clip["id"]}/preview',headers={'Range':'bytes=0-100'})
            assert response.status_code==206
        if project['clips']:
            clip=project['clips'][0];url=base+f'/clips/{clip["id"]}'
            response=client.post(url+'/export');response.raise_for_status()
            while True:
                response=client.get(base);response.raise_for_status();project=response.json()
                clip=next(c for c in project['clips'] if c['id']==clip['id'])
                if clip['original_status']=='ready':break
                if clip['original_status']=='error':raise RuntimeError(clip['original_error'])
                time.sleep(3)
            assert client.post(url+'/export').json()['original_status']=='ready'
            for quality in ('preview','original'):
                with client.stream('GET',url+'/'+quality+'?download=true') as response:
                    response.raise_for_status()
                    with (args.output/(quality+'.mp4')).open('wb') as stream:
                        for part in response.iter_bytes():stream.write(part)
    except Exception as exc:
        report['error']=str(exc)
        raise
    finally:
        try:
            response=client.get(base);response.raise_for_status();project=response.json()
        except httpx.HTTPError:
            pass
        report.update(label=args.label,resumed=resumed,elapsed_seconds=round(time.monotonic()-started,2),
                      peak_ollama_windows_rss_bytes=peak,project=project)
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
