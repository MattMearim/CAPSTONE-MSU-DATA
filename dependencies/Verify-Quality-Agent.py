"""Exercise the real agent on explicitly synthetic data, without approving repairs."""
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import time
import requests

root=Path(__file__).resolve().parent
session=requests.Session(); session.trust_env=False
base='http://127.0.0.1:8000'
event_id='AI-QUALITY-DEMO'

def call(method,path,**kwargs):
    response=session.request(method,base+path,timeout=60,**kwargs)
    response.raise_for_status()
    return response

main=call('GET','/system/ai').json()['active']
quality=call('GET','/system/ai/quality-agent').json()['settings']
assert quality['enabled'] and quality['selection']['model']!=main['model']
existing=session.get(base+'/events/'+event_id,timeout=10)
if existing.status_code==404:
    values=[round(1+.015*math.sin(index/8),6) for index in range(65)]
    values[32]=8.5
    event={'event_id':event_id,'domain':'generic','event_type':'synthetic_measurement',
           'metadata':{'dataset_name':'AI quality demo · synthetic sensor trace','is_synthetic':True},
           'signals':[{'name':'sensor_voltage','unit':'V','sample_rate_hz':1,
                       'timestamps_s':list(range(65)),'values':values}],
           'provenance':{'source':'synthetic quality-agent acceptance test','notes':'Fictional test data, not a facility measurement.'}}
    call('POST','/events',json=event)
else:
    existing.raise_for_status()
    assert existing.json()['provenance']['source']=='synthetic quality-agent acceptance test','Demo ID already belongs to another dataset.'
    call('POST','/events/'+event_id+'/quality-agent',json={})
original=call('GET','/events/'+event_id+'/download?format=json').content
deadline=time.monotonic()+900
previous=None
while time.monotonic()<deadline:
    state=call('GET','/events/'+event_id+'/quality-agent').json()
    latest=state.get('latest') or {}
    progress=(latest.get('status'),latest.get('message'))
    if progress!=previous:
        print(json.dumps({'status':progress[0],'message':progress[1]}),flush=True); previous=progress
    if latest.get('status') in {'completed','partial','failed','cancelled','stale'}:
        break
    time.sleep(2)
else: raise RuntimeError('The real quality-agent check did not finish before its deadline.')
assert latest['status'] in {'completed','partial'},latest.get('message')
after=call('GET','/events/'+event_id+'/download?format=json').content
assert after==original,'The agent must preserve original evidence bytes.'
assert call('GET','/system/ai').json()['active']==main,'Quality review must not replace the main AI.'
findings=latest.get('findings',[])
flagged=any(item.get('signal_name')=='sensor_voltage' and any(anchor['index']==32 for anchor in item.get('anchors',[])) for item in findings)
receipt={'verified_at':datetime.now(timezone.utc).isoformat(),'event_id':event_id,'synthetic_data_only':True,
         'main_model':main['model'],'quality_model':quality['selection']['model'],'original_sha256':hashlib.sha256(original).hexdigest(),
         'original_bytes_preserved':True,'main_model_preserved':True,'findings':len(findings),
         'synthetic_excursion_flagged':flagged,'repairs_applied':False,'rag_used':False,'report':latest}
(root/'logs/quality-agent-real-validation.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
print(json.dumps({key:value for key,value in receipt.items() if key!='report'},indent=2),flush=True)
assert flagged,'The real model did not flag the synthetic excursion; inspect its report before accepting this setup.'
