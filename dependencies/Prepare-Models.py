"""Download the configured main model into the private model folder."""
import os
import time
import requests
from run_frib import environment,selected_ai,start_bundled_ollama

def prepare():
    os.environ.update(environment())
    selection=selected_ai()
    if selection.provider!='ollama' or selection.base_url!=os.environ['FRIB_BUNDLED_OLLAMA_URL']:
        print('The saved external model server is managed by its owner. Checking it during verification.',flush=True)
        return
    start_bundled_ollama()
    with requests.Session() as session:
        session.trust_env=False
        installed=session.get(selection.base_url+'/api/tags',timeout=15)
        installed.raise_for_status()
        canonical=lambda name:name if ':' in name.rsplit('/',1)[-1] else name+':latest'
        if any(canonical(item['name'])==canonical(selection.model) for item in installed.json().get('models',[])):
            print('Reusing installed '+selection.model,flush=True); return
        previous=None;last=time.monotonic()
        with session.post(selection.base_url+'/api/pull',json={'model':selection.model,'stream':True},stream=True,timeout=(5,300),allow_redirects=False) as response:
            response.raise_for_status()
            import json
            for line in response.iter_lines():
                if not line: continue
                progress=json.loads(line)
                if progress.get('error'): raise RuntimeError(progress['error'])
                status=progress.get('status','Preparing model')
                if status!=previous or time.monotonic()-last>10:
                    total=progress.get('total',0);done=progress.get('completed',0)
                    print(status+(f' · {done/1024**3:.2f}/{total/1024**3:.2f} GiB' if total else ''),flush=True)
                    previous=status;last=time.monotonic()
            if previous!='success': raise RuntimeError('The engine did not confirm a complete model download.')

if __name__=='__main__': prepare()
