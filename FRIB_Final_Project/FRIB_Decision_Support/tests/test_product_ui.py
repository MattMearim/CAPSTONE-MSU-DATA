"""Display changes preserve evidence actions and persist the telemetry preference."""
from streamlit.testing.v1 import AppTest
from frib_ds.dashboard.preferences import resource_visibility
from test_dashboard_ui import APP, backend, open_page


def monitor_frames(app):
    return [element for element in app.get('iframe') if '/system/ai/monitor' in element.proto.src]


def test_resource_switch_removes_monitor_and_survives_a_new_session(backend):
    app=open_page('🏠 Home')
    assert monitor_frames(app)
    app.toggle(key='show_live_resources').set_value(False).run()
    assert not app.exception and not monitor_frames(app)
    assert resource_visibility() is False
    fresh=AppTest.from_file(str(APP),default_timeout=20).run()
    assert not fresh.exception and not fresh.toggle(key='show_live_resources').value
    assert not monitor_frames(fresh)
    fresh.toggle(key='show_live_resources').set_value(True).run()
    assert monitor_frames(fresh)
    assert not backend['posts'] and not backend['deletes']


def test_explore_starts_with_chart_and_keeps_detail_controls_on_demand(backend):
    app=open_page('🔎 Investigate Event')
    assert not app.exception
    labels=[item.label for item in app.expander]
    assert 'How to read this chart' not in labels
    assert 'Original context, recorded states and notes' not in labels
    assert 'Data checks' in labels and 'Files & exports' in labels
    assert app.get('plotly_chart')
    app.toggle(key='view_investigate_RF-TEST_normalize').set_value(True).run()
    assert not app.exception and not backend['posts'] and not backend['deletes']
