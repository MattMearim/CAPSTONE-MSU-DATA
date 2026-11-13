"""Data-only AI findings, verified coordinates and human-approved copy repairs."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from frib_ds import quality_agent as qa
from frib_ds.quality_agent_models import AgentFinding, AgentResponse, QualityAgentSettings, ReadRequest, FindingReview, RepairApproval
from frib_ds.quality_agent_settings import save_quality_settings
from frib_ds.quality_agent_tools import ReadOnlyDataTools, fingerprint
from frib_ds.ai_settings import AISelection
from frib_ds.models import EngineeringEvent, Signal, Provenance
from frib_ds.config import get_config
from frib_ds.bootstrap import Services, get_services
from frib_ds.storage.reset import DataLifecycleLock
from frib_ds.dashboard.event_view import signal_figure


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setenv('FRIB_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('FRIB_LLM_PROVIDER','mock'); monkeypatch.setenv('FRIB_EMBEDDING_PROVIDER','hash'); monkeypatch.setenv('FRIB_VECTOR_PROVIDER','sqlite')
    get_config.cache_clear(); get_services.cache_clear()
    services=Services()
    event=EngineeringEvent(event_id='QA-DATA',domain='generic',event_type='measurement',
        signals=[Signal(name='sensor',unit='V',sample_rate_hz=1,timestamps_s=list(range(65)),values=[1]*32+[99]+[1]*32)],
        provenance=Provenance(source='test source'))
    services.repo.save_event(event); services.files.save(event)
    settings=QualityAgentSettings(enabled=True,selection=AISelection(provider='ollama',base_url='http://127.0.0.1:11434',model='small-agent',context_length=8192,max_output_tokens=2048))
    save_quality_settings(services.config.config_dir,settings)
    monkeypatch.setattr(services.quality_agent,'start',lambda:None)
    yield services,event,settings
    services.quality_agent.stop(); get_config.cache_clear(); get_services.cache_clear()


def finding(**updates):
    return AgentFinding.model_validate({'title':'Possible isolated sensor error','category':'unexpected pattern','severity':'medium','confidence':.8,
        'signal_name':'s0','start_index':32,'end_index':32,'evidence':[{'index':32,'value':99.}], 'explanation':'One observed sample is 99 V while the nearby samples are 1 V.',
        'recommended_check':'Compare the original instrument record before correcting it.',
        'repair':{'action':'replace_sample','value':1.,'rationale':'Only if the instrument record confirms the point failed.'},**updates})


def fake_provider(monkeypatch,responses):
    calls=[]
    class Model:
        model='small-agent'; provider_name='ollama'
        def chat(self,messages,json_schema=None):
            calls.append(messages)
            value=responses[min(len(calls)-1,len(responses)-1)]
            return value() if callable(value) else json.dumps(value)
    monkeypatch.setattr(qa,'build_llm_provider',lambda _:Model())
    return calls


def test_read_tools_do_not_offer_sql_and_require_observed_coordinates(workspace):
    services,event,_=workspace
    tools=ReadOnlyDataTools(services,event)
    overview=tools.overview()
    assert 32 in tools.observed['s0']
    assert tools.validate_finding(finding())['anchors']==[{'index':32,'time_s':32.,'value':99.}]
    with pytest.raises(ValueError,match='inspected'):
        tools.validate_finding(finding(start_index=100000,end_index=100000))
    with pytest.raises(ValueError): ReadRequest(tool='execute_sql',event_id='DROP TABLE events')
    with pytest.raises(ValueError): tools.compare_dataset('not-allowed')
    with pytest.raises(ValueError): ReadRequest(tool='read_window',signal_name='s0',count=10000)
    assert 'synthetic_ground_truth' not in json.dumps(overview)
    assert tools.read_window('s0',30,5)['samples'][2]==[32,32.,99.]
    with pytest.raises(ValueError,match='does not match'):
        tools.validate_finding(finding(evidence=[{'index':32,'value':2.865}]))
    with pytest.raises(ValueError,match='exact inspected'):
        tools.validate_finding(finding(evidence=[]))


def test_agent_adds_graph_flags_without_rag_or_modifying_source(workspace,monkeypatch):
    services,event,settings=workspace
    original=services.files.original(event.event_id).read_bytes()
    calls=fake_provider(monkeypatch,[{'summary':'One candidate needs review.','findings':[finding().model_dump()],'read_requests':[]}])
    monkeypatch.setattr(services.rag,'query',lambda *args:pytest.fail('The quality agent must not call RAG'))
    run=services.quality_agent.schedule(event.event_id,force=True)
    services.quality_agent._run(run,settings)
    report=services.repo.quality_run(run['run_id'])
    assert report['status']=='partial' and report['findings'][0]['anchors'][0]['value']==99
    assert not report['coverage']['all_samples_directly_inspected']
    assert services.files.original(event.event_id).read_bytes()==original
    assert services.repo.get_event(event.event_id).signals[0].values[32]==99
    assert calls and 'read-only' in calls[0][0]['content']
    fig=signal_figure(event.model_dump()['signals'],{'sensor':'Sensor'},(0,64),agent_report=report)
    flag=next(trace for trace in fig.data if trace.name=='AI quality proposal')
    assert list(flag.x)==[32] and list(flag.y)==[99]


def test_agent_can_request_closer_read_windows(workspace,monkeypatch):
    services,event,settings=workspace
    calls=fake_provider(monkeypatch,[{'summary':'Inspect the neighborhood.','findings':[],'read_requests':[{'tool':'read_window','signal_name':'s0','start_index':28,'count':9}]},
        {'summary':'The candidate is isolated.','findings':[finding().model_dump()],'read_requests':[]}])
    run=services.quality_agent.schedule(event.event_id,force=True)
    services.quality_agent._run(run,settings)
    report=services.repo.quality_run(run['run_id'])
    assert len(calls)==2 and report['coverage']['windows']==[{'signal_name':'s0','first_index':28,'last_index':36}]
    assert '99.0' in calls[1][1]['content']


def test_switch_off_during_final_call_discards_new_findings(workspace,monkeypatch):
    services,event,settings=workspace
    def turn_off():
        save_quality_settings(services.config.config_dir,settings.model_copy(update={'enabled':False}))
        return json.dumps({'summary':'Must not be published','findings':[finding().model_dump()],'read_requests':[]})
    calls=fake_provider(monkeypatch,[turn_off])
    run=services.quality_agent.schedule(event.event_id,force=True)
    services.quality_agent._run(run,settings.model_copy(update={'max_model_calls':1}))
    stored=services.repo.quality_run(run['run_id'])
    assert len(calls)==1 and stored['status']=='cancelled' and not stored['findings']
    assert services.quality_agent.event_status(event.event_id)['report'] is None
    assert services.quality_agent.schedule(event.event_id,force=True)=={'status':'disabled'}
    assert services.repo.get_event(event.event_id).signals[0].values[32]==99


def test_repeated_reads_stop_when_no_new_evidence_or_findings(workspace,monkeypatch):
    services,event,settings=workspace
    response={'summary':'Inspect a point','findings':[],
              'read_requests':[{'tool':'read_window','signal_name':'s0','start_index':30,'count':5}]}
    calls=fake_provider(monkeypatch,[response])
    run=services.quality_agent.schedule(event.event_id,force=True)
    services.quality_agent._run(run,settings)
    report=services.repo.quality_run(run['run_id'])
    assert len(calls)==2 and report['model_calls']==2
    assert len(report['coverage']['windows'])==1


def test_invalid_model_coordinates_are_rejected_and_audited(workspace,monkeypatch):
    services,event,settings=workspace
    fake_provider(monkeypatch,[{'summary':'Bad reference','findings':[finding(start_index=999,end_index=999).model_dump()],'read_requests':[]}])
    run=services.quality_agent.schedule(event.event_id,force=True)
    services.quality_agent._run(run,settings.model_copy(update={'max_model_calls':1}))
    report=services.repo.quality_run(run['run_id'])
    assert not report['findings'] and report['validation_notes']
    assert report['trace'][0]['model_response']['findings']


def test_human_approval_is_required_and_repair_creates_only_one_copy(workspace,monkeypatch):
    services,event,settings=workspace
    fake_provider(monkeypatch,[{'summary':'A candidate','findings':[finding().model_dump()],'read_requests':[]}])
    run=services.quality_agent.schedule(event.event_id,force=True); services.quality_agent._run(run,settings)
    stored=services.repo.quality_run(run['run_id']); item=stored['findings'][0]
    approval=RepairApproval(reviewer='Reviewer',confirmed=True,proposal_hash=item['proposal_hash'])
    with pytest.raises(ValueError,match='Accept'): services.quality_agent.apply_repair(run['run_id'],item['finding_id'],approval)
    services.quality_agent.review(run['run_id'],item['finding_id'],FindingReview(decision='accept',reviewer='Reviewer',comments='Verified against source.'))
    with pytest.raises(ValueError,match='explicitly authorize'):
        services.quality_agent.apply_repair(run['run_id'],item['finding_id'],approval.model_copy(update={'confirmed':False}))
    result=services.quality_agent.apply_repair(run['run_id'],item['finding_id'],approval)
    assert services.repo.get_event(event.event_id).signals[0].values[32]==99
    assert services.repo.get_event(result['event_id']).signals[0].values[32]==1
    assert services.quality_agent.apply_repair(run['run_id'],item['finding_id'],approval)['already_created']
    assert services.repo.data_counts()['events']==2
    assert any(row['action']=='quality_agent_repair' for row in services.repo.list_audit())


def test_dismissed_findings_leave_the_graph(workspace,monkeypatch):
    services,event,settings=workspace
    fake_provider(monkeypatch,[{'summary':'A candidate','findings':[finding().model_dump()],'read_requests':[]}])
    run=services.quality_agent.schedule(event.event_id,force=True); services.quality_agent._run(run,settings)
    item=services.repo.quality_run(run['run_id'])['findings'][0]
    services.quality_agent.review(run['run_id'],item['finding_id'],FindingReview(decision='dismiss',reviewer='Reviewer'))
    report=services.repo.quality_run(run['run_id'])
    fig=signal_figure(event.model_dump()['signals'],{'sensor':'Sensor'},(0,64),agent_report=report)
    assert not any(trace.name=='AI quality proposal' for trace in fig.data)


def test_reset_during_inference_cannot_resurrect_old_findings(workspace,monkeypatch):
    services,event,settings=workspace
    def reset_then_answer():
        with DataLifecycleLock(services.config.data_dir): services.reset_data()
        return json.dumps({'summary':'Old candidate','findings':[finding().model_dump()],'read_requests':[]})
    fake_provider(monkeypatch,[reset_then_answer])
    run=services.quality_agent.schedule(event.event_id,force=True); services.quality_agent._run(run,settings)
    assert services.repo.quality_run(run['run_id']) is None
    assert services.repo.data_counts()['events']==0
    assert [row['action'] for row in services.repo.list_audit()]==['reset']
