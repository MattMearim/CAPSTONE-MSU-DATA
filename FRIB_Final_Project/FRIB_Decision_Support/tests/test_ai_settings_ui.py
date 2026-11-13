"""AI settings controls require testing the exact selection before application."""
from copy import deepcopy
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

STATE = None


def run_ui():
    from frib_ds.dashboard.ai_ui import render_ai_settings
    def get(path):
        if path == '/system/ai/resources':
            return {'measured_at': '2026-11-12T00:00:00Z', 'sample_seconds': .25, 'active': STATE['info']['active'],
                'system': {'ram_used_bytes': 8 * 1024**3, 'ram_available_bytes': 8 * 1024**3, 'ram_total_bytes': 16 * 1024**3, 'cpu_percent': 5},
                'models': [{'model': 'qwen3:8b', 'selected': True, 'loaded': False, 'disk_bytes': 5 * 1024**3,
                    'allocation_bytes': 0, 'gpu_bytes': 0, 'non_gpu_bytes': 0}], 'processes': [],
                'gpu': {'devices': [], 'note': 'Unavailable'}, 'storage': [], 'notes': []}
        if path.startswith('/system/ai/recommendations'):
            from frib_ds.ai_hardware import plan_models
            return plan_models({'architecture': 'AMD64', 'cpu': {'model': 'Test CPU', 'logical_cores': 8},
                'memory': {'total_gib': 16, 'available_gib': STATE.get('available_gib', 8)}, 'disk': {'free_gib': 100},
                'gpu': {'devices': [{'name': 'Test GPU', 'memory_gib': 4}]}}, [])
        if path == '/system/ai/setup':
            return STATE['info'].get('setup', {'status': 'idle'})
        if path.startswith('/system/ai/models'):
            return {'models': [{'id': 'qwen3:8b', 'size_bytes': 123}, {'id': 'another-model'}], 'download_available': True}
        return STATE['info']
    def post(path, payload):
        STATE['calls'].append((path, deepcopy(payload)))
        if path == '/system/ai/switch':
            STATE['info']['active'] = deepcopy(payload['selection'])
            STATE['info']['setup'] = {'status': 'completed', 'stage': 'completed', 'selection': deepcopy(payload['selection'])}
            return STATE['info']['setup']
        if path == '/system/ai/setup':
            STATE['info']['active']['model'] = 'qwen3:4b'
            STATE['info']['setup'] = {'status': 'completed', 'stage': 'completed', 'selection': {'model': 'qwen3:4b'}}
            return STATE['info']['setup']
        if path.endswith('/models'):
            return {'models': [{'id': 'qwen3:8b', 'size_bytes': 123}, {'id': 'another-model'}], 'download_available': True}
        if path.endswith('/test'):
            return {'passed': True, 'test_token': 'verified', 'chat': True, 'structured_json': True}
        if path.endswith('/apply'):
            STATE['info']['active'] = deepcopy(payload['selection'])
            STATE['info']['active_profile'] = payload['profile_name']
            STATE['info']['profiles'] = [{'name': payload['profile_name'], 'selection': deepcopy(payload['selection'])}]
            return {'applied': True, 'message': 'New model applied; document search unchanged.'}
        raise AssertionError(path)
    render_ai_settings(get, post, str)


@pytest.fixture
def ui(monkeypatch):
    from frib_ds.ai_settings import AISelection
    global STATE
    STATE = {'info': {'active': AISelection(provider='ollama', model='qwen3:8b', base_url='http://127.0.0.1:11434').model_dump(),
                      'profiles': [], 'active_profile': None, 'embeddings': {'model': 'all-MiniLM-L6-v2'},
                      'download_available': True, 'bundled_ollama_available': True}, 'calls': []}
    app = AppTest.from_string('from test_ai_settings_ui import run_ui; run_ui()', default_timeout=15).run()
    return app.segmented_control(key='ai_setup_view').set_value('Advanced').run()


def test_select_test_apply_and_display_saved_model(ui):
    assert not ui.exception
    assert ui.button(key='ai_apply_model').disabled
    ui.selectbox(key='ai_installed_model').select('another-model').run()
    ui.button(key='ai_test_model').click().run()
    assert not ui.exception
    assert not ui.button(key='ai_apply_model').disabled
    ui.button(key='ai_apply_model').click().run()
    assert not ui.exception
    assert STATE['info']['active']['model'] == 'another-model'
    assert any('another-model' in item.value for item in ui.success)
    assert STATE['info']['embeddings']['model'] == 'all-MiniLM-L6-v2'


def test_editing_a_tested_selection_disables_apply(ui):
    ui.button(key='ai_test_model').click().run()
    assert not ui.button(key='ai_apply_model').disabled
    ui.number_input(key='ai_temperature').set_value(0.5).run()
    assert ui.button(key='ai_apply_model').disabled


def test_provider_change_uses_its_server_and_stays_untested(ui):
    ui.selectbox(key='ai_provider').select('lmstudio').run()
    assert not ui.exception
    assert ui.text_input(key='ai_base_url').value == 'http://127.0.0.1:1234/v1'
    assert ui.button(key='ai_apply_model').disabled


def test_automatic_view_needs_no_model_name_address_or_code(ui):
    ui.segmented_control(key='ai_setup_view').set_value('Advanced').run()
    ui.segmented_control(key='ai_advanced_view').set_value('Hardware').run()
    assert not ui.exception
    assert not any(item.key in {'ai_base_url', 'ai_model', 'ai_profile_name'} for item in ui.text_input)
    assert not ui.button(key='ai_optimize').disabled
    ui.button(key='ai_optimize').click().run()
    assert not ui.exception
    setups = [payload for path, payload in STATE['calls'] if path == '/system/ai/setup']
    assert setups == [{'mode': 'balanced', 'auto_adjust': True}]
    assert STATE['info']['active']['model'] == 'qwen3:4b'


def test_model_picker_switches_arbitrary_installed_model_with_one_button(ui):
    ui.segmented_control(key='ai_setup_view').set_value('Choose a model').run()
    ui.selectbox(key='ai_picker_model').select('another-model').run()
    assert not ui.exception
    assert not ui.text_input
    ui.button(key='ai_picker_use').click().run()
    assert not ui.exception
    assert STATE['info']['active']['model'] == 'another-model'
    assert [path for path, _ in STATE['calls']] == ['/system/ai/switch']


def test_model_picker_downloads_another_family_without_typing_names(ui):
    ui.segmented_control(key='ai_setup_view').set_value('Choose a model').run()
    ui.selectbox(key='ai_picker_model').select('llama3.2:3b').run()
    assert not ui.exception
    assert not ui.button(key='ai_picker_use').disabled
    ui.button(key='ai_picker_use').click().run()
    assert not ui.exception
    assert ('/system/ai/setup', {'mode': 'balanced', 'model': 'llama3.2:3b', 'auto_adjust': False}) in STATE['calls']


def test_resources_view_labels_unloaded_models_and_does_not_change_settings(ui):
    ui.segmented_control(key='ai_setup_view').set_value('Advanced').run()
    ui.segmented_control(key='ai_advanced_view').set_value('Resources').run()
    assert not ui.exception
    assert ui.dataframe[0].value.iloc[0]['Status'] == 'Unloaded / idle'
    assert ui.dataframe[0].value.iloc[0]['Runtime allocation'] == '0.00 GiB'
    assert ui.dataframe[0].value.iloc[0]['On disk'] == '5.00 GiB'
    assert not STATE['calls']


def test_low_free_ram_does_not_block_replacing_a_loaded_model_with_an_installed_one(ui):
    STATE['available_gib'] = 1
    ui.segmented_control(key='ai_setup_view').set_value('Choose a model').run()
    ui.selectbox(key='ai_picker_model').select('another-model').run()
    assert not ui.button(key='ai_picker_use').disabled
    ui.selectbox(key='ai_picker_model').select('llama3.2:3b').run()
    assert ui.button(key='ai_picker_use').disabled
