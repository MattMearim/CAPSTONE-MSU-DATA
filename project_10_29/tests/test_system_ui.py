"""System inventory is read-only; upgrade choices queue explicit startup plans."""
from __future__ import annotations

import copy
from urllib.parse import urlsplit

import pytest
import requests

from test_dashboard_ui import Response, backend, open_page


def component(component_id, name, purpose, *, required=True, installed='2.0', status='ok', enabled=True, upgradeable=True):
    return {'id': component_id, 'name': name, 'purpose': purpose, 'category': 'required' if required else 'optional', 'required': required,
        'installed_version': installed, 'minimum_version': '1.0', 'status': status, 'upgradeable': upgradeable,
        'choices': [{'id': 'upgrade', 'label': 'Update at next startup', 'description': 'Resolve compatible project dependencies.', 'enabled': enabled, 'reason': None if enabled else 'Insufficient available memory.'}]}


@pytest.fixture
def system_backend(backend, monkeypatch):
    info = {'schema_version': '1.0', 'checked_at': '2026-10-12T12:00:00Z',
        'hardware': {'os': 'Windows', 'os_version': '11', 'architecture': 'AMD64', 'cpu': {'model': 'Test processor', 'logical_cores': 8},
            'memory': {'total_gib': 16.0, 'available_gib': 10.0, 'source': 'local'}, 'disk': {'free_gib': 100.0, 'total_gib': 500.0, 'path': 'C:'},
            'gpu': {'status': 'detected', 'devices': [{'name': 'Test graphics', 'memory_gib': 4.0}], 'note': 'Detected locally.'}},
        'recommendations': {'tier': 'standard', 'rationale': ['Core analysis is suitable.', 'Optional model sizing needs review.'], 'semantic_suitable': True, 'local_ai_suitable': False, 'warnings': []},
        'components': [component('python', 'Python', 'Runs this project.', status='tested_branch'), component('pip', 'pip', 'Installs project software.'),
            component('numpy', 'NumPy', 'Processes measured signal arrays.'), component('streamlit', 'Streamlit', 'Displays the dashboard.'),
            component('sentence-transformers', 'Semantic search', 'Optional document embeddings.', required=False, installed=None, status='not_installed'),
            component('ollama', 'Ollama', 'Optional local language model service.', required=False, installed=None, status='not_installed', enabled=False, upgradeable=False)],
        'upgrade': {'pending': None, 'last_result': None}, 'network_checked': False}
    state = {'info': info, 'reads': 0, 'posts': [], 'deletes': [], 'offline': False, 'latest_offline': False, 'plan_error': False}
    old_get, old_post, old_delete = requests.get, requests.post, requests.delete

    def get(url, **kwargs):
        if urlsplit(url).path == '/system/info':
            state['reads'] += 1
            if state['offline']:
                raise requests.ConnectionError('offline')
            return Response(state['info'])
        return old_get(url, **kwargs)

    def post(url, **kwargs):
        path = urlsplit(url).path
        if path.startswith('/system/'):
            state['posts'].append((path, copy.deepcopy(kwargs.get('json'))))
        if path == '/system/versions/check':
            if state['latest_offline']:
                raise requests.Timeout('network timeout')
            return Response({'checked_at': '2026-10-12T12:01:00Z', 'source': 'https://pypi.org', 'network_checked': True,
                'versions': [{'id': 'numpy', 'installed_version': '2.0', 'latest_version': '2.4', 'status': 'update_available', 'requires_python': '>=3.11', 'python_compatible': True, 'error': None}]})
        if path == '/system/upgrades/plan':
            if state['plan_error']:
                return Response({'detail': 'This update is not suitable for the current machine.'}, 400)
            plan = {**kwargs['json'], 'created_at': '2026-10-12T12:02:00Z'}
            state['info']['upgrade']['pending'] = plan
            return Response({'queued': True, 'plan': plan})
        return old_post(url, **kwargs)

    def delete(url, **kwargs):
        path = urlsplit(url).path
        if path == '/system/upgrades/plan':
            state['deletes'].append(path)
            state['info']['upgrade']['pending'] = None
            return Response({'cancelled': True, 'pending': None})
        return old_delete(url, **kwargs)

    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(requests, 'post', post)
    monkeypatch.setattr(requests, 'delete', delete)
    return state


def test_system_navigation_inventory_cards_and_cached_local_reads(system_backend):
    app = open_page('🖥️ System & upgrades')
    assert not app.exception
    assert 'System & upgrades' in app.radio(key='main_nav').options
    html = '\n'.join(item.value for item in app.markdown)
    assert 'Test processor' in html and '16.0 GiB RAM' in html and '100.0 GiB free' in html
    assert 'Processes measured signal arrays.' in html
    assert not app.dataframe
    assert system_backend['reads'] == 1
    assert not system_backend['posts']
    app.text_input(key='system_component_search').set_value('arrays').run()
    assert not app.exception
    assert system_backend['reads'] == 1
    assert len([item for item in app.selectbox if item.key.startswith('system_choice_')]) == 1
    assert app.selectbox(key='system_choice_numpy').value == 'keep'
    assert app.button(key='system_queue_selected').disabled
    assert any('Latest releases have not been checked' in item.value for item in app.caption)


def test_latest_check_is_explicit_and_never_queues_or_installs(system_backend):
    app = open_page('🖥️ System & upgrades')
    app.button(key='system_check_latest').click().run()
    assert not app.exception
    assert system_backend['posts'] == [('/system/versions/check', {})]
    assert any('Latest checked release: 2.4' in item.value for item in app.caption)
    assert system_backend['info']['upgrade']['pending'] is None
    assert system_backend['reads'] == 1
    system_backend['latest_offline'] = True
    app.button(key='system_check_latest').click().run()
    assert any('Latest versions could not be checked' in item.value for item in app.info)
    assert not app.exception


def test_selected_updates_persist_when_search_hides_cards_and_queue_exact_ids(system_backend):
    app = open_page('🖥️ System & upgrades')
    app.selectbox(key='system_choice_numpy').set_value('upgrade').run()
    app.text_input(key='system_component_search').set_value('dashboard').run()
    app.selectbox(key='system_choice_streamlit').set_value('upgrade').run()
    app.button(key='system_queue_selected').click().run()
    assert not app.exception
    path, payload = system_backend['posts'][-1]
    assert path == '/system/upgrades/plan'
    assert payload == {'mode': 'selected', 'components': ['numpy', 'streamlit'], 'upgrade_python': False, 'upgrade_pip': False, 'include_semantic': False}
    assert any('Update plan saved' in item.value for item in app.success)
    assert any('An update is queued' in item.value for item in app.info)
    assert app.button(key='system_queue_required').label == 'Replace plan with required updates'
    assert system_backend['info']['components'][2]['installed_version'] == '2.0'


def test_python_and_pip_are_explicit_flags_and_pending_plan_can_cancel(system_backend):
    app = open_page('🖥️ System & upgrades')
    app.selectbox(key='system_choice_python').set_value('upgrade').run()
    app.selectbox(key='system_choice_pip').set_value('upgrade').run()
    app.button(key='system_queue_selected').click().run()
    assert system_backend['posts'][-1][1] == {'mode': 'selected', 'components': [], 'upgrade_python': True, 'upgrade_pip': True, 'include_semantic': False}
    app.segmented_control(key='system_view').set_value('Startup plan').run()
    assert any('private Python runtime update' in item.value for item in app.caption)
    assert not any(item.key == 'system_choice_numpy' for item in app.selectbox)
    app.button(key='system_cancel').click().run()
    assert not app.exception
    assert system_backend['deletes'] == ['/system/upgrades/plan']
    assert system_backend['info']['upgrade']['pending'] is None
    assert any('Queued update cancelled' in item.value for item in app.success)


def test_required_bundle_and_optional_semantic_are_separate_plans(system_backend):
    app = open_page('🖥️ System & upgrades')
    app.button(key='system_queue_required').click().run()
    assert system_backend['posts'][-1][1] == {'mode': 'required', 'components': [], 'upgrade_python': False, 'upgrade_pip': False, 'include_semantic': False}
    app.segmented_control(key='system_view').set_value('Optional AI').run()
    assert not app.exception
    assert not app.button(key='system_queue_semantic').disabled
    app.button(key='system_queue_semantic').click().run()
    assert system_backend['posts'][-1][1] == {'mode': 'selected', 'components': [], 'upgrade_python': False, 'upgrade_pip': False, 'include_semantic': True}
    assert not any(path == '/system/versions/check' for path, _ in system_backend['posts'])
    assert any('does not download an AI model or install Ollama' in item.value for item in app.caption)


def test_unsuitable_optional_dependencies_and_disabled_package_choice_do_not_queue(system_backend):
    system_backend['info']['recommendations']['semantic_suitable'] = False
    system_backend['info']['components'][2]['choices'][0].update(enabled=False, reason='Not allowed for this runtime.')
    app = open_page('🖥️ System & upgrades')
    app.selectbox(key='system_choice_numpy').set_value('upgrade').run()
    assert app.button(key='system_queue_selected').disabled
    assert any('Not allowed for this runtime' in item.value for item in app.warning)
    app.segmented_control(key='system_view').set_value('Optional AI').run()
    assert app.button(key='system_queue_semantic').disabled
    assert not system_backend['posts']
    assert not app.exception


def test_backend_offline_is_friendly_and_retry_recovers(system_backend):
    system_backend['offline'] = True
    app = open_page('🖥️ System & upgrades')
    assert not app.exception
    assert app.button(key='system_check_latest').disabled
    assert any('System status is unavailable' in item.value for item in app.warning)
    assert any('Connect to inspect this computer' in item.value for item in app.markdown)
    system_backend['offline'] = False
    app.button(key='system_refresh').click().run()
    assert not app.exception
    assert not app.button(key='system_check_latest').disabled
    assert system_backend['reads'] == 2


def test_queue_failure_and_failed_previous_startup_remain_visible(system_backend):
    system_backend['info']['upgrade']['last_result'] = {'status': 'failed', 'error': 'Replacement validation failed; previous environment retained.'}
    system_backend['plan_error'] = True
    app = open_page('🖥️ System & upgrades')
    app.button(key='system_queue_required').click().run()
    assert not app.exception
    assert any('Could not update the startup plan' in item.value for item in app.error)
    assert system_backend['info']['upgrade']['pending'] is None
    app.segmented_control(key='system_view').set_value('Startup plan').run()
    assert any('previous environment retained' in item.value for item in app.warning)
    assert not app.get('dataframe')
    assert any(item.label == 'Download system report (JSON)' for item in app.get('download_button'))


def test_stale_inventory_disables_actions_until_refresh_succeeds(system_backend):
    app = open_page('🖥️ System & upgrades')
    app.selectbox(key='system_choice_numpy').set_value('upgrade').run()
    system_backend['offline'] = True
    app.button(key='system_refresh').click().run()
    assert app.button(key='system_queue_selected').disabled
    assert app.button(key='system_queue_required').disabled
    assert any('Showing the last successful inventory' in item.value for item in app.caption)
    app.segmented_control(key='system_view').set_value('Optional AI').run()
    assert app.button(key='system_queue_semantic').disabled
    system_backend['offline'] = False
    app.button(key='system_refresh').click().run()
    assert not app.button(key='system_queue_semantic').disabled
    assert not system_backend['posts']
    assert not app.exception


def test_healthy_runtime_and_local_source_are_not_attention_issues(system_backend):
    system_backend['info']['components'].append(component('frib-decision-support', 'FRIB source', 'Reviewed local application.', status='local_source', upgradeable=False))
    app = open_page('🖥️ System & upgrades')
    app.selectbox(key='system_component_filter').set_value('Needs attention').run()
    assert any('No matching software' in item.value for item in app.markdown)
    html = '\n'.join(item.value for item in app.markdown)
    assert 'Core analysis is suitable. Optional model sizing needs review.' in html
    assert "['Core analysis" not in html
    assert not app.exception


def test_invalid_saved_plan_is_visible_and_can_be_cancelled(system_backend):
    system_backend['info']['upgrade']['pending_error'] = 'The saved plan includes an unsupported component.'
    app = open_page('🖥️ System & upgrades')
    assert any('saved update plan needs attention' in item.value for item in app.warning)
    app.segmented_control(key='system_view').set_value('Startup plan').run()
    assert any('The saved update plan cannot be used' in item.value for item in app.error)
    app.button(key='system_cancel').click().run()
    assert not any('The saved update plan cannot be used' in item.value for item in app.error)
    assert system_backend['deletes'] == ['/system/upgrades/plan']
    assert not app.exception


def test_current_system_manager_inventory_renders_without_adapters(system_backend, monkeypatch, tmp_path):
    from frib_ds import system_manager
    hardware = copy.deepcopy(system_backend['info']['hardware'])
    monkeypatch.setattr(system_manager, 'inspect_hardware', lambda *args: hardware)
    system_backend['info'] = system_manager.SystemManager(tmp_path).inventory()
    app = open_page('🖥️ System & upgrades')
    assert not app.exception
    app.text_input(key='system_component_search').set_value('python runtime').run()
    assert app.selectbox(key='system_choice_python').options[1].startswith('Queue private Python')
    assert app.selectbox(key='system_choice_python').value == 'keep'
    assert not app.dataframe
    assert not system_backend['posts']


def test_actual_interpreter_and_pointer_errors_are_visible(system_backend):
    executable = r'C:\FRIB\.frib\environments\ENV-example\Scripts\python.exe'
    system_backend['info']['runtime'] = {'executable': executable, 'python_version': '3.13.16',
        'active_environment': {'schema_version': '1.0', 'path': 'environments/ENV-example'}, 'active_pointer_error': 'The pointer schema is invalid.'}
    app = open_page('🖥️ System & upgrades')
    assert not app.exception
    assert any(item.value == executable for item in app.code)
    assert any('Python 3.13.16' in item.value for item in app.caption)
    assert any('Environment: environments/ENV-example' in item.value for item in app.caption)
    assert any('environment pointer needs attention' in item.value for item in app.warning)
    assert not system_backend['posts']
