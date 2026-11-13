"""Large previews remain responsive without weakening full-file validation."""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from frib_ds.api.main import app
from frib_ds.bootstrap import get_services
from frib_ds.config import get_config


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv("FRIB_CONFIG_DIR",str(Path("config").resolve()))
    monkeypatch.setenv("FRIB_DATA_DIR",str(tmp_path/"data"))
    monkeypatch.setenv("FRIB_LLM_PROVIDER","mock")
    monkeypatch.setenv("FRIB_EMBEDDING_PROVIDER","hash")
    monkeypatch.setenv("FRIB_VECTOR_PROVIDER","sqlite")
    get_config.cache_clear(); get_services.cache_clear()
    with TestClient(app) as connected:
        yield connected
    get_services.cache_clear(); get_config.cache_clear()


def source(last_value="1500"):
    return ("time [ms],voltage [mV]\n" + "".join(f"{i},{i}\n" for i in range(1500)) + f"1500,{last_value}\n").encode()


def send(client,path,contents):
    return client.post(path,files={"file":("large.csv",contents)},data={"validate":"true","options":json.dumps({"event_id":"PREVIEW-LIMIT","domain":"other"})})


def test_sampling_preview_does_not_truncate_the_import(client):
    response=send(client,"/ingestion/preview",source())
    assert response.status_code==200,response.text
    preview=response.json()
    assert preview["validation"]["valid"]
    assert len(preview["event"]["signals"][0]["values"])<=1000
    assert preview["event"]["signals"][0]["metadata"]["preview_total_samples"]==1501
    assert preview["event"]["signals"][0]["values"][-1]==1.5
    assert "Every row was validated" in preview["preview_notice"]
    assert client.get("/events").json()==[]
    imported=send(client,"/ingestion/import",source())
    assert imported.status_code==200,imported.text
    assert len(imported.json()["event"]["signals"][0]["values"])==1501


def test_invalid_final_row_cannot_hide_outside_sampled_preview(client):
    preview=send(client,"/ingestion/preview",source("invalid"))
    assert preview.status_code==200,preview.text
    assert preview.json()["validation"]["valid"] is False
    assert "1502" in " ".join(preview.json()["validation"]["errors"])
    imported=send(client,"/ingestion/import",source("invalid"))
    assert imported.status_code==400
    assert client.get("/events").json()==[]
