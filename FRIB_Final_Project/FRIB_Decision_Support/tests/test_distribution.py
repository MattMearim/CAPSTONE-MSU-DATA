"""Verify the source ZIP runs independently of the original checkout and data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


PROJECT = Path(__file__).resolve().parents[1]


def test_extracted_source_distribution_supports_complete_workflow(tmp_path):
    package = tmp_path / "project.zip"
    subprocess.run([sys.executable, str(PROJECT / "scripts/package_project.py"), str(package)], check=True, capture_output=True, text=True)
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        assert not any("/.venv/" in name or "/.frib/" in name or "/data/" in name or "/tmp/" in name for name in names)
        assert "FRIB_Decision_Support/docs/references/FRIB_Decision_Support_Architecture.pdf" in names
        assert "FRIB_Decision_Support/src/frib_ds/dashboard/reset_ui.py" in names
        assert "FRIB_Decision_Support/scripts/run_system_smoke.py" in names
        assert "FRIB_Decision_Support/scripts/bootstrap_windows.ps1" in names
        assert "FRIB_Decision_Support/src/frib_ds/dashboard/system_ui.py" in names
        archive.extractall(tmp_path / "extracted")
    extracted = tmp_path / "extracted/FRIB_Decision_Support"
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(extracted / "src"), FRIB_CONFIG_DIR=str(extracted / "config"),
                       FRIB_DATA_DIR=str(tmp_path / "smoke-data"), FRIB_LLM_PROVIDER="mock",
                       FRIB_EMBEDDING_PROVIDER="hash", FRIB_VECTOR_PROVIDER="sqlite")
    checked = subprocess.run([sys.executable, "-m", "frib_ds.launcher", "--check"], cwd=extracted, env=environment, capture_output=True, text=True)
    assert checked.returncode != 0, "A packaged application must reject mock/hash runtime settings"
    assert "test-only" in checked.stderr
    script = r'''
import json
from pathlib import Path
import frib_ds
from fastapi.testclient import TestClient
from frib_ds.api.main import app
from frib_ds.bootstrap import get_services
assert Path(frib_ds.__file__).resolve().is_relative_to(Path.cwd())
ids = []
with TestClient(app) as client:
    assert client.get('/health').json()['status'] == 'ok'
    for domain in ('rf', 'mechanical', 'plc'):
        event = json.loads(Path('sample_data', domain + '_demo.json').read_text(encoding='utf-8'))
        event_id = event['event_id']; ids.append(event_id)
        assert client.post('/events', json=event).status_code == 200
        analysis = client.post(f'/events/{event_id}/analyze')
        assert analysis.status_code == 200, analysis.text
        assert analysis.json()['features']
        result = client.post(f'/events/{event_id}/draft')
        assert result.status_code == 200, result.text
        draft = result.json()
        assert len(draft['hypotheses']) >= 2
        assert draft['status'] == 'draft'
        assert client.get(f'/events/{event_id}/download').json()['event_id'] == event_id
        reviewed = client.post(f"/drafts/{draft['draft_id']}/review", json={'decision':'approve','reviewer':'Distribution smoke test'})
        assert reviewed.status_code == 200 and reviewed.json()['knowledge']
    assert len(client.get('/knowledge').json()) == 3
    payload = b'FICTIONAL DEMO ONLY: RF cavity field tuner pressure trip evidence review.'
    result = client.post('/documents/index', files={'file':('reference.md', payload)}, data={'approved':'true','title':'RF demonstration reference','version':'DEMO'})
    assert result.status_code == 200, result.text
    document_id = result.json()['document_id']
    assert client.get(f'/documents/{document_id}/download').content == payload
    query = client.post('/rag/query', json={'question':'RF cavity field tuner pressure trip evidence review'})
    assert query.status_code == 200 and query.json()['sources']
    evidence = client.post(f'/events/{ids[0]}/files', files={'file':('example.log',b'DEMO evidence')})
    assert evidence.status_code == 200, evidence.text
    file_id = evidence.json()['file_id']
    assert client.get(f'/events/{ids[0]}/files/{file_id}/download').content == b'DEMO evidence'
    assert client.delete(f'/events/{ids[0]}/files/{file_id}').status_code == 200
    assert client.delete(f'/documents/{document_id}').status_code == 200
    for filename, domain in (('mixed_units_and_states.csv','plc'),('operator_shift.log','rf')):
        contents = Path('sample_data',filename).read_bytes()
        response = client.post('/ingestion/import',files={'file':(filename,contents)},data={'options':json.dumps({'domain':domain})})
        assert response.status_code == 200, response.text
        event = response.json()['event']; event_id = event['event_id']; ids.append(event_id)
        if filename.endswith('.csv'):
            by_name = {signal['name']:signal for signal in event['signals']}
            assert by_name['pressure']['unit'] == 'Pa'
            assert by_name['pressure']['values'] == [1000,1000,1050,1080,1020]
            assert by_name['temperature']['unit'] == 'K'
        assert event['logs'] and event['states']
        assert client.post(f'/events/{event_id}/analyze').status_code == 200
        assert client.post(f'/events/{event_id}/draft').status_code == 200
    contents = Path('sample_data/quality_review.csv').read_bytes()
    report = client.post('/ingestion/quality',files={'file':('quality.csv',contents)})
    assert report.status_code == 200 and report.json()['status'] == 'blocked', report.text
    settings = {'quality_expectations':{'expected_interval_s':1,'channels':{'pressure':{'expected_stable':True,'stability_tolerance':100}}},
        '_repairs':[{'operation':'drop_exact_duplicate_rows'}, {'operation':'mark_missing_tokens','columns':['pressure [kPa]']},
                    {'operation':'drop_invalid_numeric_cells','rows':[5],'columns':['pressure [kPa]']}]}
    reviewed = client.post('/ingestion/preview',files={'file':('quality.csv',contents)},data={'options':json.dumps(settings),'validate':'true'})
    assert reviewed.status_code == 200 and reviewed.json()['validation']['valid'], reviewed.text
    response = client.post('/ingestion/import',files={'file':('quality.csv',contents)},data={'options':json.dumps(settings)})
    assert response.status_code == 200, response.text
    event = response.json()['event']; event_id = event['event_id']; ids.append(event_id)
    assert {'RECORDING_GAP','STABILITY_EXCEEDED'} <= {issue['code'] for issue in event['metadata']['data_quality']['issues']}
    assert response.json()['derived_file'] and event['metadata']['repair_receipt']
    original = response.json()['original_file']
    assert client.get(f"/events/{event_id}/files/{original['file_id']}/download").content == contents
get_services.cache_clear()
with TestClient(app) as client:
    assert len(client.get('/events').json()) == len(ids)
    assert len(client.get('/knowledge').json()) == 3
    assert client.get('/documents').json() == []
    assert client.post('/rag/query', json={'question':'RF cavity field tuner pressure trip evidence review'}).json()['sources'] == []
    before = client.get('/system/data').json()['counts']
    assert before['events'] == len(ids) and before['knowledge'] == 3
    reset = client.post('/system/reset', json={'confirmation':'RESET'})
    assert reset.status_code == 200, reset.text
    assert reset.json()['reset'] is True and reset.json()['removed']['events'] == len(ids)
    assert all(value == 0 for key,value in reset.json()['remaining'].items() if key != 'audit_entries')
    assert reset.json()['remaining']['audit_entries'] == 1
    for event_id in ids:
        assert client.get(f'/events/{event_id}').status_code == 404
    assert client.get('/events').json() == [] and client.get('/knowledge').json() == []
    assert client.post('/rag/query', json={'question':'RF cavity field tuner pressure trip evidence review'}).json()['sources'] == []
    assert list(get_services().config.event_dir.iterdir()) == []
    assert list(get_services().config.document_dir.iterdir()) == []
print('Verified extracted-package workflows for RF, mechanical, PLC, documents, evidence, retrieval, review, restart and deletion/reset')
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=extracted, env=environment, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr + result.stdout
    assert "Verified extracted-package workflows" in result.stdout
