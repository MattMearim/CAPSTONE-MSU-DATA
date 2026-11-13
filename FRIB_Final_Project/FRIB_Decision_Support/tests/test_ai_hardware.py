"""Capacity planning and one-click setup across current and upgraded machines."""
from copy import deepcopy
import time
import threading

import pytest

from frib_ds import ai_settings as ai
from frib_ds.ai_hardware import plan_models, hardware_signature, automatic_selection
from test_ai_settings import services, selection, local_model_server


def hardware(ram=16, gpu=4, disk=100, available=8):
    return {'architecture': 'AMD64', 'cpu': {'model': 'Test CPU', 'logical_cores': 12},
            'memory': {'total_gib': ram, 'available_gib': available}, 'disk': {'free_gib': disk},
            'gpu': {'devices': [{'name': 'Test GPU', 'memory_gib': gpu}] if gpu else []}}


@pytest.mark.parametrize('ram,gpu,expected', [(8, 0, 'qwen3:1.7b'), (16, 4, 'qwen3:4b'),
    (32, 8, 'qwen3:8b'), (32, 16, 'qwen3:14b'), (64, 24, 'qwen3:32b'), (64, 0, 'qwen3:8b')])
def test_recommendation_grows_with_hardware(ram, gpu, expected):
    plan = plan_models(hardware(ram, gpu))
    assert plan['recommended']['id'] == expected
    assert plan['recommended']['eligible'] and plan['blocked_reason'] is None


def test_preference_unknown_resources_and_storage_are_honoured():
    assert plan_models(hardware(), mode='speed')['recommended']['id'] == 'qwen3:1.7b'
    assert plan_models(hardware(), mode='capacity')['recommended']['id'] == 'qwen3:8b'
    assert plan_models(hardware(ram=None))['blocked_reason']
    assert plan_models(hardware(disk=0.1))['blocked_reason']
    assert plan_models(hardware(available=1))['blocked_reason']
    cached = plan_models(hardware(disk=0.1), ['qwen3:4b'])
    assert cached['recommended']['id'] == 'qwen3:4b'
    with pytest.raises(ValueError):
        automatic_selection(plan_models(hardware()), 'qwen3:32b')


def test_only_real_hardware_changes_trigger_new_signature():
    original = hardware()
    transient = hardware(disk=60, available=3)
    assert hardware_signature(original) == hardware_signature(transient)
    assert hardware_signature(original) != hardware_signature(hardware(ram=32, gpu=8))


def test_other_model_families_can_be_chosen_without_changing_automatic_policy():
    plan = plan_models(hardware())
    assert plan['recommended']['id'] == 'qwen3:4b'
    assert automatic_selection(plan, 'llama3.2:3b')['model'] == 'llama3.2:3b'
    assert automatic_selection(plan, 'phi4-mini:3.8b')['model'] == 'phi4-mini:3.8b'


def test_one_click_installed_switch_tests_and_persists_custom_family(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    monkeypatch.setattr(ai, 'list_models', lambda _: [{'id': 'custom-family:small'}])
    monkeypatch.setattr(ai, 'probe_model', lambda _: {'chat': True, 'structured_json': True})
    old_embedding = services.embedding
    manager.begin_switch(ai.InstalledModelSwitch(selection=selection(model='custom-family:small')), services)
    assert wait_setup(manager)['status'] == 'completed'
    assert services.llm.model == 'custom-family:small' and services.embedding is old_embedding
    saved = ai.read_profiles(services.config.config_dir)
    assert saved['automation']['enabled'] is False
    assert saved['active_profile'] == 'My selected AI'


def test_one_click_switch_rejects_uninstalled_and_preserves_model_on_probe_failure(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    old = services.llm
    monkeypatch.setattr(ai, 'list_models', lambda _: [])
    with pytest.raises(ValueError, match='not installed'):
        manager.begin_switch(ai.InstalledModelSwitch(selection=selection(model='new-model')), services)
    monkeypatch.setattr(ai, 'list_models', lambda _: [{'id': 'new-model'}])
    monkeypatch.setattr(ai, 'probe_model', lambda _: (_ for _ in ()).throw(ValueError('No JSON support')))
    manager.begin_switch(ai.InstalledModelSwitch(selection=selection(model='new-model')), services)
    assert wait_setup(manager)['status'] == 'failed'
    assert services.llm is old


def wait_setup(manager):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = manager.setup_status()
        if result['status'] != 'running':
            return result
        time.sleep(0.03)
    raise AssertionError('Automatic test setup did not finish')


def configure(manager, services, base, monkeypatch, installed=()):
    monkeypatch.setenv('FRIB_DEPENDENCIES_DIR', str(services.config.config_dir.parent / 'dependencies'))
    monkeypatch.setenv('FRIB_BUNDLED_OLLAMA_URL', base)
    monkeypatch.setenv('FRIB_MANAGED_OLLAMA_URL', base)
    monkeypatch.setattr(ai, 'start_bundled_server', lambda: {'base_url': base})
    monkeypatch.setattr(manager, 'recommendations', lambda mode='balanced', refresh=False: plan_models(hardware(), installed, mode))


def test_one_click_downloads_tests_applies_and_persists_automatic_choice(services, local_model_server, monkeypatch):
    base, captured = local_model_server
    manager = ai.AISettingsManager(services.config.config_dir)
    configure(manager, services, base, monkeypatch)
    old_embedding = services.embedding
    old_vector = services.vector
    manager.begin_setup(ai.AutomaticSetup(), services)
    result = wait_setup(manager)
    assert result['status'] == 'completed', result
    assert services.llm.model == 'qwen3:4b'
    assert services.embedding is old_embedding and services.vector is old_vector
    paths = [path for path, _ in captured]
    assert paths == ['/api/pull', '/api/chat', '/api/chat']
    profiles = ai.read_profiles(services.config.config_dir)
    assert profiles['automation']['enabled'] is True
    assert profiles['automation']['hardware_signature'] == hardware_signature(hardware())
    assert profiles['active_profile'] == 'Automatic AI'
    assert any(item['name'] == 'Previous model' for item in profiles['profiles'])
    assert ai.AISettingsManager(services.config.config_dir).setup_status()['status'] == 'completed'


def test_failed_automatic_probe_keeps_model_and_index(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    configure(manager, services, 'http://127.0.0.1:11434', monkeypatch, ['qwen3:4b'])
    monkeypatch.setattr(ai, 'list_models', lambda server: [{'id': 'qwen3:4b'}])
    monkeypatch.setattr(ai, 'probe_model', lambda chosen: (_ for _ in ()).throw(ValueError('Incompatible structured output')))
    old = services.llm
    manager.begin_setup(ai.AutomaticSetup(), services)
    result = wait_setup(manager)
    assert result['status'] == 'failed' and result['previous_model_preserved']
    assert services.llm is old
    assert ai.read_profiles(services.config.config_dir)['active_profile'] is None


def test_another_family_downloads_tests_and_saves_explicit_choice(services, local_model_server, monkeypatch):
    base, captured = local_model_server
    manager = ai.AISettingsManager(services.config.config_dir)
    configure(manager, services, base, monkeypatch)
    manager.begin_setup(ai.AutomaticSetup(model='llama3.2:3b', auto_adjust=False), services)
    result = wait_setup(manager)
    assert result['status'] == 'completed', result
    assert services.llm.model == 'llama3.2:3b'
    assert captured[0][1]['model'] == 'llama3.2:3b'
    profiles = ai.read_profiles(services.config.config_dir)
    assert profiles['active_profile'] == 'My selected AI' and not profiles['automation']['enabled']


def test_cancel_during_test_does_not_apply_the_candidate(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    configure(manager, services, 'http://127.0.0.1:11434', monkeypatch, ['qwen3:4b'])
    monkeypatch.setattr(ai, 'list_models', lambda server: [{'id': 'qwen3:4b'}])
    started, release = threading.Event(), threading.Event()
    def probe(chosen):
        started.set()
        assert release.wait(5)
        return {'chat': True, 'structured_json': True}
    monkeypatch.setattr(ai, 'probe_model', probe)
    old = services.llm
    manager.begin_setup(ai.AutomaticSetup(), services)
    assert started.wait(5)
    manager.cancel_setup()
    release.set()
    assert wait_setup(manager)['status'] == 'cancelled'
    assert services.llm is old


def test_changed_hardware_schedules_an_upgrade_without_coding(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    ai._write_profiles(services.config.config_dir, {'schema_version': '1.0', 'active_profile': None, 'profiles': [],
        'automation': {'enabled': True, 'mode': 'balanced', 'hardware_signature': hardware_signature(hardware())}})
    monkeypatch.setattr(manager, 'recommendations', lambda *args, **kwargs: plan_models(hardware(32, 16)))
    calls = []
    monkeypatch.setattr(manager, 'begin_setup', lambda request, service, **kwargs: calls.append((request, kwargs)))
    manager.check_automatic_hardware(services)
    assert len(calls) == 1 and calls[0][0].auto_adjust
    assert calls[0][1]['reason'] == 'Hardware change detected'
    policy = ai.read_profiles(services.config.config_dir)
    policy['automation']['enabled'] = False
    ai._write_profiles(services.config.config_dir, policy)
    manager.check_automatic_hardware(services)
    assert len(calls) == 1


def test_pausing_does_not_change_the_active_model(services):
    manager = ai.AISettingsManager(services.config.config_dir)
    ai._write_profiles(services.config.config_dir, {'schema_version': '1.0', 'active_profile': None, 'profiles': [],
        'automation': {'enabled': True, 'mode': 'balanced', 'hardware_signature': hardware_signature(hardware())}})
    old = services.llm
    assert manager.pause_automation()['paused']
    assert services.llm is old
    assert ai.read_profiles(services.config.config_dir)['automation']['enabled'] is False


def test_interrupted_one_time_setup_resumes_even_without_future_auto_adjust(services, monkeypatch):
    manager = ai.AISettingsManager(services.config.config_dir)
    manager._setup = {'status': 'interrupted', 'request': {'mode': 'balanced', 'auto_adjust': False}}
    calls = []
    monkeypatch.setattr(manager, 'begin_setup', lambda request, service, **kwargs: calls.append(request))
    manager.check_automatic_hardware(services)
    assert len(calls) == 1 and calls[0].auto_adjust is False
