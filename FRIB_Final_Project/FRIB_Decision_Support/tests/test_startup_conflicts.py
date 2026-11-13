"""The newest normal launch coordinates shutdown before touching environments."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def startup():
    spec = importlib.util.spec_from_file_location('startup_conflict_checks', PROJECT / 'start.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_newest_launch_acquires_global_ownership_before_environment_work(startup, monkeypatch):
    events = []
    @contextmanager
    def owner(project):
        events.append(('handoff', project))
        try: yield
        finally: events.append(('release', project))
    class SupersededLaunch(RuntimeError): pass
    monkeypatch.setattr(startup, 'single_instance_tools', lambda p: SimpleNamespace(SingleInstance=owner, SupersededLaunch=SupersededLaunch))
    monkeypatch.setattr(startup, 'application_main', lambda args: events.append(('start', args)) or 0)
    arguments = ['--local-ai', '--no-browser']
    assert startup.main(arguments) == 0
    assert events == [('handoff', PROJECT), ('start', arguments), ('release', PROJECT)]


def test_requested_ports_are_preserved_in_the_single_running_instance(startup, monkeypatch):
    @contextmanager
    def owner(project): yield
    seen = []
    monkeypatch.setattr(startup, 'single_instance_tools', lambda p: SimpleNamespace(SingleInstance=owner, SupersededLaunch=RuntimeError))
    monkeypatch.setattr(startup, 'application_main', lambda args: seen.append(args) or 0)
    args = ['--api-port=9000', '--port', '9001']
    assert startup.main(args) == 0
    assert seen == [args]


def test_invalid_launch_never_stops_or_replaces_existing_app(startup, monkeypatch):
    monkeypatch.setattr(startup, 'single_instance_tools', lambda *a: pytest.fail('Do not acquire ownership for invalid arguments'))
    with pytest.raises(SystemExit): startup.main(['--port', '80'])
    with pytest.raises(SystemExit): startup.main(['--unexpected'])


def test_superseded_launch_does_not_continue_setup(startup, monkeypatch, capsys):
    class SupersededLaunch(RuntimeError): pass
    @contextmanager
    def owner(project):
        raise SupersededLaunch('A newer request arrived')
        yield
    monkeypatch.setattr(startup, 'single_instance_tools', lambda p: SimpleNamespace(SingleInstance=owner, SupersededLaunch=SupersededLaunch))
    monkeypatch.setattr(startup, 'application_main', lambda args: pytest.fail('Superseded startup must not continue'))
    assert startup.main([]) == 0
    assert 'newer FRIB launch has priority' in capsys.readouterr().out


def test_unverified_owner_failure_never_starts_parallel_services(startup, monkeypatch):
    class SupersededLaunch(RuntimeError): pass
    @contextmanager
    def owner(project):
        raise RuntimeError('Cannot verify the existing process')
        yield
    monkeypatch.setattr(startup, 'single_instance_tools', lambda p: SimpleNamespace(SingleInstance=owner, SupersededLaunch=SupersededLaunch))
    monkeypatch.setattr(startup, 'application_main', lambda args: pytest.fail('Cannot start while ownership is unresolved'))
    with pytest.raises(RuntimeError, match='Cannot verify'): startup.main([])


@pytest.mark.parametrize('flag', ['--check-packages', '--check', '--setup-local-ai', '--test-lab', '--help'])
def test_maintenance_does_not_take_over_a_running_workspace(startup, monkeypatch, flag):
    monkeypatch.setattr(startup, 'single_instance_tools', lambda *a: pytest.fail('Maintenance is not a new app launch'))
    seen = []
    monkeypatch.setattr(startup, 'application_main', lambda args: seen.append(args) or 0)
    assert startup.main([flag]) == 0
    assert seen == [[flag]]


def test_launcher_preflight_loads_without_application_packages(startup):
    module = startup.source_launcher(PROJECT)
    assert module.PROJECT == PROJECT.resolve()
    assert module.parse_launcher_args(['--local-ai']).api_port == 8000
