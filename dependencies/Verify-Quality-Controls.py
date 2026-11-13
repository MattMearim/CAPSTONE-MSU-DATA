"""Record live on/off checks after using the dashboard's quality-agent toggle."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import requests

phase=sys.argv[1]
assert phase in {'off','off-restarted','on'}
root=Path(__file__).resolve().parent/'logs'
session=requests.Session(); session.trust_env=False
def call(method,path,**kwargs):
    result=session.request(method,'http://127.0.0.1:8000'+path,timeout=300,**kwargs)
    result.raise_for_status(); return result.json()

baseline=json.loads((root/'quality-agent-real-validation.json').read_text(encoding='utf-8'))
health=call('GET','/health')
settings=call('GET','/system/ai/quality-agent')['settings']
assert settings['enabled']==(phase=='on')
assert settings['selection']['model']==baseline['quality_model']
main=call('GET','/system/ai')['active']
assert main['model']==baseline['main_model']
report=call('GET','/events/AI-QUALITY-DEMO/quality-agent')['report']
assert report and report['findings']
if phase!='on':
    assert call('POST','/events/AI-QUALITY-DEMO/quality-agent',json={})=={'status':'disabled'}
    assert call('GET','/events/AI-QUALITY-DEMO/quality-agent')['report']['run_id']==report['run_id']
    if phase=='off-restarted':
        previous=json.loads((root/'quality-controls-off.json').read_text())
        assert previous['instance_id']!=health['instance_id']
        # Real main-model inference remains available with the quality role off.
        probe=call('POST','/system/ai/test',json=main)
        assert probe['passed'] and probe['chat'] and probe['structured_json']
original=session.get('http://127.0.0.1:8000/events/AI-QUALITY-DEMO/download?format=json',timeout=15)
original.raise_for_status()
assert hashlib.sha256(original.content).hexdigest()==baseline['original_sha256']
dashboard=session.get('http://127.0.0.1:8501/_stcore/health',timeout=15)
assert dashboard.text.strip()=='ok'
receipt={'verified_at':datetime.now(timezone.utc).isoformat(),'phase':phase,'instance_id':health['instance_id'],
         'quality_enabled':settings['enabled'],'quality_model':settings['selection']['model'],
         'main_model':main['model'],'existing_findings_preserved':True,'original_bytes_preserved':True,
         'dashboard_healthy':True,'new_reviews_blocked':phase!='on',
         'real_main_model_probe_passed':True if phase=='off-restarted' else None}
(root/('quality-controls-'+phase+'.json')).write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps(receipt,indent=2),flush=True)
