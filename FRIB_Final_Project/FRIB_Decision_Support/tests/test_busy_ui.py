"""Run-state and offline animation regressions without contacting an AI service."""
from contextlib import contextmanager
import hashlib
import json
import queue
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from frib_ds.dashboard import busy_ui


class Slot:
    def __init__(self, ui):
        self.ui = ui

    @contextmanager
    def container(self, **kwargs):
        yield self

    def caption(self, value):
        self.ui.captions.append(value)

    def empty(self):
        self.ui.emptied += 1

    def progress(self, value, **kwargs):
        self.ui.progresses.append((value, kwargs.get("text", "")))
        return self


class FakeUI:
    def __init__(self):
        self.session_state = {}
        self.captions = []
        self.progresses = []
        self.emptied = 0

    @contextmanager
    def container(self, **kwargs):
        yield Slot(self)

    def empty(self):
        return Slot(self)

    def markdown(self, *args, **kwargs):
        pass

    def progress(self, value, **kwargs):
        return Slot(self).progress(value, **kwargs)


@pytest.fixture
def ui(monkeypatch):
    fake = FakeUI()
    states = []
    monkeypatch.setattr(busy_ui, "st", fake)
    monkeypatch.setattr(busy_ui, "render_run_animation", lambda state="running", label="Working": states.append((state, label)))
    return fake, states


def test_request_runs_once_off_ui_thread_and_returns_same_result(ui):
    fake, states = ui
    calls = []
    result = {"ready": True}
    original = threading.current_thread()
    def operation():
        calls.append(threading.current_thread())
        return result
    assert busy_ui.run_with_progress(operation, "Drafting", completed_label="Draft ready") is result
    assert len(calls) == 1 and calls[0] is not original
    assert states == [("running", "Drafting"), ("success", "Draft ready")]
    assert [p for p, _ in fake.progresses] == [1, 100]
    assert fake.progresses[0][1].startswith("1% estimated")
    assert any("does not report intermediate percentages" in c for c in fake.captions)
    assert fake.session_state[busy_ui.NOTICE_KEY]["label"] == "Draft ready"


def test_failure_preserves_exception_and_never_claims_success(ui):
    fake, states = ui
    fake.session_state[busy_ui.NOTICE_KEY] = {"label": "Old success"}
    failure = ValueError("Service rejected input")
    def operation():
        raise failure
    with pytest.raises(ValueError) as caught:
        busy_ui.run_with_progress(operation)
    assert caught.value is failure
    assert [state for state, _ in states] == ["running", "failed"]
    assert [value for value, _ in fake.progresses] == [1]
    assert busy_ui.NOTICE_KEY not in fake.session_state


def test_receipt_is_once_only_and_survives_immediate_rerun(ui):
    fake, states = ui
    busy_ui.run_with_progress(lambda: "ok", completed_label="Saved")
    states.clear()
    busy_ui.render_run_receipt()
    assert states == [("success", "Saved")]
    assert busy_ui.NOTICE_KEY not in fake.session_state
    busy_ui.render_run_receipt()
    assert states == [("success", "Saved")]


def test_no_receipt_renders_nothing(ui):
    _, states = ui
    busy_ui.render_run_receipt()
    assert states == []


def test_waiting_estimate_increases_monotonically_but_cannot_finish():
    values = [busy_ui.estimated_progress(seconds)
              for seconds in (-10, 0, .25, 1, 5, 15, 30, 60, 120, 300, 3600, float('inf'))]
    assert values == sorted(values)
    assert values[0] == 1
    assert values[-1] == 95
    assert all(1 <= value <= 95 for value in values)
    assert len(set(values)) >= 6


def test_running_bar_updates_in_place_before_worker_returns(ui, monkeypatch):
    fake, states = ui
    result = queue.Queue(maxsize=1)
    release = threading.Event()
    clock = [100.0]
    polls = [0]

    class PendingResult:
        def put(self, value):
            result.put(value)

        def get(self, timeout):
            assert timeout == busy_ui.UPDATE_INTERVAL_SECONDS
            if polls[0] < 3:
                polls[0] += 1
                clock[0] += 30
                raise queue.Empty
            release.set()
            return result.get(timeout=1)

    monkeypatch.setattr(busy_ui, 'queue', SimpleNamespace(Queue=lambda **_: PendingResult(), Empty=queue.Empty))
    monkeypatch.setattr(busy_ui.time, 'monotonic', lambda: clock[0])

    def operation():
        assert release.wait(timeout=1)
        return 'draft ready'

    assert busy_ui.run_with_progress(operation, 'Drafting', retain_receipt=False) == 'draft ready'
    percentages = [value for value, _ in fake.progresses]
    assert percentages == [1, 60, 82, 90, 100]
    assert all('estimated' in text for _, text in fake.progresses[:-1])
    assert any('90s elapsed' in text for text in fake.captions)
    # Only the bar and caption update during waiting; the looping iframe is
    # created once and is replaced only after the operation actually succeeds.
    assert states == [('running', 'Drafting'), ('success', 'Finished')]
    assert busy_ui.NOTICE_KEY not in fake.session_state


def test_inline_completion_can_disable_next_page_receipt(ui):
    fake, states = ui
    busy_ui.run_with_progress(lambda: 'draft ready', completed_label='Draft ready', retain_receipt=False)
    assert states[-1] == ('success', 'Draft ready')
    assert fake.progresses[-1] == (100, '100% · Draft ready')
    assert busy_ui.NOTICE_KEY not in fake.session_state


@pytest.mark.parametrize("state", ["running", "success", "failed"])
def test_animation_is_self_contained_and_escapes_task_label(state):
    document = busy_ui.animation_document(state, '<img src=x onerror="bad()">')
    assert '<img src=x' not in document
    assert '&lt;img' in document
    assert '<script src=' not in document and '<link ' not in document
    assert 'animationData:' in document
    assert 'role="status"' in document
    assert 'prefers-reduced-motion: reduce' in document
    assert 'animation.playSegments([0,26],true)' in document
    assert 'animation.playSegments([26,65],true)' in document
    assert "animation.goToAndStop(64,true)" in document
    assert 'animation.loop=false' in document
    assert "if(state==='failed')" in document


def test_unrecognized_state_rejected():
    with pytest.raises(ValueError):
        busy_ui.animation_document("cancelled")


def test_supplied_animation_retained_as_curated_shape_data():
    data = json.loads((busy_ui.ASSETS / 'cred_success.json').read_text())
    assert (data['fr'], data['ip'], data['op']) == (30, 0, 65)
    assert (data['w'], data['h']) == (600, 600)
    assert all(not asset.get('p') and not asset.get('u') for asset in data.get('assets', []))
    assert {layer['nm'] for layer in data['layers']} >= {'Tick completed', '1', '2', '3', '4'}
    assert 'MIT' in (busy_ui.ASSETS / 'LOTTIE_LICENSE.md').read_text()
    assert '5.13.0' in (busy_ui.ASSETS / 'VENDOR.md').read_text()


def test_bulk_percent_uses_report_counts_not_elapsed_time():
    source = (Path(busy_ui.__file__).with_name('bulk_ui.py')).read_text()
    assert 'processed / total * 100' in source
    assert 'sent / total * 100' in source
    assert 'Percentage counts files processed' in source
    assert 'status == "completed" and not counts.get("failed")' in source


def test_app_motion_preference_is_forwarded(monkeypatch):
    fake = FakeUI()
    fake.session_state['interface_motion'] = False
    documents = []
    monkeypatch.setattr(busy_ui, 'st', fake)
    monkeypatch.setattr(busy_ui.components, 'html', lambda html, **kw: documents.append(html))
    busy_ui.render_run_animation()
    assert 'const forceReduced=true' in documents[0]
    assert 'if(forceReduced||reduced.matches)' in documents[0]


def test_streamlit_supports_two_sequential_requests_and_failure():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from frib_ds.dashboard.busy_ui import run_with_progress, render_run_receipt
assert run_with_progress(lambda: 7, completed_label='First ready') == 7
assert run_with_progress(lambda: 9, completed_label='Second ready') == 9
try:
    run_with_progress(lambda: (_ for _ in ()).throw(ValueError('Rejected')))
except ValueError:
    st.info('Expected rejection')
render_run_receipt()
st.success('Operations verified')
''').run(timeout=15)
    assert not app.exception
    assert app.success[0].value == 'Operations verified'
    assert busy_ui.NOTICE_KEY not in app.session_state


@pytest.mark.parametrize('status,failed,expected', [
    ('running', 0, 'running'), ('completed', 0, 'success'),
    ('completed', 1, None), ('failed', 1, 'failed'), ('cancelled', 0, None),
])
def test_bulk_completion_animation_matches_real_job_outcome(monkeypatch, status, failed, expected):
    from streamlit.testing.v1 import AppTest
    from frib_ds.dashboard import bulk_ui
    states = []
    monkeypatch.setattr(bulk_ui, 'render_run_animation', lambda state, label: states.append(state))
    data = {'job_id': 'BULK-' + 'a' * 32, 'status': status, 'processed_files': 2,
            'total_files': 4, 'counts': {'failed': failed, 'imported': 2, 'skipped': 0}, 'files': []}
    source = '''
import streamlit as st
from frib_ds.dashboard.bulk_ui import _render_progress
report = DATA
st.session_state['bulk_report'] = report
_render_progress(report['job_id'], lambda _: report, lambda *_: None, str, lambda _: None)
'''.replace('DATA', repr(data))
    app = AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert states == ([expected] if expected else [])
    progress = app.get('progress')[0].proto
    assert progress.value == 50
    assert progress.text.startswith('50% · ')
