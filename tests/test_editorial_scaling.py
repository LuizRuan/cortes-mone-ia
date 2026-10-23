import json
import hashlib
from unittest.mock import Mock

import httpx
import pytest

from cortes.cloud import CloudError
from cortes.config import Cancelled
from cortes.local_ai import Ollama
from cortes.studio_stories import select_stories
from cortes.transcribe import Transcript, Sentence


class ScalingEditor:
    model = 'simulated-scaling'
    context = 8192
    max_tokens = 1200

    def __init__(self, reject=False):
        self.calls = []
        self.reject = reject

    def chat_json(self, system, user, schema, tick):
        p = json.loads(user)
        self.calls.append(p)
        stage = p['stage']
        if stage == 'descoberta':
            lines = p['transcript']
            return dict(candidates=[dict(topic=str(lines[0]['id']),context='Context',
                start=lines[0]['id'],end=lines[min(2,len(lines)-1)]['id'],complete=True,conclusion='Outcome')])
        if stage in ('triagem','contexto distante'):
            return dict(decisions=[dict(id=i,action='advance',reason='Complete',score=5,related=[]) for i in p['targets']])
        if stage == 'revisão':
            return dict(approved=not self.reject,fidelity=5,coherence=5,completeness=1 if self.reject else 5,interest=4,feedback='Review',single_topic=True,complete_ending=not self.reject,preserves_meaning=True)
        core=int(p['topic'])
        return dict(title=p['topic'],rationale='Reason',opening='Problem',development='Change',ending='Outcome',sentence_ids=[core,core+1,core+2])


def run(tmp_path, client, seconds=3600, **kwargs):
    sentences = [Sentence(i,i+10,hashlib.sha256(str(i).encode()).hexdigest()+'.') for i in range(0,seconds,10)]
    return select_stories(Transcript('pt',sentences),[(0,seconds+1)],
        dict(count=2,min_seconds=20,max_seconds=90),client,tmp_path,lambda *a:None,**kwargs)


@pytest.mark.parametrize('seconds',[300,600,3600])
def test_full_coverage_before_review_and_stable_publication(tmp_path, seconds):
    client = ScalingEditor()
    publications=[]
    clips = run(tmp_path,client,seconds,publish=lambda c:publications.append(c['id']))
    report=json.loads((tmp_path/'editorial-progress.json').read_text())
    assert report['covered_ids']==list(range(seconds//10))
    assert report['complete']
    assert publications==[c['id'] for c in clips]
    assert len(clips)==2
    stages=[c['stage'] for c in client.calls]
    assert max(i for i,s in enumerate(stages) if s=='descoberta') < stages.index('montagem')


def test_review_budget_and_rejection_reasons(tmp_path):
    client=ScalingEditor(reject=True)
    assert run(tmp_path,client)==[]
    report=json.loads((tmp_path/'editorial-progress.json').read_text())
    assert report['reviewed']==6  # 3 * requested count
    assert sum(p['stage']=='correção única' for p in client.calls)==6
    assert len([d for d in report['decisions'] if d['outcome']=='rejected'])==6


def test_resume_preserves_published_candidate_and_reuses_ai(tmp_path):
    client=ScalingEditor()
    published=[]
    def interrupt(clip):
        published.append(clip['id'])
        raise Cancelled()
    with pytest.raises(Cancelled):run(tmp_path,client,publish=interrupt)
    calls=len(client.calls)
    clips=run(tmp_path,client)
    assert clips[0]['id']==published[0]
    assert len(client.calls)>calls  # only remaining candidates need work
    calls=len(client.calls)
    assert run(tmp_path,client)==clips
    assert len(client.calls)==calls


def test_missing_decision_is_not_cached(tmp_path):
    client=ScalingEditor()
    original=client.chat_json
    client.chat_json=lambda s,u,sc,t: {'decisions':[]} if json.loads(u)['stage']=='triagem' else original(s,u,sc,t)
    with pytest.raises(ValueError,match='todos'):run(tmp_path,client,300)
    assert all('decisions' not in json.loads(p.read_text()) for p in (tmp_path/'editorial').glob('*.json'))


def test_context_budget_splits_without_losing_sentences(tmp_path):
    client=ScalingEditor();client.context=4000
    # No candidate assembly needed; the test exercises discovery budgeting.
    original=client.chat_json
    client.chat_json=lambda s,u,sc,t: {'candidates':[]} if json.loads(u)['stage']=='descoberta' else original(s,u,sc,t)
    run(tmp_path,client,600)
    report=json.loads((tmp_path/'editorial-progress.json').read_text())
    assert len(report['covered_ids'])==60


def test_ollama_preflight_checks_server_and_installed_model():
    for response,match in [(httpx.Response(503),'indisponível'),(httpx.Response(200,json={'models':[]}),'ollama pull')]:
        client=Ollama(httpx.Client(transport=httpx.MockTransport(lambda r:response)))
        with pytest.raises(CloudError,match=match):client.check_ready()
    client=Ollama(httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'models':[{'name':'qwen3:4b'}]}))))
    client.check_ready()


def test_remote_context_retrieves_original_speech_in_order(tmp_path):
    client=ScalingEditor()
    original=client.chat_json
    requests=[]
    def chat(system,user,schema,tick):
        payload=json.loads(user);requests.append(payload)
        if payload['stage'] in ('triagem','contexto distante'):
            related=[payload['summaries'][-1]['id']] if payload['stage']=='contexto distante' else []
            return dict(decisions=[dict(id=i,action='context' if i==0 else 'advance',reason='Needs conclusion',
                                       score=5,related=related if i==0 else []) for i in payload['targets']])
        return original(system,user,schema,tick)
    client.chat_json=chat
    run(tmp_path,client)
    assert any(r['stage']=='contexto distante' for r in requests)
    source=next(r['transcript'] for r in requests if r['stage']=='montagem')
    ids=[s['id'] for s in source]
    assert ids==sorted(set(ids))
    assert ids[-1]-ids[0]>50


def test_oversized_single_sentence_errors_instead_of_truncating(tmp_path):
    client=ScalingEditor();client.context=3000
    with pytest.raises(ValueError,match='frase excede'):
        select_stories(Transcript('pt',[Sentence(0,60,'Long text '*5000)]),[(0,60)],
            dict(count=1,min_seconds=30,max_seconds=90),client,tmp_path,lambda *a:None)
    assert client.calls==[]


def test_review_flags_override_high_scores_and_approval(tmp_path):
    client=ScalingEditor()
    original=client.chat_json
    def chat(system,user,schema,tick):
        result=original(system,user,schema,tick)
        if json.loads(user)['stage']=='revisão':
            result['single_topic']=False
        return result
    client.chat_json=chat
    assert run(tmp_path,client,300)==[]


def test_impossible_duration_skips_generation_without_truncating_or_filling(tmp_path):
    client=ScalingEditor()
    source=Transcript('pt',[Sentence(i*3,i*3+2,'A complete thought.') for i in range(3)])
    clips=select_stories(source,[(0,9)],dict(count=5,min_seconds=30,max_seconds=90),
                         client,tmp_path,lambda *a:None)
    assert clips==[]
    assert all(p['stage'] not in ('montagem','revisão','correção única') for p in client.calls)
    report=json.loads((tmp_path/'editorial-progress.json').read_text())
    assert report['skipped_too_short']==1
    assert report['reviewed']==0


def test_published_edits_survive_new_transcript_ids_and_are_not_replaced(tmp_path):
    client=ScalingEditor()
    old=dict(id='published',title='Already downloaded',topic='Previous title',sentence_ids=[10000],
             duration=30,parts=[(0,30)],preview_status='ready',original_status='ready')
    clips=run(tmp_path,client,existing=[old])
    assert clips[0]==old
    assert len(clips)==2
    assert clips[1]['parts'][0][0]>30


def test_empty_retry_keeps_published_edits(tmp_path):
    old=dict(id='published',parts=[(0,30)],preview_status='ready')
    client=ScalingEditor()
    assert select_stories(Transcript('pt',[]),[],dict(count=5),client,tmp_path,lambda *a:None,existing=[old])==[old]
    assert client.calls==[]
