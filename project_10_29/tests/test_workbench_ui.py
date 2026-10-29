"""Workbench navigation and data states use fake API records only."""
from __future__ import annotations

import copy
from urllib.parse import urlsplit

import pytest
import requests

from test_dashboard_ui import APP,Response,backend
from streamlit.testing.v1 import AppTest


@pytest.fixture
def workbench_backend(backend,monkeypatch):
    first=copy.deepcopy(backend["event"])
    second=copy.deepcopy(first)
    second.update(event_id="MECH-SECOND",domain="mechanical",event_type="vibration_anomaly")
    second["metadata"]["dataset_name"]="Bearing survey"
    state={"events":[first,second],"failed":set(),"total":2,"offline":False}
    original_get=requests.get
    def get(url,**kwargs):
        path=urlsplit(url).path
        if path=="/health" and state["offline"]:
            raise requests.ConnectionError("Fake backend offline")
        if path in state["failed"]:
            return Response({"detail":"Storage temporarily unavailable"},503)
        if path=="/events":
            rows=[]
            for event in state["events"]:
                rows.append({**{key:event[key] for key in ("event_id","domain","event_type","timestamp")},
                    "dataset_name":event["metadata"].get("dataset_name"),"signal_count":len(event["signals"]),
                    "state_count":len(event["states"]),"log_count":len(event["logs"])})
            return Response(rows)
        if path=="/system/data":
            return Response({"counts":{"events":state["total"],"documents":len(backend["documents"]),"knowledge":0,
                "analyses":0,"drafts":0,"reviews":0,"document_chunks":0,"event_files":0,
                "stored_files":0,"retrieval_vectors":0,"audit_entries":0},"reset_pending":False})
        for event in state["events"]:
            if path==f"/events/{event['event_id']}": return Response(event)
            if event["event_id"]!="RF-TEST" and path==f"/events/{event['event_id']}/analysis":
                return Response({**backend["analysis"],"event_id":event["event_id"]})
            if event["event_id"]!="RF-TEST" and path==f"/events/{event['event_id']}/files": return Response([])
        return original_get(url,**kwargs)
    monkeypatch.setattr(requests,"get",get)
    return state


def overview():
    app=AppTest.from_file(str(APP),default_timeout=20).run()
    assert not app.exception
    assert app.radio(key="main_nav").value=="🏠 Home"
    return app


def assert_workspace_mode_rendered(app,expected):
    labels=["Import data","Text & PDF","Event JSON","Generate demo","Dataset library"]
    workspace=next(container for container in app.get("tab_container")
                   if [tab.label for tab in container.tabs]==labels)
    # Streamlit's browser receives this selection. A Python session key alone
    # can exist even when stateless tabs ignore it and render the first tab.
    rendered=workspace.proto.tab_container
    assert rendered.id,"Workspace tab selection must register as a stateful widget"
    assert rendered.default_tab_index==labels.index(expected)


@pytest.mark.parametrize("button,tab",[("overview_import","Import data"),("overview_generate","Generate demo")])
def test_empty_overview_actions_open_the_intended_workspace_mode(workbench_backend,backend,button,tab):
    workbench_backend["events"]=[]; workbench_backend["total"]=0; backend["documents"]=[]
    app=overview()
    assert not any(item.key=="overview_event" for item in app.selectbox)
    app.button(key=button).click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value=="🧪 Create Dataset"
    assert app.session_state["workspace_tabs"]==tab
    assert {item.label for item in app.tabs}=={"Import data","Text & PDF","Event JSON","Generate demo","Dataset library"}
    assert_workspace_mode_rendered(app,tab)
    app.run()
    assert not app.exception
    assert_workspace_mode_rendered(app,tab)
    assert backend["posts"]==[],"Choosing an entry route must not generate or import records"


def test_recent_dataset_selection_opens_the_correct_record(workbench_backend):
    app=overview()
    app.selectbox(key="overview_event").set_value("MECH-SECOND").run()
    app.button(key="overview_open").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value=="🔎 Investigate Event"
    assert app.selectbox(key="investigate_event").value=="MECH-SECOND"
    assert app.session_state["investigate_event"]=="MECH-SECOND"


@pytest.mark.parametrize("button,target",[
    ("overview_procedures","📁 Files & Documents"),
    ("overview_assistant","💬 Ask Assistant"),
    ("overview_review","✅ Review Results"),
    ("overview_knowledge","🧠 Engineering Wiki"),
])
def test_overview_context_actions_route_to_the_correct_stage(workbench_backend,button,target):
    app=overview()
    app.button(key=button).click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value==target


def test_overview_filters_match_names_domains_and_do_not_reopen_stale_records(workbench_backend):
    app=overview()
    app.text_input(key="overview_search").set_value("bearing").run()
    assert app.selectbox(key="overview_event").value=="MECH-SECOND"
    app.selectbox(key="overview_domain").set_value("rf").run()
    assert not app.exception
    assert not any(item.key=="overview_event" for item in app.selectbox)
    assert not any(item.key=="overview_open" for item in app.button)
    assert any("match" in item.value.lower() for item in [*app.info,*app.markdown])
    assert not any(item.key=="overview_generate" for item in app.button),"No matches must not masquerade as an empty project"
    app.button(key="overview_clear_filters").click().run()
    assert not app.exception
    assert app.text_input(key="overview_search").value==""
    assert app.selectbox(key="overview_domain").value=="all"
    assert len(app.selectbox(key="overview_event").options)==2
    assert app.selectbox(key="overview_event").value in {"RF-TEST","MECH-SECOND"}
    assert any(item.key=="overview_open" for item in app.button)


def test_overview_search_accepts_event_identifier(workbench_backend):
    app=overview()
    app.text_input(key="overview_search").set_value("MECH-SECOND").run()
    assert not app.exception
    assert app.selectbox(key="overview_event").value=="MECH-SECOND"


def test_home_uses_authoritative_dataset_total_instead_of_recent_list_length(workbench_backend):
    workbench_backend["total"]=23
    app=overview()
    dataset_metric=next(item for item in app.metric if "dataset" in item.label.lower())
    assert dataset_metric.value=="23"


@pytest.mark.parametrize("path",["/events","/documents","/knowledge"])
def test_home_list_failure_is_visible_and_does_not_claim_a_zero_count(workbench_backend,path):
    workbench_backend["failed"].add(path)
    app=overview()
    assert not app.exception
    assert any("unavailable" in item.value.lower() or "could not" in item.value.lower() for item in app.error)
    assert any(item.value=="—" for item in app.metric)
    if path=="/events":
        assert not any(item.key in {"overview_event","overview_open","overview_generate"} for item in [*app.selectbox,*app.button])


def test_home_count_endpoint_failure_preserves_recent_dataset_access(workbench_backend):
    workbench_backend["failed"].add("/system/data")
    app=overview()
    assert not app.exception
    assert app.selectbox(key="overview_event").value in {"RF-TEST","MECH-SECOND"}
    assert not app.button(key="overview_open").disabled


def test_failed_dataset_list_can_be_retried_without_losing_the_navigation(workbench_backend):
    workbench_backend["failed"].add("/events")
    app=overview()
    assert any("Datasets unavailable" in item.value for item in app.error)
    workbench_backend["failed"].remove("/events")
    app.button(key="overview_retry").click().run()
    assert not app.exception
    assert app.radio(key="main_nav").value=="🏠 Home"
    assert len(app.selectbox(key="overview_event").options)==2
    assert not any("Datasets unavailable" in item.value for item in app.error)


def test_offline_status_retains_a_retry_action(workbench_backend):
    workbench_backend["offline"]=True
    app=overview()
    assert not app.exception
    assert any("Backend is unavailable" in item.value for item in app.warning)
    assert app.button(key="global_retry")
    workbench_backend["offline"]=False
    app.button(key="global_retry").click().run()
    assert not app.exception
    assert not any("Backend is unavailable" in item.value for item in app.warning)


@pytest.mark.parametrize("page,path,empty_message",[
    ("✅ Review Results","/events","no datasets to review"),
    ("🧠 Engineering Wiki","/knowledge","no matching approved knowledge"),
])
def test_review_and_knowledge_list_failures_do_not_masquerade_as_empty_records(workbench_backend,page,path,empty_message):
    workbench_backend["failed"].add(path)
    app=overview()
    app.radio(key="main_nav").set_value(page).run()
    assert not app.exception
    assert any("Storage temporarily unavailable" in item.value for item in app.error)
    assert not any(empty_message in item.value.casefold() for item in app.info)
    workbench_backend["failed"].remove(path)
    app.run()
    assert not app.exception
    assert app.radio(key="main_nav").value==page
    assert not any("Storage temporarily unavailable" in item.value for item in app.error)
    if path=="/events":
        assert len(app.selectbox(key="review_event_select").options)==2
    else:
        assert any(empty_message in item.value.casefold() for item in app.info)
