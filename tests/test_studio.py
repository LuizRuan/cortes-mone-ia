import hashlib
import json
import shutil
import subprocess
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from cortes.config import Cancelled
from cortes.media import probe
from cortes.studio_api import create_app, CHUNK_BYTES, MAX_BYTES
from cortes.studio_media import prepare
from cortes.studio_stories import select_stories, validate_edit
from cortes.studio_store import Store
from cortes.studio_worker import Worker
from cortes.transcribe import Transcript, Sentence, Word


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path, run_worker=False)) as c:
        yield c


def upload(client, content, name='video.mp4'):
    p = client.post('/api/projects', json={'name': name, 'size': len(content), 'fingerprint': hashlib.sha256(content).hexdigest()}).json()
    response = client.put(f'/api/projects/{p["id"]}/upload?offset=0', content=content,
                          headers={'x-chunk-sha256': hashlib.sha256(content).hexdigest()})
    assert response.status_code == 200, response.text
    return p['id']


def test_resumable_upload_and_integrity(client):
    content = b'video' * 100
    p = client.post('/api/projects', json={'name': 'video.mp4', 'size': len(content), 'fingerprint': 'a' * 64}).json()
    key = p['id']
    for offset, part in [(0, content[:200]), (200, content[200:])]:
        response = client.put(f'/api/projects/{key}/upload?offset={offset}', content=part, headers={'x-chunk-sha256': hashlib.sha256(part).hexdigest()})
        assert response.status_code == 200
        assert response.json()['offset'] == offset + len(part)
    assert client.app.state.store.directory(key).joinpath('upload.partial').read_bytes() == content
    assert client.put(f'/api/projects/{key}/upload?offset=0', content=b'x').status_code == 409
    assert client.post(f'/api/projects/{key}/complete').status_code == 400  # not actual video


def test_corrupt_chunk_does_not_advance(client):
    p = client.post('/api/projects', json={'name':'a.mp4','size':10,'fingerprint':'b'*64}).json()
    key = p['id']
    assert client.put(f'/api/projects/{key}/upload?offset=0', content=b'123').status_code == 400
    assert client.get('/api/projects/'+key).json()['offset'] == 0
    assert not (client.app.state.store.directory(key) / 'chunk.tmp').exists()


def test_size_boundary_and_disk_space(client, monkeypatch):
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: Mock(free=MAX_BYTES * 3))
    data = {'name':'big.mp4','size':MAX_BYTES,'fingerprint':'f'*64}
    assert client.post('/api/projects', json=data).status_code == 200
    assert client.post('/api/projects', json={**data,'size':MAX_BYTES+1}).status_code == 422
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: Mock(free=0))
    assert client.post('/api/projects', json=data).status_code == 507


def test_queue_recovery_dedup_and_scoped_cancel(tmp_path):
    store = Store(tmp_path)
    a, b = [store.create('video.mp4',10,'f'*64)['id'] for _ in range(2)]
    store.enqueue(a,'process'); store.enqueue(a,'process'); store.enqueue(b,'process')
    first = store.claim()
    assert first[1] == a
    store.recover()
    assert store.claim()[0] == first[0]
    store.finish(first[0])
    assert store.claim()[1] == b
    worker = Worker(store)
    worker.cancel(a)
    with pytest.raises(Cancelled): worker.notify(a,'test',0)
    worker.notify(b,'test',.5)


def transcript():
    texts = ['Eu perdia horas tentando organizar meu trabalho.', 'O problema era começar tudo ao mesmo tempo.',
             'Passei a escolher uma única prioridade por dia.', 'Mas isso só funcionou depois que limitei as reuniões.',
             'Hoje termino o que começo sem trabalhar até tarde.', 'A lição é reduzir a lista, não aumentar as horas.']
    return Transcript('pt', [Sentence(i*3+.5,i*3+3,text,[Word(i*3+.5,i*3+3,text)]) for i,text in enumerate(texts)])


class Editor:
    model = 'fixture-editor'
    def __init__(self, approved=True):
        self.approved, self.calls = approved, []
    def chat_json(self, system, user, schema, tick):
        request = json.loads(user); stage=request['stage']; self.calls.append(stage)
        if stage == 'compreensão': return {'ideas':[{'topic':'Foco','context':'Uma ressalva sobre reuniões é essencial.','start':0,'end':5}]}
        if stage == 'busca editorial': return {'candidates':[{'topic':'Foco','ranges':[{'start':0,'end':5}]}]}
        if stage == 'seleção global': return {'indexes':[0]}
        if stage == 'revisão': return dict(approved=self.approved, fidelity=5,coherence=5,completeness=5 if self.approved else 1,interest=4,feedback='Completo' if self.approved else 'Falta conclusão')
        return dict(title='Uma prioridade muda seu dia',rationale='Problema, mudança e resultado com a ressalva preservada.',
                    opening='O problema',development='A mudança e sua condição',ending='A lição',sentence_ids=list(range(6)))


def test_editor_preserves_story_and_caches(tmp_path):
    client=Editor()
    args=(transcript(),[(0,20)],{'count':5,'min_seconds':10,'max_seconds':20},client,tmp_path,lambda *a:None)
    clips=select_stories(*args)
    assert len(clips)==1
    assert 3 in clips[0]['sentence_ids']  # crucial qualification
    calls=len(client.calls)
    assert select_stories(*args)==clips
    assert len(client.calls)==calls
    rejected=Editor(False)
    other=tmp_path/'rejected';other.mkdir()
    assert select_stories(*args[:3],rejected,other,lambda *a:None)==[]
    assert rejected.calls.count('correção única')==1


@pytest.mark.parametrize('ids', [[2,1],[0,0],[-1],[900]])
def test_invalid_edits_rejected_without_trimming(ids):
    edit={'sentence_ids':ids,'title':'A','opening':'A','development':'B','ending':'C'}
    with pytest.raises(ValueError):validate_edit(edit,transcript().sentences,[(0,20)],5,20)


def test_distant_context_preserves_chronology_without_filling_gaps():
    sentences = transcript().sentences
    sentences[3] = Sentence(100, 103, sentences[3].text)
    sentences[4] = Sentence(200, 203, sentences[4].text)
    sentences[5] = Sentence(203, 206, sentences[5].text)
    edit = dict(sentence_ids=[0,1,2,3,4,5], title='Foco', opening='Problema', development='Solução e ressalva', ending='Lição')
    parts = validate_edit(edit, sentences, [(0,207)], 10, 30)
    assert len(parts) == 5
    assert parts[-1][1] >= 206
    assert all(a < b for a,b in parts)
    assert not any(a <= 150 <= b for a,b in parts)
    with pytest.raises(ValueError):
        validate_edit(edit, sentences, [(0,207)], 5, 10)  # never trim the ending


def test_diversity_keeps_best_reviewed_duplicate(tmp_path):
    editor = Editor()
    original = editor.chat_json
    def call(system, user, schema, tick):
        payload = json.loads(user)
        stage = payload['stage']
        if stage == 'busca editorial':
            return {'candidates':[dict(topic=t, ranges=[dict(start=0,end=5)]) for t in ['Primeira', 'Melhor']]}
        if stage == 'seleção global':
            return {'indexes':[0,1]}
        result = original(system, user, schema, tick)
        if stage == 'montagem':
            result['title'] = payload['topic']
        if stage == 'revisão':
            result['interest'] = 5 if payload['edit']['title'] == 'Melhor' else 4
        return result
    editor.chat_json = call
    clips = select_stories(transcript(), [(0,20)], dict(count=5,min_seconds=10,max_seconds=20), editor,tmp_path,lambda *a:None)
    assert len(clips) == 1
    assert clips[0]['title'] == 'Melhor'


@pytest.fixture
def video(tmp_path):
    if not shutil.which('ffmpeg'):pytest.skip('ffmpeg required')
    path=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','testsrc2=s=640x360:r=30:d=20',
                    '-f','lavfi','-i','sine=frequency=440:duration=20','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(path)],check=True)
    return path


def test_full_pipeline_preview_original_range_and_reuse(client, video, monkeypatch):
    import cortes.studio_worker as module
    monkeypatch.setattr(module,'editor',Editor)
    transcriber=Mock(return_value=transcript())
    monkeypatch.setattr(module,'transcribe',transcriber)
    monkeypatch.setenv('GROQ_API_KEY','fixture-key')
    key=upload(client,video.read_bytes())
    assert client.post(f'/api/projects/{key}/complete').status_code==200
    params={'count':5,'min_seconds':10,'max_seconds':20}
    assert client.post(f'/api/projects/{key}/start',json=params).status_code==200
    store=client.app.state.store;worker=Worker(store)
    job=store.claim();worker.process(key);store.finish(job[0])
    data=store.get(key);assert data['status']=='ready'
    clip=data['clips'][0];folder=store.directory(key)
    assert clip['preview_status']=='ready'
    assert max(probe(folder/'proxy.mp4').width,probe(folder/'proxy.mp4').height)<=480
    assert probe(folder/'proxy.mp4').fps<=15
    assert not (folder/f'{clip["id"]}.original.mp4').exists()
    url=f'/api/projects/{key}/clips/{clip["id"]}'
    assert client.get(url+'/preview',headers={'Range':'bytes=0-9'}).status_code==206
    assert client.post(url+'/export').status_code==200
    assert client.post(url+'/export').status_code==200
    queued=store.claim();assert queued[2]=='export'
    assert store.claim() is None
    worker.export(key,clip['id']);store.finish(queued[0])
    original=folder/f'{clip["id"]}.original.mp4'
    assert probe(original).width==640
    preview=folder/f'{clip["id"]}.preview.mp4'
    assert abs(probe(original).duration-probe(preview).duration)<.15
    oldtime=original.stat().st_mtime_ns
    worker.export(key,clip['id'])
    assert original.stat().st_mtime_ns==oldtime
    transcriber.assert_called_once()
    assert client.get(url+'/original?download=true').headers['content-disposition'].startswith('attachment')
    assert client.delete(f'/api/projects/{key}').status_code==200
    assert not folder.exists()


def test_delayed_audio_proxy_alignment(video,tmp_path):
    delayed=tmp_path/'delayed.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(video),'-itsoffset','1','-i',str(video),
                    '-map','0:v','-map','1:a','-c','copy',str(delayed)],check=True)
    folder=tmp_path/'proxy';folder.mkdir()
    proxy,audio=prepare(delayed,folder,probe(delayed),lambda f:None)
    from cortes.transcribe import read_wav
    import numpy as np
    assert np.abs(read_wav(audio,0,.7)).max()<.001
    assert np.abs(read_wav(audio,1.2,1.5)).max()>.01
    assert abs(probe(proxy).duration-probe(delayed).duration)<.15
    from cortes.studio_media import render_edit
    from cortes.media import extract_audio
    for original,source in [(True,delayed),(False,proxy)]:
        out=folder/f'cut-{original}.mp4'
        render_edit(source,[(0,2)],out,original,lambda f:None)
        wav=folder/f'cut-{original}.wav'
        extract_audio(out,wav)
        assert np.abs(read_wav(wav,0,.7)).max()<.001
        assert np.abs(read_wav(wav,1.2,1.5)).max()>.01


@pytest.mark.parametrize('variant',['rotation','vfr'])
def test_rotation_and_variable_fps(video,tmp_path,variant):
    changed=tmp_path/f'{variant}.mp4'
    if variant=='rotation':
        flags=['-c','copy','-metadata:s:v:0','rotate=90']
    else:
        flags=['-vf',"select='if(lt(t,10),not(mod(n,2)),1)'",'-fps_mode','vfr','-c:v','libx264','-preset','ultrafast','-c:a','copy']
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(video),*flags,str(changed)],check=True)
    folder=tmp_path/'variant';folder.mkdir()
    info=probe(changed)
    proxy,_=prepare(changed,folder,info,lambda f:None)
    assert abs(probe(proxy).duration-info.duration)<.15
    assert probe(proxy).width/probe(proxy).height==pytest.approx(info.width/info.height,abs=.01)
    from cortes.studio_media import render_edit
    out=folder/'original.mp4'
    render_edit(changed,[(1,3),(12,14)],out,True,lambda f:None)
    assert (probe(out).width,probe(out).height)==(info.width,info.height)


def test_groq_failure_is_not_replaced_with_heuristic(tmp_path):
    broken=Editor()
    broken.chat_json=Mock(side_effect=RuntimeError('Groq unavailable'))
    with pytest.raises(RuntimeError,match='Groq unavailable'):
        select_stories(transcript(),[(0,20)],dict(count=5,min_seconds=10,max_seconds=20),broken,tmp_path,lambda *a:None)


def test_chunk_limit_and_disk_exhaustion(client, monkeypatch):
    p = client.post('/api/projects', json=dict(name='a.mp4', size=CHUNK_BYTES + 1, fingerprint='a'*64)).json()
    key = p['id']
    content = b'x' * (CHUNK_BYTES + 1)
    assert client.put(f'/api/projects/{key}/upload?offset=0', content=content).status_code == 413
    monkeypatch.setattr(shutil, 'disk_usage', lambda p: Mock(free=0))
    assert client.put(f'/api/projects/{key}/upload?offset=0', content=b'x').status_code == 507
    assert client.app.state.store.get(key)['offset'] == 0


def test_uncommitted_append_and_validation_recover(tmp_path):
    app = create_app(tmp_path, run_worker=False)
    with TestClient(app) as c:
        key = upload(c, b'123')
        app.state.store.update(key, size=6)
        (app.state.store.directory(key) / 'upload.partial').write_bytes(b'123uncommitted')
    with TestClient(create_app(tmp_path, run_worker=False)) as c:
        response = c.put(f'/api/projects/{key}/upload?offset=3', content=b'456', headers={'x-chunk-sha256':hashlib.sha256(b'456').hexdigest()})
        assert response.status_code == 200
        assert (app.state.store.directory(key) / 'upload.partial').read_bytes() == b'123456'
        app.state.store.update(key, status='validating')
        assert c.post(f'/api/projects/{key}/cancel').status_code == 409
        app.state.store.recover()
        assert app.state.store.get(key)['status'] == 'uploading'


def test_cancellation_restart_does_not_requeue_exports(tmp_path):
    store = Store(tmp_path)
    key = store.create('a.mp4', 10, 'a'*64)['id']
    store.update(key, status='cancelling', clips=[dict(id='clip', original_status='rendering')])
    store.enqueue(key, 'export', 'clip')
    store.claim()
    store.recover()
    assert store.claim() is None
    assert store.get(key)['clips'][0]['original_status'] == 'cancelled'


def test_video_without_audio_rejected(client, video, tmp_path):
    path = tmp_path / 'silent.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(video),'-an','-c:v','copy',str(path)],check=True)
    key = upload(client, path.read_bytes())
    response = client.post(f'/api/projects/{key}/complete')
    assert response.status_code == 400
    assert 'áudio' in response.json()['detail']


def test_hdr_conversion_is_sdr(video, tmp_path):
    from cortes.studio_media import render_edit
    hdr = tmp_path / 'hdr.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(video),'-t','2','-vf','format=yuv420p10le',
                    '-c:v','libx265','-x265-params','log-level=error:colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc','-color_primaries','bt2020',
                    '-color_trc','smpte2084','-colorspace','bt2020nc','-c:a','copy',str(hdr)],check=True, capture_output=True)
    folder = tmp_path / 'hdr-output'; folder.mkdir()
    proxy, _ = prepare(hdr, folder, probe(hdr), lambda f:None)
    final = folder / 'final.mp4'
    render_edit(hdr, [(0,1.5)], final, True, lambda f:None)
    for path in [proxy, final]:
        stream = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(path)]))['streams'][0]
        assert stream['color_transfer'] == 'bt709'
        assert stream['color_primaries'] == 'bt709'
        assert stream['pix_fmt'] == 'yuv420p'


def test_old_heuristic_would_fill_incomplete_story(tmp_path):
    from cortes.highlights import _pick_with_heuristic, kept_clock
    incomplete=Transcript('pt',transcript().sentences[:3])
    keep=[(0,10)]
    assert _pick_with_heuristic(incomplete.sentences,kept_clock(keep),5,10)
    # A strict editorial review rejects an unfinished idea rather than filling
    # the requested count. This tests policy, not a real model's judgement.
    editor=Editor(False)
    original_call=editor.chat_json
    def call(system,user,schema,tick):
        stage=json.loads(user)['stage']
        result=original_call(system,user,schema,tick)
        if stage=='compreensão':result['ideas'][0]['end']=2
        if stage=='busca editorial':result['candidates'][0]['ranges'][0]['end']=2
        if stage in ('montagem','correção única'):result['sentence_ids']=[0,1,2]
        return result
    editor.chat_json=call
    assert select_stories(incomplete,keep,dict(count=5,min_seconds=5,max_seconds=10),editor,tmp_path,lambda *a:None)==[]


def test_ai_provider_follows_env_and_key(monkeypatch):
    from cortes import local_ai
    monkeypatch.delenv('CORTES_IA', raising=False)
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    assert local_ai.provider() == 'local' and local_ai.missing_setup() is None
    assert local_ai.transcription() == ('local', 'small', 'local-small')
    monkeypatch.setenv('GROQ_API_KEY', 'fixture-key')
    assert local_ai.provider() == 'groq'
    monkeypatch.setenv('CORTES_IA', 'local')
    assert local_ai.provider() == 'local'
    monkeypatch.setenv('CORTES_IA', 'groq')
    monkeypatch.delenv('GROQ_API_KEY')
    assert 'GROQ_API_KEY' in local_ai.missing_setup()


def test_ollama_streams_structured_answer():
    import httpx
    from cortes.local_ai import Ollama
    sent = {}
    def handler(request):
        sent.update(json.loads(request.content))
        lines = [{'message': {'content': '{"indexes": '}}, {'message': {'content': '[2, 0]}'}, 'done': True}]
        return httpx.Response(200, content='\n'.join(json.dumps(x) for x in lines))
    ollama = Ollama(httpx.Client(transport=httpx.MockTransport(handler)))
    assert ollama.chat_json('sys', 'user', {'type': 'object'}, lambda msg: None) == {'indexes': [2, 0]}
    assert sent['format'] == {'type': 'object'} and sent['think'] is False
    assert sent['options']['temperature'] == 0


def test_ollama_missing_model_and_offline_have_clear_messages():
    import httpx
    from cortes.cloud import CloudError
    from cortes.local_ai import Ollama
    missing = Ollama(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404, json={'error': 'not found'}))))
    with pytest.raises(CloudError, match='ollama pull'):
        missing.chat_json('s', 'u', {}, lambda msg: None)
    def offline(request):
        raise httpx.ConnectError('refused')
    with pytest.raises(CloudError, match='Ollama'):
        Ollama(httpx.Client(transport=httpx.MockTransport(offline))).chat_json('s', 'u', {}, lambda msg: None)