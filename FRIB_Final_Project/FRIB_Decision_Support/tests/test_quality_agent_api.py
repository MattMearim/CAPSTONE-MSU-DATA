import json

import pytest

from test_api_lifecycle import api_environment
from test_quality_agent import finding
from frib_ds import quality_agent as qa
from frib_ds.ai_settings import AISelection


def test_enable_separate_agent_and_automatically_queue_incoming_data(api_environment,monkeypatch):
    client,state,_=api_environment
    services=state['services']
    monkeypatch.setattr(qa,'quality_model_probe',lambda _: {'structured_findings':True,'sample_coordinates':True})
    monkeypatch.setattr(services.quality_agent,'start',lambda:None)
    selected=AISelection(provider='ollama',base_url='http://127.0.0.1:11434',model='small-agent',context_length=8192,max_output_tokens=2048).model_dump()
    tested=client.post('/system/ai/quality-agent/test',json=selected)
    assert tested.status_code==200,tested.text
    settings={'enabled':True,'automatic':True,'selection':selected,'max_model_calls':1}
    configured=client.post('/system/ai/quality-agent/configure',json={'settings':settings,'test_token':tested.json()['test_token']})
    assert configured.status_code==200,configured.text
    from frib_ds.models import EngineeringEvent,Signal,Provenance
    event=EngineeringEvent(event_id='INCOMING-QA',domain='generic',event_type='measurement',
        signals=[Signal(name='sensor',unit='V',sample_rate_hz=1,timestamps_s=list(range(65)),values=[1]*32+[99]+[1]*32)],provenance=Provenance(source='temporary API test'))
    assert client.post('/system/ai/quality-agent/configure',json={'settings':{**settings,'enabled':False}}).status_code==200
    paused=event.model_copy(update={'event_id':'IMPORTED-WHILE-AGENT-OFF'})
    assert client.post('/events',json=paused.model_dump(mode='json')).status_code==200
    paused_status=client.get('/events/IMPORTED-WHILE-AGENT-OFF/quality-agent').json()
    assert not paused_status['enabled'] and paused_status['latest'] is None
    assert client.get('/events/IMPORTED-WHILE-AGENT-OFF').json()['signals'][0]['values'][32]==99
    assert client.post('/system/ai/quality-agent/configure',json={'settings':settings}).status_code==200
    stored=client.post('/events',json=event.model_dump(mode='json'))
    assert stored.status_code==200,stored.text
    status=client.get('/events/INCOMING-QA/quality-agent').json()
    assert status['enabled'] and status['latest']['status']=='queued'
    assert services.config.models['llm']['provider']=='mock'
    assert services.config.models['embeddings']['provider']=='hash'
    class Model:
        model='small-agent'
        def chat(self,*args,**kwargs): return json.dumps({'summary':'A candidate','findings':[finding().model_dump()],'read_requests':[]})
    monkeypatch.setattr(qa,'build_llm_provider',lambda _:Model())
    from frib_ds.quality_agent_models import QualityAgentSettings
    services.quality_agent._run(status['latest'],QualityAgentSettings.model_validate(settings))
    report=client.get('/events/INCOMING-QA/quality-agent').json()['report']
    item=report['findings'][0]
    path=f"/quality-agent/runs/{report['run_id']}/findings/{item['finding_id']}"
    denied=client.post(path+'/repair',json={'reviewer':'Reviewer','confirmed':True,'proposal_hash':item['proposal_hash']})
    assert denied.status_code==409
    assert client.post(path+'/review',json={'decision':'accept','reviewer':'Reviewer'}).status_code==200
    repaired=client.post(path+'/repair',json={'reviewer':'Reviewer','confirmed':True,'proposal_hash':item['proposal_hash']})
    assert repaired.status_code==200,repaired.text
    assert client.get('/events/INCOMING-QA').json()['signals'][0]['values'][32]==99
    assert client.get('/events/'+repaired.json()['event_id']).json()['signals'][0]['values'][32]==1


def test_unverified_quality_assignment_and_arbitrary_tools_are_rejected(api_environment):
    client,_,_=api_environment
    selected=AISelection(provider='ollama',base_url='http://127.0.0.1:11434',model='new-agent').model_dump()
    response=client.post('/system/ai/quality-agent/configure',json={'settings':{'enabled':True,'automatic':True,'selection':selected,'max_model_calls':4}})
    assert response.status_code==400
    assert client.post('/system/ai/quality-agent/configure',json={'settings':{'enabled':True,'selection':selected,'sql':'DROP TABLE events'}}).status_code==422
    assert client.post('/system/ai/library/install',json={'model':'https://unrelated.invalid/model','role':'chat'}).status_code==422
