from copy import deepcopy
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

STATE=None


def run_ui():
    from frib_ds.dashboard.ai_ui import render_ai_settings
    def get(path):
        if path=='/system/ai': return deepcopy(STATE['info'])
        if path=='/system/ai/setup': return {'status':'idle'}
        if path=='/system/ai/quality-agent': return {'settings':deepcopy(STATE['quality']),'jobs':{}}
        if path.startswith('/system/ai/library'):
            quality=STATE['quality'].get('selection')
            return {'models':[{'id':model,'size_bytes':1000,'roles':['Main AI'] if model=='qwen3:4b' else ['Data Quality Agent'] if quality and quality['model']==model else []} for model in STATE['models']], 'can_delete':True}
        if path.startswith('/system/ai/models'): return {'models':[{'id':model} for model in STATE['models']]}
        if path.startswith('/system/ai/recommendations'):
            from frib_ds.ai_hardware import plan_models
            return plan_models({'memory':{'total_gib':16,'available_gib':8},'disk':{'free_gib':80},'gpu':{'devices':[{'name':'GPU','memory_gib':4}]}},STATE['models'])
        raise AssertionError(path)
    def post(path,payload):
        STATE['calls'].append((path,deepcopy(payload)))
        if path.endswith('/delete-preview'): return {'model':payload['model'],'confirmation_token':'preview-token','message':'Deletes only this unused model.'}
        if path.endswith('/delete'):
            STATE['models'].remove(payload['model']); return {'deleted':True,'message':'Unused model deleted.'}
        if path.endswith('/install'): return {'status':'running'}
        if path.endswith('/quality-agent/test'): return {'passed':True,'test_token':'quality-tested'}
        if path.endswith('/quality-agent/configure'):
            STATE['quality']=deepcopy(payload['settings']); return {'saved':True}
        raise AssertionError(path)
    render_ai_settings(get,post,str)


@pytest.fixture
def ui():
    from frib_ds.ai_settings import AISelection
    global STATE
    STATE={'info':{'active':AISelection(provider='ollama',model='qwen3:4b',base_url='http://127.0.0.1:11434').model_dump(),
                   'bundled_ollama_available':True,'managed_ollama_url':'http://127.0.0.1:11434','setup':{'status':'idle'}},
           'quality':{'enabled':False,'automatic':True,'selection':None,'max_model_calls':4},
           'models':['qwen3:4b','qwen3:8b','qwen3:1.7b'],'calls':[]}
    return AppTest.from_string('from test_model_library_ui import run_ui; run_ui()',default_timeout=15).run()


def test_download_new_release_uses_one_button_and_role(ui):
    ui.segmented_control(key='ai_setup_view').set_value('Models').run()
    assert not ui.exception and not STATE['calls']
    ui.text_input(key='library_new_name').set_value('new-family:tiny').run()
    ui.selectbox(key='library_new_role').select('quality').run()
    ui.button(key='library_install').click().run()
    assert not ui.exception
    assert STATE['calls']==[('/system/ai/library/install',{'model':'new-family:tiny','role':'quality'})]


def test_delete_excludes_assigned_model_and_requires_preview_confirmation(ui):
    ui.segmented_control(key='ai_setup_view').set_value('Models').run()
    assert 'qwen3:4b' not in ui.selectbox(key='library_delete_model').options
    ui.selectbox(key='library_delete_model').select('qwen3:8b').run()
    ui.button(key='library_delete_preview').click().run()
    assert ui.button(key='library_delete_execute').disabled
    ui.checkbox(key='library_delete_confirm_preview-token').check().run()
    ui.button(key='library_delete_execute').click().run()
    assert not ui.exception
    assert 'qwen3:8b' not in STATE['models'] and 'qwen3:4b' in STATE['models']


def test_quality_model_is_tested_then_enabled_without_changing_chat(ui):
    before=deepcopy(STATE['info']['active'])
    ui.segmented_control(key='ai_setup_view').set_value('Quality agent').run()
    ui.selectbox(key='qa_model').select('qwen3:1.7b').run()
    ui.button(key='qa_enable').click().run()
    assert not ui.exception
    assert [path for path,_ in STATE['calls']]==['/system/ai/quality-agent/test','/system/ai/quality-agent/configure']
    assert STATE['quality']['selection']['model']=='qwen3:1.7b' and STATE['quality']['enabled']
    assert STATE['info']['active']==before


def test_quality_toggle_pauses_and_resumes_without_retesting_or_changing_chat(ui):
    before=deepcopy(STATE['info']['active'])
    ui.segmented_control(key='ai_setup_view').set_value('Quality agent').run()
    assert ui.toggle(key='qa_enabled_toggle').disabled
    ui.selectbox(key='qa_model').select('qwen3:1.7b').run()
    ui.button(key='qa_enable').click().run()
    selection=deepcopy(STATE['quality']['selection'])
    STATE['calls'].clear()
    ui.toggle(key='qa_enabled_toggle').set_value(False).run()
    assert not ui.exception and not STATE['quality']['enabled']
    assert STATE['quality']['selection']==selection
    ui.toggle(key='qa_enabled_toggle').set_value(True).run()
    assert not ui.exception and STATE['quality']['enabled']
    assert len(STATE['calls'])==2 and all(path.endswith('/configure') for path,_ in STATE['calls'])
    assert STATE['info']['active']==before
