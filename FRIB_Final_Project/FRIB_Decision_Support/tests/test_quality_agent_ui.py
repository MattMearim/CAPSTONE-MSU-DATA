from copy import deepcopy
import pytest
from streamlit.testing.v1 import AppTest
from test_quality_agent import finding

STATE={}

def run_ui():
    from frib_ds.dashboard.quality_agent_ui import render_agent_panel
    def post(path,payload):
        STATE['calls'].append((path,deepcopy(payload)))
        if path.endswith('/review'):
            STATE['state']['report']['findings'][0]['review']=payload
        elif path.endswith('/repair'):
            STATE['state']['report']['findings'][0]['repair_event_id']='CORRECTED-COPY'
            return {'event_id':'CORRECTED-COPY'}
        return {}
    render_agent_panel({'event_id':'DEMO'},STATE['state'],post,str,'demo',lambda _:None)

@pytest.fixture
def ui():
    global STATE
    item={**finding().model_dump(),'finding_id':'F1','proposal_hash':'a'*64,
          'anchors':[{'index':32,'time_s':32.,'value':99.}]}
    report={'run_id':'R1','status':'partial','source_hash':'b'*64,'findings':[item],
            'summary':'Tentative issue','coverage':{'directly_inspected_samples':33,'total_samples':65,'total_channels':1,'summarized_channels':['sensor']}}
    STATE={'state':{'enabled':True,'latest':report,'report':report},'calls':[]}
    return AppTest.from_string('from test_quality_agent_ui import run_ui; run_ui()',default_timeout=15).run()

def test_repair_ui_requires_name_acceptance_and_explicit_authorization(ui):
    assert not ui.exception
    assert ui.button(key='demo_qa_accept_F1').disabled
    assert ui.button(key='demo_qa_repair_F1').disabled
    ui.text_input(key='demo_qa_reviewer').set_value('Reviewer').run()
    assert not ui.button(key='demo_qa_accept_F1').disabled
    ui.checkbox(key='demo_qa_authorize_F1').check().run()
    assert ui.button(key='demo_qa_repair_F1').disabled
    ui.button(key='demo_qa_accept_F1').click().run()
    assert not ui.button(key='demo_qa_repair_F1').disabled
    ui.button(key='demo_qa_repair_F1').click().run()
    assert not ui.exception
    assert STATE['calls'][-1]==('/quality-agent/runs/R1/findings/F1/repair',
                              {'reviewer':'Reviewer','confirmed':True,'proposal_hash':'a'*64})
    assert 'CORRECTED-COPY' in ui.success[-1].value

def test_paused_agent_keeps_report_visible_and_disables_new_review(ui):
    STATE['state']['enabled']=False
    ui.run()
    assert not ui.exception and ui.button(key='demo_qa_run').disabled
    assert ui.selectbox(key='demo_qa_finding_R1').value=='F1'
