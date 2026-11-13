from copy import deepcopy
from types import SimpleNamespace
import threading
import time
import uuid

import pytest

from frib_ds import model_library as library
from frib_ds.ai_settings import AISettingsManager, AISelection
from frib_ds.quality_agent_settings import read_quality_settings, save_quality_settings
from frib_ds.model_runtime import inference_slot
from test_quality_agent import workspace
from test_ai_settings import local_model_server


@pytest.mark.parametrize('value,expected',[('brand-new:small','brand-new:small'),('brand-new','brand-new:latest'),
    ('https://ollama.com/library/brand-new:small','brand-new:small'),('organization/model:tag','organization/model:tag'),
    ('hf.co/organization/model:Q4_K_M','hf.co/organization/model:Q4_K_M')])
def test_future_names_and_official_links_need_no_catalogue_change(value,expected):
    assert library.NewModelRequest(model=value).model==expected


@pytest.mark.parametrize('value',['https://unrelated.invalid/model','https://user@ollama.com/library/x','https://ollama.com/library/x?download=true',
    '../file','a/../file','C:/Users/model','ollama pull model','file:///tmp/model','model;command'])
def test_new_model_inputs_cannot_be_commands_or_arbitrary_urls(value):
    with pytest.raises(ValueError): library.NewModelRequest(model=value)


@pytest.fixture
def managed(workspace,monkeypatch):
    services,event,settings=workspace
    monkeypatch.delenv('FRIB_LLM_PROVIDER',raising=False)
    monkeypatch.delenv('FRIB_LLM_MODEL',raising=False)
    services.config.models['llm']=AISelection(provider='ollama',base_url='http://127.0.0.1:11434',model='qwen3:4b').llm_config()
    monkeypatch.setenv('FRIB_MANAGED_OLLAMA_URL','http://127.0.0.1:11434')
    manager=AISettingsManager(services.config.config_dir)
    return services,manager,library.get_model_library(manager)


def test_delete_protects_both_assigned_roles_even_if_quality_agent_is_paused(managed,monkeypatch):
    services,manager,control=managed
    settings=read_quality_settings(services.config.config_dir)
    save_quality_settings(services.config.config_dir,settings.model_copy(update={'enabled':False}))
    monkeypatch.setattr(library,'list_models',lambda _: [{'id':'qwen3:4b','digest':'a'},{'id':'small-agent:latest','digest':'b'}])
    for model in ['qwen3:4b','small-agent:latest']:
        with pytest.raises(ValueError,match='assigned'):
            control.deletion_plan(library.ModelDeletion(provider='ollama',base_url='http://127.0.0.1:11434',model=model),services)


def test_delete_requires_current_preview_unloads_only_target_and_keeps_other_models(managed,monkeypatch):
    services,manager,control=managed
    models=[{'id':'old-unused:latest','digest':'old-digest','size_bytes':1000}]
    monkeypatch.setattr(library,'list_models',lambda _:deepcopy(models))
    monkeypatch.setattr(library,'_json_get',lambda _: {'models':[{'name':'old-unused:latest'}]})
    calls=[]
    class Session:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def post(self,url,**kwargs): calls.append(('unload',url,kwargs['json'])); return SimpleNamespace(status_code=200)
        def delete(self,url,**kwargs): calls.append(('delete',url,kwargs['json'])); models.clear(); return SimpleNamespace(status_code=200)
    monkeypatch.setattr(library,'_session',Session)
    request=library.ModelDeletion(provider='ollama',base_url='http://127.0.0.1:11434',model='old-unused')
    with pytest.raises(ValueError,match='preview'): control.delete(request,services)
    plan=control.deletion_plan(request,services)
    request.confirmation_token=plan['confirmation_token']
    assert control.delete(request,services)['deleted']
    assert [item[0] for item in calls]==['unload','delete']
    assert all(item[2]['model']=='old-unused:latest' for item in calls)
    assert services.config.models['llm']['model']=='qwen3:4b'
    assert services.repo.list_audit()[0]['action']=='model_deleted'


def test_deletion_preview_is_rechecked_after_a_role_change(managed,monkeypatch):
    services,manager,control=managed
    monkeypatch.setattr(library,'list_models',lambda _: [{'id':'old-unused:latest','digest':'old'}])
    request=library.ModelDeletion(provider='ollama',base_url='http://127.0.0.1:11434',model='old-unused')
    request.confirmation_token=control.deletion_plan(request,services)['confirmation_token']
    settings=read_quality_settings(services.config.config_dir)
    save_quality_settings(services.config.config_dir,settings.model_copy(update={'selection':AISelection(provider='ollama',base_url=request.base_url,model='old-unused:latest')}))
    with pytest.raises(ValueError,match='assigned'): control.delete(request,services)


def wait_setup(manager):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        status=manager.setup_status()
        if status['status']!='running': return status
        time.sleep(.03)
    raise AssertionError('Model setup did not finish')


def test_a_new_uncatalogued_model_downloads_tests_and_replaces_chat(managed,local_model_server,monkeypatch):
    services,manager,control=managed; base,captured=local_model_server
    monkeypatch.setenv('FRIB_DEPENDENCIES_DIR',str(services.config.config_dir.parent/'dependencies'))
    monkeypatch.setenv('FRIB_BUNDLED_OLLAMA_URL',base); monkeypatch.setenv('FRIB_MANAGED_OLLAMA_URL',base)
    monkeypatch.setattr(library,'start_bundled_server',lambda:{'base_url':base})
    old_embeddings=services.embedding; old_quality=read_quality_settings(services.config.config_dir)
    control.install(library.NewModelRequest(model='future-family:tiny',role='chat'),services)
    status=wait_setup(manager)
    assert status['status']=='completed',status
    assert services.llm.model=='future-family:tiny'
    assert services.embedding is old_embeddings
    assert read_quality_settings(services.config.config_dir)==old_quality
    assert captured[0][0]=='/api/pull' and captured[0][1]['model']=='future-family:tiny'


def test_quality_role_setup_keeps_main_chat_and_embeddings(managed,local_model_server,monkeypatch):
    from frib_ds import quality_agent
    services,manager,control=managed; base,captured=local_model_server
    monkeypatch.setenv('FRIB_DEPENDENCIES_DIR',str(services.config.config_dir.parent/'dependencies'))
    monkeypatch.setenv('FRIB_BUNDLED_OLLAMA_URL',base); monkeypatch.setenv('FRIB_MANAGED_OLLAMA_URL',base)
    monkeypatch.setattr(library,'start_bundled_server',lambda:{'base_url':base})
    monkeypatch.setattr(quality_agent,'quality_model_probe',lambda _: {'structured_findings':True,'sample_coordinates':True})
    before=deepcopy(services.config.models['llm']); embedding=services.embedding
    control.install(library.NewModelRequest(model='future-small:1b',role='quality'),services)
    status=wait_setup(manager)
    assert status['status']=='completed',status
    assert services.config.models['llm']==before and services.embedding is embedding
    assert read_quality_settings(services.config.config_dir).selection.model=='future-small:1b'


def test_interactive_inference_runs_before_a_waiting_background_agent():
    key='test-priority-'+uuid.uuid4().hex
    order=[]; ready=threading.Event()
    def interactive():
        ready.set()
        with inference_slot(key): order.append('interactive')
    def background():
        with inference_slot(key,background=True): order.append('background')
    with inference_slot(key,background=True):
        first=threading.Thread(target=interactive); first.start(); assert ready.wait(1)
        from frib_ds import model_runtime
        deadline=time.monotonic()+2
        while model_runtime._servers[key]['interactive']<1 and time.monotonic()<deadline: time.sleep(.01)
        second=threading.Thread(target=background); second.start()
    first.join(2); second.join(2)
    assert order==['interactive','background']
