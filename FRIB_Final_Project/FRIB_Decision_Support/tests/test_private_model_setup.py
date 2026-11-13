"""Fresh-clone model setup reuses weights and refuses incomplete downloads."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

@pytest.fixture
def setup_module(monkeypatch):
    root=Path(__file__).resolve().parents[3]/'dependencies'
    if not (root/'Prepare-Models.py').is_file(): pytest.skip('Private Windows setup is only present in the repository bundle.')
    monkeypatch.syspath_prepend(str(root))
    spec=importlib.util.spec_from_file_location('frib_first_model_setup',root/'Prepare-Models.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'environment',lambda:{'FRIB_BUNDLED_OLLAMA_URL':'http://127.0.0.1:11434'})
    monkeypatch.setattr(module,'selected_ai',lambda:SimpleNamespace(provider='ollama',base_url='http://127.0.0.1:11434',model='tiny:latest'))
    started=[];monkeypatch.setattr(module,'start_bundled_ollama',lambda:started.append(True))
    return module,started

def session(module,monkeypatch,installed,lines):
    calls=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def raise_for_status(self): pass
        def json(self): return {'models':installed}
        def iter_lines(self): return (json.dumps(item).encode() for item in lines)
    class Session(Response):
        def get(self,*args,**kwargs): return Response()
        def post(self,url,**kwargs): calls.append((url,kwargs));return Response()
    monkeypatch.setattr(module.requests,'Session',Session)
    return calls

def test_existing_weights_are_reused_without_download(setup_module,monkeypatch):
    module,started=setup_module
    calls=session(module,monkeypatch,[{'name':'tiny:latest'}],[])
    module.prepare()
    assert started==[True] and not calls

@pytest.mark.parametrize('lines,match',[
    ([{'error':'storage full'}],'storage full'),
    ([{'status':'pulling manifest'}],'did not confirm'),
    ([], 'did not confirm'),
])
def test_failed_or_interrupted_download_is_not_reported_ready(setup_module,monkeypatch,lines,match):
    module,_=setup_module
    session(module,monkeypatch,[],lines)
    with pytest.raises(RuntimeError,match=match): module.prepare()

def test_successful_download_uses_the_configured_private_engine(setup_module,monkeypatch):
    module,_=setup_module
    calls=session(module,monkeypatch,[],[{'status':'pulling weights','completed':2,'total':4},{'status':'success'}])
    module.prepare()
    assert calls[0][0]=='http://127.0.0.1:11434/api/pull'
    assert calls[0][1]['json']=={'model':'tiny:latest','stream':True}
    assert calls[0][1]['allow_redirects'] is False

def test_external_server_is_not_started_or_downloaded_to(setup_module,monkeypatch):
    module,started=setup_module
    monkeypatch.setattr(module,'selected_ai',lambda:SimpleNamespace(provider='lmstudio',base_url='http://127.0.0.1:1234/v1',model='external'))
    calls=session(module,monkeypatch,[],[])
    module.prepare()
    assert not started and not calls
