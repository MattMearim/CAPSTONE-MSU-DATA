"""Install future local models and delete unused models through guarded UI APIs."""
from copy import deepcopy
import hashlib
import json
import os
import re
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from frib_ds.ai_settings import AISelection, ApplySelection, ModelServer, DEFAULT_URLS, _json_get, _session, list_models, selection_from_models, start_bundled_server
from frib_ds.quality_agent_models import QualityAgentSettings
from frib_ds.quality_agent_settings import read_quality_settings, save_quality_settings


def model_name(value):
    value=value.strip()
    if '://' in value:
        url=urlsplit(value)
        if url.scheme!='https' or url.hostname!='ollama.com' or url.username or url.password or url.port or url.query or url.fragment or not url.path.startswith('/library/'):
            raise ValueError('Paste an official https://ollama.com/library/... link or a plain Ollama model name.')
        value=unquote(url.path[len('/library/'):]).rstrip('/')
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}',value) or '..' in value.split('/')
            or any(not part for part in value.split('/')) or any(':' in part for part in value.split('/')[:-1])):
        raise ValueError('Enter a model name and optional tag, not a command, file path, or download URL.')
    if ':' not in value.rsplit('/',1)[-1]: value+=':latest'
    return value


class NewModelRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    model: str = Field(min_length=1,max_length=500)
    role: Literal['chat','quality','install_only']='chat'

    @field_validator('model')
    @classmethod
    def clean(cls,value): return model_name(value)


class QualityConfiguration(BaseModel):
    model_config=ConfigDict(extra='forbid')
    settings: QualityAgentSettings
    test_token: str | None = Field(default=None,max_length=64)


class ModelDeletion(ModelServer):
    model: str = Field(min_length=1,max_length=200)
    confirmation_token: str | None = Field(default=None,max_length=64)


def get_model_library(manager):
    with manager._lock:
        if not hasattr(manager,'_library'): manager._library=ModelLibrary(manager)
        return manager._library


class ModelLibrary:
    def __init__(self,manager):
        self.manager=manager; self._quality_tokens={}; self._deletions={}

    def test_quality(self,selection):
        from frib_ds.quality_agent import quality_model_probe
        manager=self.manager
        if not manager._probe_slot.acquire(blocking=False): raise ValueError('Another model test is running. Wait for it to finish.')
        try:
            capabilities=quality_model_probe(selection)
            token=uuid.uuid4().hex
            with manager._lock:
                self._quality_tokens={key:value for key,value in self._quality_tokens.items() if value[1]>time.monotonic()}
                if len(self._quality_tokens)>=20: self._quality_tokens.pop(next(iter(self._quality_tokens)))
                self._quality_tokens[token]=(manager._fingerprint(selection),time.monotonic()+600)
            return {'passed':True,'test_token':token,'capabilities':capabilities,'valid_for_seconds':600}
        finally: manager._probe_slot.release()

    def configure_quality(self,request,services):
        with self.manager._lock:
            previous=read_quality_settings(services.config.config_dir)
            selection=request.settings.selection
            if selection is not None and selection!=previous.selection:
                tested=self._quality_tokens.get(request.test_token)
                if not tested or tested[0]!=self.manager._fingerprint(selection) or tested[1]<time.monotonic():
                    raise ValueError('Test this exact quality-agent model before saving its assignment.')
                self._quality_tokens.pop(request.test_token,None)
            save_quality_settings(services.config.config_dir,request.settings)
            services.repo.record_audit('quality_agent_settings','system','quality-agent',
                {'previous':previous.model_dump(mode='json'),'settings':request.settings.model_dump(mode='json')})
            if request.settings.enabled: services.quality_agent.start()
        return {'saved':True,'settings':request.settings.model_dump(mode='json'),'chat_model_changed':False}

    def install(self,request,services):
        manager=self.manager
        if not os.getenv('FRIB_DEPENDENCIES_DIR'): raise ValueError('Open START_PROJECT.cmd to manage bundled model downloads.')
        selection=AISelection(provider='ollama',base_url=os.getenv('FRIB_BUNDLED_OLLAMA_URL',DEFAULT_URLS['ollama']),
                              model=request.model,context_length=8192,max_output_tokens=2048,timeout_seconds=300)
        with manager._lock:
            if manager._setup.get('status')=='running' or any(job['status']=='downloading' for job in manager._jobs.values()):
                raise ValueError('Another model setup is running. Let it finish or cancel it first.')
            manager._setup_cancel.clear()
            manager._setup={'job_id':uuid.uuid4().hex,'kind':'install','status':'running','stage':'starting',
                            'request':request.model_dump(),'selection':selection.model_dump(),'role':request.role,
                            'previous':selection_from_models(services.config.models).model_dump(),
                            'message':'Preparing the requested model','completed':0,'total':0}
            manager._setup_update()
        threading.Thread(target=self._install,args=(request,selection,services),daemon=True,name='frib-model-library-install').start()
        return manager.setup_status()

    def _install(self,request,selection,services):
        from frib_ds.ai_storage import AIStorageLock
        manager=self.manager
        try:
            with AIStorageLock():
                started=start_bundled_server()
                if started['base_url'].rstrip('/')!=selection.base_url: raise ValueError('The bundled model address changed. Refresh and retry.')
                if request.model not in {model_name(item['id']) for item in list_models(selection)}:
                    manager._setup_update(stage='downloading',message='Downloading '+request.model)
                    job=manager.download(selection,automatic=True)
                    manager._setup_update(download_job=job['job_id'])
                    while True:
                        status=manager.download_status(job['job_id'])
                        manager._setup_update(message=status['message'],completed=status['completed'],total=status['total'])
                        if manager._setup_cancel.is_set() or status['status']=='cancelled':
                            manager._setup_update(status='cancelled',stage='cancelled',message='Setup cancelled. Existing role assignments were kept.'); return
                        if status['status']=='failed': raise ValueError(status['message'])
                        if status['status']=='completed': break
                        time.sleep(1)
                if manager._setup_cancel.is_set():
                    manager._setup_update(status='cancelled',stage='cancelled',message='Setup cancelled. Existing role assignments were kept.'); return
                if request.role!='install_only':
                    manager._setup_update(stage='testing',message='Checking model compatibility for its selected role')
                    tested=self.test_quality(selection) if request.role=='quality' else manager.test(selection)
                    if manager._setup_cancel.is_set():
                        manager._setup_update(status='cancelled',stage='cancelled',message='Setup cancelled. Existing role assignments were kept.'); return
                    manager._setup_update(stage='applying',message='Saving the tested role assignment')
                    if request.role=='quality':
                        settings=read_quality_settings(services.config.config_dir).model_copy(update={'selection':selection,'enabled':True})
                        self.configure_quality(QualityConfiguration(settings=settings,test_token=tested['test_token']),services)
                    else:
                        manager.apply(ApplySelection(selection=selection,profile_name='My selected AI',test_token=tested['test_token']),services,setup_apply=True)
                services.repo.record_audit('model_installed','model',request.model,{'role':request.role,'tested':request.role!='install_only'})
                manager._setup_update(status='completed',stage='completed',message='Model installed'+(' and assigned to '+request.role if request.role!='install_only' else ' in the library')+'.')
        except Exception as exc: manager._setup_update(status='failed',stage='failed',message=str(exc)[:600],previous_model_preserved=True)

    def protected_roles(self,services,server):
        active=selection_from_models(services.config.models)
        roles={}
        key=lambda name:model_name(name) if server.provider=='ollama' else name
        if active.provider==server.provider and active.base_url==server.base_url: roles.setdefault(key(active.model),[]).append('Main AI')
        quality=read_quality_settings(services.config.config_dir)
        if quality.selection and quality.selection.provider==server.provider and quality.selection.base_url==server.base_url:
            roles.setdefault(key(quality.selection.model),[]).append('Data Quality Agent')
        return roles

    def inventory(self,services,server):
        roles=self.protected_roles(services,server)
        return {'models':[{**entry,'roles':roles.get(model_name(entry['id']) if server.provider=='ollama' else entry['id'],[])} for entry in list_models(server)],
                'can_delete':self.manager.can_download(server),'settings':read_quality_settings(services.config.config_dir).model_dump(mode='json')}

    def _delete_target(self,request,services):
        manager=self.manager
        if not manager.can_download(request): raise ValueError('Model deletion is limited to this workspace\'s bundled Ollama server.')
        if manager._setup.get('status')=='running' or any(job['status']=='downloading' for job in manager._jobs.values()):
            raise ValueError('Wait for model setup/downloads to finish before deleting a model.')
        name=model_name(request.model)
        roles=self.protected_roles(services,request).get(name,[])
        if roles: raise ValueError('This model is assigned to '+', '.join(roles)+'. Assign another model or remove that role before deleting it.')
        target=next((item for item in list_models(request) if model_name(item['id'])==name),None)
        if target is None: raise ValueError('The model is not installed. Refresh the library.')
        return target

    def deletion_plan(self,request,services):
        with self.manager._lock:
            target=self._delete_target(request,services)
            token=uuid.uuid4().hex
            self._deletions={key:value for key,value in self._deletions.items() if value['expires']>time.monotonic()}
            self._deletions[token]={'model':target['id'],'base_url':request.base_url,'digest':target.get('digest'),'expires':time.monotonic()+300}
            return {'confirmation_token':token,'model':target['id'],'size_bytes':target.get('size_bytes'),
                    'message':'Deletes this model from the local engine. Shared layers used by other models are retained; freed disk space can be smaller than the model size. Saved profile settings are retained.'}

    def delete(self,request,services):
        from frib_ds.model_runtime import inference_slot
        manager=self.manager
        with manager._lock:
            target=self._delete_target(request,services)
            plan=self._deletions.get(request.confirmation_token)
            if not plan or plan['expires']<time.monotonic() or plan['model']!=target['id'] or plan['base_url']!=request.base_url or plan['digest']!=target.get('digest'):
                raise ValueError('Refresh the deletion preview and confirm this exact model again.')
            if not manager._probe_slot.acquire(blocking=False): raise ValueError('A model is being tested. Retry deletion after it finishes.')
            try:
                with inference_slot(request.base_url,timeout=30):
                    loaded=_json_get(request.base_url+'/api/ps').get('models',[])
                    with _session() as session:
                        if any(model_name(item.get('name') or item.get('model') or '')==model_name(target['id']) for item in loaded):
                            response=session.post(request.base_url+'/api/generate',json={'model':target['id'],'keep_alive':0,'stream':False},timeout=(3,30),allow_redirects=False)
                            if response.status_code!=200: raise ValueError('The old model could not be unloaded. Retry after active requests finish.')
                        response=session.delete(request.base_url+'/api/delete',json={'model':target['id']},timeout=(3,60),allow_redirects=False)
                        if response.status_code!=200: raise ValueError('The model engine did not confirm deletion. Refresh the model list.')
                    manager._tests.clear(); self._quality_tokens.clear(); self._deletions.pop(request.confirmation_token,None)
            finally: manager._probe_slot.release()
            services.repo.record_audit('model_deleted','model',target['id'],{'digest':target.get('digest'),'size_bytes':target.get('size_bytes'),'shared_layers_retained':True})
            return {'deleted':True,'model':target['id'],'message':'Unused model deleted. Assigned models and document search were preserved.'}
