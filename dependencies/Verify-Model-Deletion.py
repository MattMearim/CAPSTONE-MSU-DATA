"""Verify model removal using a temporary alias; preserve existing model weights."""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import requests

session=requests.Session(); session.trust_env=False
base='http://127.0.0.1:8000'
engine='http://127.0.0.1:11434'
server={'provider':'ollama','base_url':engine}

def call(method,path,**kwargs):
    result=session.request(method,base+path,timeout=60,**kwargs)
    result.raise_for_status()
    return result.json()

before=call('GET','/system/ai/library',params=server)
original={item['id'] for item in before['models']}
main=call('GET','/system/ai')['active']
quality=call('GET','/system/ai/quality-agent')['settings']
source=quality['selection']['model']
alias='frib-delete-check:'+uuid.uuid4().hex[:12]
copied=session.post(engine+'/api/copy',json={'source':source,'destination':alias},timeout=30)
copied.raise_for_status()
try:
    preview=call('POST','/system/ai/library/delete-preview',json={**server,'model':alias})
    deleted=call('POST','/system/ai/library/delete',json={**server,'model':alias,'confirmation_token':preview['confirmation_token']})
    remaining={item['id'] for item in call('GET','/system/ai/library',params=server)['models']}
    assert alias not in remaining and original==remaining
    protected=[]
    for model in {main['model'],source}:
        result=session.post(base+'/system/ai/library/delete-preview',json={**server,'model':model},timeout=30)
        assert result.status_code==400,result.text
        protected.append(model)
    assert call('GET','/system/ai')['active']==main
    assert call('GET','/system/ai/quality-agent')['settings']==quality
    receipt={'verified_at':datetime.now(timezone.utc).isoformat(),'temporary_alias':alias,'deleted':True,
             'existing_models_preserved':sorted(remaining),'protected_models_rejected':protected,
             'main_and_quality_settings_preserved':True}
    output=Path(__file__).resolve().parent/'logs/model-deletion-validation.json'
    output.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,indent=2))
finally:
    # Cleanup is restricted to the exact unique alias created by this script.
    session.delete(engine+'/api/delete',json={'model':alias},timeout=30)
