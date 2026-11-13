"""Compact model-library and independent quality-role controls."""
import json
from urllib.parse import urlencode
import streamlit as st


def render_model_library(api_get,api_post,friendly_error):
    from frib_ds.dashboard.ai_ui import _automatic_progress
    try:
        info=api_get('/system/ai')
        server={'provider':'ollama','base_url':info.get('managed_ollama_url') or 'http://127.0.0.1:11434'}
        try: library=api_get('/system/ai/library?'+urlencode(server))
        except Exception:
            library={'models':[],'can_delete':False}
            st.info('Engine offline. Adding a model starts the local engine.')
        running=info.get('setup',{}).get('status')=='running'
        add,remove=st.columns(2)
        with add.popover('Add model',icon=':material/add:',width='stretch'):
            name=st.text_input('Model name or library link',key='library_new_name',placeholder='model:tag or https://ollama.com/library/…')
            roles={'chat':'Main AI','quality':'Quality agent','install_only':'Download only'}
            role=st.selectbox('Assign to',list(roles),format_func=roles.get,key='library_new_role')
            if st.button('Download & set up',key='library_install',type='primary',disabled=running or not name.strip() or not info.get('bundled_ollama_available'),width='stretch'):
                api_post('/system/ai/library/install',{'model':name.strip(),'role':role}); st.rerun()
        with remove.popover('Remove model',icon=':material/delete_outline:',width='stretch'):
            unused=[item for item in library['models'] if not item['roles']]
            st.caption('Assigned models are protected.')
            if not unused: st.info('No unused models.')
            else:
                chosen=st.selectbox('Unused model',[item['id'] for item in unused],key='library_delete_model')
                if st.button('Preview deletion',key='library_delete_preview',disabled=not library.get('can_delete') or running):
                    st.session_state['library_deletion']=api_post('/system/ai/library/delete-preview',{**server,'model':chosen})
                plan=st.session_state.get('library_deletion')
                if plan and plan['model']==chosen:
                    st.warning(plan['message'])
                    confirmed=st.checkbox('Delete '+chosen+' from local storage',key='library_delete_confirm_'+plan['confirmation_token'])
                    if st.button('Delete model',key='library_delete_execute',disabled=not confirmed or running,type='primary'):
                        result=api_post('/system/ai/library/delete',{**server,'model':chosen,'confirmation_token':plan['confirmation_token']})
                        st.session_state.pop('library_deletion',None)
                        st.session_state['library_notice']=result['message']; st.rerun()
        st.dataframe([{'Model':item['id'],'Role':', '.join(item['roles']) or 'Available',
                       'Size (GiB)':round(item.get('size_bytes',0)/1024**3,2) if item.get('size_bytes') is not None else None}
                      for item in library['models']],hide_index=True,width='stretch')
        if st.session_state.get('library_notice'): st.success(st.session_state.pop('library_notice'))
        _automatic_progress(api_get,api_post,friendly_error,info.get('setup',{'status':'idle'}))
    except Exception as exc: st.error('Model library: '+friendly_error(exc))


def render_quality_agent_settings(api_get,api_post,friendly_error):
    from frib_ds.dashboard.ai_ui import _automatic_progress,_model_card
    try:
        state=api_get('/system/ai/quality-agent'); info=api_get('/system/ai')
        settings=state['settings']; current=settings.get('selection')
        signature=json.dumps(settings,sort_keys=True)
        if st.session_state.get('qa_saved_settings_seen')!=signature:
            st.session_state['qa_saved_settings_seen']=signature
            st.session_state['qa_automatic']=settings.get('automatic',True)
            st.session_state['qa_depth']=settings.get('max_model_calls',4)
            st.session_state['qa_enabled_toggle']=settings['enabled']
            if current:
                st.session_state['qa_provider']=current['provider']; st.session_state['qa_model']=current['model']
        _model_card('DATA QUALITY',current['model'] if current else 'Choose a model',
                    ('On' if settings['enabled'] else 'Off')+' · Read-only data review')
        enabled=st.toggle('Enable quality agent',value=settings['enabled'],key='qa_enabled_toggle',disabled=current is None,
                          help='Off blocks new reviews and discards an active call’s result. Existing reports remain available.')
        if enabled!=settings['enabled']:
            api_post('/system/ai/quality-agent/configure',{'settings':{**settings,'enabled':enabled}}); st.rerun()
        if state.get('last_error'): st.warning(state['last_error'])
        jobs=state.get('jobs',{})
        if jobs.get('queued',0) or jobs.get('running',0):
            st.caption(f"{jobs.get('queued',0)} waiting · {jobs.get('running',0)} running")
        with st.popover('Review options',icon=':material/tune:'):
            provider=st.selectbox('Engine',['ollama','lmstudio'],index=0 if not current or current['provider']=='ollama' else 1,key='qa_provider')
            automatic=st.checkbox('Review new datasets automatically',value=settings.get('automatic',True),key='qa_automatic')
            calls=st.selectbox('Review depth',list(range(1,7)),index=settings.get('max_model_calls',4)-1,
                               format_func=lambda value:{1:'Quick · 1 pass',4:'Standard · 4 passes',6:'Thorough · 6 passes'}.get(value,f'{value} passes'),key='qa_depth')
            if current and st.button('Save options',key='qa_save_options'):
                api_post('/system/ai/quality-agent/configure',{'settings':{**settings,'automatic':automatic,'max_model_calls':calls}}); st.rerun()
        base=current['base_url'] if current and provider==current['provider'] else (info.get('managed_ollama_url') or 'http://127.0.0.1:11434') if provider=='ollama' else 'http://127.0.0.1:1234/v1'
        try: models=api_get('/system/ai/models?'+urlencode({'provider':provider,'base_url':base}))['models']
        except Exception:
            models=[]; st.info('No engine connection. Download a local model below or start LM Studio.')
        ids=[item['id'] for item in models]
        if ids:
            if st.session_state.get('qa_model') not in ids:
                st.session_state['qa_model']=current['model'] if current and current['model'] in ids else ('qwen3:1.7b' if 'qwen3:1.7b' in ids else ids[0])
            model=st.selectbox('Quality model',ids,key='qa_model')
            selection=current if current and current['provider']==provider and current['model']==model else {'provider':provider,'base_url':base,'model':model,'temperature':0.0,'context_length':8192,'max_output_tokens':2048,'timeout_seconds':300}
            if st.button('Test & apply model',key='qa_enable',type='primary',width='stretch',disabled=info.get('setup',{}).get('status')=='running'):
                tested=api_post('/system/ai/quality-agent/test',selection)
                api_post('/system/ai/quality-agent/configure',{'settings':{'enabled':True,'automatic':automatic,'selection':selection,'max_model_calls':calls},'test_token':tested['test_token']}); st.rerun()
        else: st.info('Install a model to configure this role.')
        if settings['enabled']:
            if st.button('Review existing datasets',key='qa_scan_existing',help='Queues up to 1,000 recent datasets.'):
                result=api_post('/system/ai/quality-agent/scan-existing',{}); st.success(f"{result['scheduled']} reviews queued.")
        elif current and st.button('Remove assignment',key='qa_clear'):
            api_post('/system/ai/quality-agent/configure',{'settings':{**settings,'enabled':False,'selection':None}}); st.rerun()
        with st.expander('Get a small model'):
            small=st.selectbox('Small model',['qwen3:1.7b','llama3.2:3b','phi4-mini:3.8b'],key='qa_small_download')
            if st.button('Download & enable',key='qa_install_small',disabled=info.get('setup',{}).get('status')=='running' or not info.get('bundled_ollama_available')):
                api_post('/system/ai/library/install',{'model':small,'role':'quality'}); st.rerun()
        st.caption('AI flags are suggestions. Repairs require your approval.')
        _automatic_progress(api_get,api_post,friendly_error,info.get('setup',{'status':'idle'}))
    except Exception as exc: st.error('Quality agent: '+friendly_error(exc))
