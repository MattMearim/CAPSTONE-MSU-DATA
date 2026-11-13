"""Select and test local chat models without altering document embeddings."""
from __future__ import annotations

import json
import time
from html import escape
from urllib.parse import urlencode
import streamlit as st
from frib_ds.dashboard.design import page_header

LABELS = {'ollama': 'Ollama', 'lmstudio': 'LM Studio'}
URLS = {'ollama': 'http://127.0.0.1:11434', 'lmstudio': 'http://127.0.0.1:1234/v1'}
CUSTOM = 'Enter another model name…'


def _model_card(label,model,detail):
    st.markdown(f'<div class="ai-model-card"><div class="ai-model-label">{escape(label)}</div>'
                f'<div class="ai-model-name">{escape(model)}</div><div class="ai-model-detail">{escape(detail)}</div></div>',unsafe_allow_html=True)


def _open_hardware():
    st.session_state['ai_setup_view']='Advanced'
    st.session_state['ai_advanced_view']='Hardware'


def _load_profile():
    name = st.session_state.get('ai_saved_profile')
    profile = st.session_state.get('ai_profile_choices', {}).get(name)
    if profile:
        for key, value in profile.items():
            st.session_state['ai_' + key] = value
        st.session_state['ai_profile_name'] = name
        st.session_state.pop('ai_catalog', None)
        st.session_state.pop('ai_installed_model', None)
        st.session_state.pop('ai_test_result', None)


def _provider_changed():
    provider = st.session_state['ai_provider']
    st.session_state['ai_base_url'] = URLS[provider]
    st.session_state['ai_model'] = ''
    st.session_state.pop('ai_installed_model', None)
    st.session_state.pop('ai_catalog', None)
    st.session_state.pop('ai_test_result', None)


def _fingerprint(selection):
    return json.dumps(selection, sort_keys=True)


def _download_progress(api_get, friendly_error):
    job_id = st.session_state.get('ai_download_job')
    if not job_id:
        return

    @st.fragment(run_every='2s' if st.session_state.get('ai_download_running', True) else None)
    def progress():
        try:
            job = api_get('/system/ai/downloads/' + job_id)
            st.write(f"**{job['model']}** · {job['message']}")
            if job.get('total'):
                st.progress(min(1.0, job.get('completed', 0) / job['total']))
                st.caption(f"{job.get('completed', 0) / 1024**3:.2f} / {job['total'] / 1024**3:.2f} GiB for the current model layer")
            if job['status'] != 'downloading' and st.session_state.get('ai_download_running', True):
                st.session_state['ai_download_running'] = False
                st.session_state.pop('ai_catalog', None)
                st.rerun()
            if job['status'] == 'failed':
                st.error(job['message'])
            elif job['status'] == 'completed':
                st.success('Model downloaded. Select it above and test it before applying.')
        except Exception as exc:
            st.error(friendly_error(exc))
    progress()


def _render_advanced_settings(api_get, api_post, friendly_error):
    st.subheader('Connection')
    try:
        info = api_get('/system/ai')
    except Exception as exc:
        st.error('AI settings could not be loaded: ' + friendly_error(exc))
        return
    active = info['active']
    if 'ai_pending_url' in st.session_state:
        st.session_state['ai_base_url'] = st.session_state.pop('ai_pending_url')
    st.success(f"Active: {LABELS[active['provider']]} · {active['model']}")
    if st.session_state.get('ai_notice'):
        st.info(st.session_state['ai_notice'])
    embeddings = info.get('embeddings', {})
    st.caption(f"Search embeddings · {embeddings.get('model', 'unchanged')}")
    st.session_state['ai_profile_choices'] = {entry['name']: entry['selection'] for entry in info.get('profiles', [])}
    if info.get('profiles'):
        st.selectbox('Saved AI profile', ['Choose a profile…', *st.session_state['ai_profile_choices']], key='ai_saved_profile', on_change=_load_profile)
    for key, value in active.items():
        st.session_state.setdefault('ai_' + key, value)
    st.session_state.setdefault('ai_profile_name', info.get('active_profile') or 'My local AI')
    provider = st.selectbox('AI provider', list(LABELS), format_func=LABELS.get, key='ai_provider', on_change=_provider_changed)
    url = st.text_input('Model server address', key='ai_base_url', help='Ollama usually uses port 11434. In LM Studio, enable its local server; its address usually ends in :1234/v1.')
    if provider == 'lmstudio':
        st.info('Enable the LM Studio local server, then refresh models.')
    server = {'provider': provider, 'base_url': url}
    catalog_key = _fingerprint(server)
    refresh = st.button('Refresh models', key='ai_refresh_models')
    cached = st.session_state.get('ai_catalog')
    if refresh or not cached or cached.get('key') != catalog_key:
        try:
            with st.spinner('Reading models from the selected local server…'):
                catalog = api_get('/system/ai/models?' + urlencode(server))
            cached = {'key': catalog_key, **catalog}
        except Exception as exc:
            cached = {'key': catalog_key, 'models': [], 'download_available': False, 'error': friendly_error(exc)}
        st.session_state['ai_catalog'] = cached
    if cached.get('error'):
        st.warning(cached['error'])
        if provider == 'ollama' and info.get('bundled_ollama_available') and st.button('Start bundled Ollama', key='ai_start_ollama'):
            try:
                with st.spinner('Starting the bundled local model server…'):
                    started = api_post('/system/ai/start-ollama', {})
                st.session_state['ai_pending_url'] = started['base_url']
                st.session_state.pop('ai_catalog', None)
                st.rerun()
            except Exception as exc:
                st.error(friendly_error(exc))
    ids = [entry['id'] for entry in cached.get('models', [])]
    options = [*ids, CUSTOM]
    selected = st.session_state.get('ai_installed_model')
    if selected not in options:
        st.session_state['ai_installed_model'] = st.session_state.get('ai_model') if st.session_state.get('ai_model') in ids else CUSTOM
    chosen = st.selectbox('Installed model', options, key='ai_installed_model')
    if chosen == CUSTOM:
        model = st.text_input('Model name', key='ai_model', placeholder='Enter the exact model identifier')
    else:
        model = chosen
        details = next((entry for entry in cached['models'] if entry['id'] == model), {})
        if details.get('size_bytes'):
            st.caption(f"Model file size: {details['size_bytes'] / 1024**3:.2f} GiB. Memory use and speed depend on the model and hardware.")
    with st.expander('Advanced model settings'):
        temperature = st.number_input('Temperature', min_value=0.0, max_value=2.0, step=0.1, key='ai_temperature')
        timeout = st.number_input('Response timeout (seconds)', min_value=15, max_value=600, step=15, key='ai_timeout_seconds')
        context = st.number_input('Context window (tokens)', min_value=512, max_value=32768, step=512, key='ai_context_length', help='Used for Ollama. For LM Studio, set the loaded model context in LM Studio.')
        output = st.number_input('Maximum answer tokens', min_value=64, max_value=8192, step=64, key='ai_max_output_tokens')
    selection = {**server, 'model': model.strip(), 'temperature': float(temperature), 'timeout_seconds': int(timeout),
                 'context_length': int(context), 'max_output_tokens': int(output)}
    fingerprint = _fingerprint(selection)
    name = st.text_input('Save profile as', key='ai_profile_name')
    test, apply = st.columns(2)
    if test.button('Test model', key='ai_test_model', disabled=not selection['model'], width='stretch'):
        try:
            with st.spinner('Testing an answer and the structured JSON used for drafts…'):
                result = api_post('/system/ai/test', selection)
            st.session_state['ai_test_result'] = {'selection': fingerprint, 'tested_at': time.monotonic(), **result}
        except Exception as exc:
            st.session_state.pop('ai_test_result', None)
            st.error('Model test failed: ' + friendly_error(exc))
    tested = st.session_state.get('ai_test_result', {})
    valid = (tested.get('selection') == fingerprint and tested.get('passed') is True
             and time.monotonic() - tested.get('tested_at', 0) < tested.get('valid_for_seconds', 600))
    if valid:
        st.success('Compatibility check passed.')
    else:
        st.caption('Test before applying. The active model stays selected if testing fails.')
    if apply.button('Save & apply model', key='ai_apply_model', disabled=not valid or not name.strip(), width='stretch', type='primary'):
        try:
            with st.spinner('Saving and applying your model…'):
                result = api_post('/system/ai/apply', {'selection': selection, 'profile_name': name.strip(), 'test_token': tested['test_token']})
            st.session_state['ai_notice'] = result['message']
            st.session_state.pop('ai_test_result', None)
            st.rerun()
        except Exception as exc:
            st.error('Could not apply the model: ' + friendly_error(exc))
    if provider == 'ollama':
        with st.expander('Download another Ollama model'):
            st.caption('Enter its exact name above using “Enter another model name…”. Downloads use the bundled Ollama model folder and may require several GB.')
            if not cached.get('download_available'):
                st.caption('Downloads here are enabled for the bundled Ollama server started by START_PROJECT.cmd.')
            if st.button('Download model', key='ai_download_model', disabled=not cached.get('download_available') or not selection['model']):
                try:
                    job = api_post('/system/ai/downloads', selection)
                    st.session_state['ai_download_job'] = job['job_id']
                    st.session_state['ai_download_running'] = True
                    st.rerun()
                except Exception as exc:
                    st.error(friendly_error(exc))
        _download_progress(api_get, friendly_error)


def _automatic_progress(api_get, api_post, friendly_error, initial):
    running = initial.get('status') == 'running'

    @st.fragment(run_every='2s' if running else None)
    def progress():
        try:
            job = api_get('/system/ai/setup')
            status = job.get('status', 'idle')
            if status == 'idle':
                return
            if running and status != 'running':
                st.rerun()
            if status == 'running':
                st.info(job.get('message', 'Preparing your AI…'))
                if job.get('stage') == 'downloading' and job.get('total'):
                    st.progress(min(1.0, job.get('completed', 0) / job['total']))
                    st.caption(f"Downloading model layer: {job.get('completed', 0) / 1e9:.2f} / {job['total'] / 1e9:.2f} GB")
                if st.button('Cancel setup', key='ai_cancel_automatic', disabled=job.get('stage') == 'applying'):
                    api_post('/system/ai/setup/cancel', {})
                    st.rerun()
            elif status == 'completed':
                return
            elif status == 'failed':
                st.error('Setup could not finish: ' + job.get('message', 'Try again.'))
                st.caption('Your previous model remains selected. You can retry; completed download bytes are reused.')
            elif status in {'cancelled', 'interrupted'}:
                st.info(job.get('message', 'The previous model was kept.'))
        except Exception as exc:
            st.error(friendly_error(exc))
    progress()


def _model_label(entry):
    return ('Qwen3 ' + entry['id'].split(':')[1].upper() + ' · ' + entry['name']) if entry['id'].startswith('qwen3:') else entry['name']


def _render_model_picker(api_get, api_post, friendly_error):
    try:
        info = api_get('/system/ai')
        active = info['active']
        _model_card('MAIN AI',active['model'],LABELS.get(active['provider'],active['provider'])+' · Answers & drafts')
        st.session_state.setdefault('ai_picker_provider', active['provider'])
        with st.container(key='ai_picker_controls'):
            model_column,engine_column=st.columns([4,1],vertical_alignment='bottom')
        with engine_column.popover('Engine',icon=':material/settings_input_component:',width='stretch'):
            provider = st.selectbox('Engine', list(LABELS), format_func=LABELS.get, key='ai_picker_provider')
            refresh = st.button('Refresh models', key='ai_picker_refresh',width='stretch')
        base = active['base_url'] if provider == active['provider'] else URLS[provider]
        installed, server_error = {}, None
        try:
            catalog = api_get('/system/ai/models?' + urlencode({'provider': provider, 'base_url': base}))
            installed = {entry['id']: entry for entry in catalog['models']}
        except Exception as exc:
            server_error = friendly_error(exc)
        plan = api_get('/system/ai/recommendations?mode=balanced&refresh=' + str(refresh).lower()) if provider == 'ollama' else None
        choices = {entry['id']: entry for entry in plan['options']} if plan else {}
        for model in installed:
            choices.setdefault(model, {'id': model, 'name': model, 'eligible': True, 'fit': 'Installed model; compatibility will be tested.'})
        if provider == 'lmstudio':
            st.caption('Load models in LM Studio before switching.')
        if server_error:
            st.warning('The local model engine could not be reached. ' + server_error)
            if provider == 'ollama' and info.get('bundled_ollama_available') and st.button('Start local AI engine', key='ai_picker_start'):
                api_post('/system/ai/start-ollama', {})
                st.rerun()
        if not choices:
            st.info('No models are available yet. Start the selected engine and refresh the model list.')
            return
        keys = sorted(choices, key=lambda model: (model not in installed, model))
        if st.session_state.get('ai_picker_model') not in choices:
            st.session_state['ai_picker_model'] = active['model'] if active['provider'] == provider and active['model'] in choices else keys[0]
        chosen = model_column.selectbox('Model', keys, key='ai_picker_model',
            format_func=lambda model: _model_label(choices[model]))
        entry = choices[chosen]
        if chosen in installed:
            size = installed[chosen].get('size_bytes')
            st.caption((f"Installed · {size / 1024**3:.2f} GiB" if size else 'Installed')+' · '+entry['fit'])
        else:
            st.caption(f"Download · {entry['download_gb']:.1f} GB · "+entry['fit'])
        running = info.get('setup', {}).get('status') == 'running'
        bundled = info.get('bundled_ollama_available') and base == (info.get('managed_ollama_url') or URLS['ollama'])
        # A loaded larger model can itself consume the available RAM. Allow an
        # installed replacement to be tested: Ollama can evict the old runner.
        blocked = not entry.get('eligible', True) or bool(chosen not in installed and plan and plan.get('blocked_reason'))
        if blocked:
            st.warning(plan.get('blocked_reason') or 'This model needs more memory or disk than the current hardware plan allows.')
        if st.button('Apply model', type='primary', width='stretch', key='ai_picker_use',help='Downloads and tests if needed. Applying a model pauses automatic hardware matching.',
                     disabled=running or blocked or (chosen not in installed and not bundled) or (chosen in installed and bool(server_error))):
            if chosen in installed:
                selection = {**active, 'provider': provider, 'base_url': base, 'model': chosen}
                api_post('/system/ai/switch', {'selection': selection})
            else:
                api_post('/system/ai/setup', {'mode': 'balanced', 'model': chosen, 'auto_adjust': False})
            st.rerun()
        _automatic_progress(api_get, api_post, friendly_error, info.get('setup', {'status': 'idle'}))
        st.button('Match my hardware',key='ai_open_hardware',icon=':material/memory:',on_click=_open_hardware,width='stretch')
    except Exception as exc:
        st.error('Model selection could not finish: ' + friendly_error(exc))


def _gib(value):
    return 'Unavailable' if value is None else f'{value / 1024**3:.2f} GiB'


def _render_resources(api_get, friendly_error):
    st.subheader('Resources')
    live = st.checkbox('Refresh automatically', value=True, key='ai_resources_live')
    st.button('Refresh resource usage', key='ai_resources_refresh')

    @st.fragment(run_every='5s' if live else None)
    def snapshot():
        try:
            report = api_get('/system/ai/resources')
            system = report['system']
            st.caption('Measured ' + report['measured_at'] + f" · CPU sample {report['sample_seconds']:.2f}s · selected model: {report['active']['model']}")
            columns = st.columns(3)
            columns[0].metric('Computer RAM in use', _gib(system['ram_used_bytes']))
            columns[1].metric('RAM available', _gib(system['ram_available_bytes']))
            columns[2].metric('Computer CPU use', f"{system['cpu_percent']:.1f}%")
            st.progress(min(1.0, system['ram_used_bytes'] / system['ram_total_bytes']))
            st.subheader('Chat models: installed versus loaded')
            if report.get('model_error'):
                st.warning(report['model_error'])
            st.dataframe([{'Model': item['model'], 'Role': ', '.join(item.get('roles',[])) or 'Available', 'Selected': item['selected'],
                'Status': 'Loaded' if item['loaded'] is True else 'Unloaded / idle' if item['loaded'] is False else 'Unknown',
                'On disk': _gib(item['disk_bytes']), 'Runtime allocation': _gib(item['allocation_bytes']),
                'GPU portion': _gib(item['gpu_bytes']), 'Non-GPU portion (estimate)': _gib(item['non_gpu_bytes'])} for item in report['models']],
                hide_index=True, width='stretch')
            st.caption('Model allocations overlap process and GPU totals.')
            st.subheader('App components in RAM')
            st.dataframe([{'Component': item['component'], 'Resident RAM': _gib(item['resident_bytes']),
                'Share of total RAM': f"{item['resident_bytes'] / system['ram_total_bytes'] * 100:.1f}%",
                'CPU (whole computer)': f"{item['cpu_percent']:.1f}%", 'Processes': item['processes']} for item in report['processes']],
                hide_index=True, width='stretch')
            st.caption('Search embeddings are included in API memory.')
            st.subheader('Graphics processor')
            for device in report['gpu']['devices']:
                st.write(f"{device['name']} · {_gib(device['used_bytes'])} / {_gib(device['total_bytes'])} · {device['utilization_percent']:.1f}% busy")
            st.caption(report['gpu']['note'])
            st.subheader('Storage breakdown')
            if report.get('storage_scanning'):
                st.caption('Storage sizes are being measured in the background. Live memory and CPU readings continue above.')
            st.dataframe([{'Component': item['component'], 'Disk space': _gib(item['bytes'])} for item in report['storage']], hide_index=True, width='stretch')
            with st.expander('How these measurements work'):
                for note in report['notes']:
                    st.write(note)
        except Exception as exc:
            st.error('Resource measurements are unavailable: ' + friendly_error(exc))
    snapshot()


def render_ai_settings(api_get, api_post, friendly_error):
    st.markdown('<div class="product-header product-ai-marker"><h1>AI settings</h1><p>Models, quality and performance.</p></div>',unsafe_allow_html=True)
    legacy=st.session_state.get('ai_setup_view')
    if legacy in {'Automatic','Resources'}:
        st.session_state['ai_setup_view']='Advanced'
        st.session_state['ai_advanced_view']='Hardware' if legacy=='Automatic' else 'Resources'
    labels={'Choose a model':'Main AI','Quality agent':'Quality agent','Models':'Library','Advanced':'Advanced'}
    view = st.segmented_control('AI setup', list(labels),format_func=labels.get,default='Choose a model', key='ai_setup_view',label_visibility='collapsed',width='stretch') or 'Choose a model'
    if view == 'Models':
        from frib_ds.dashboard.model_library_ui import render_model_library
        render_model_library(api_get,api_post,friendly_error)
        return
    if view == 'Quality agent':
        from frib_ds.dashboard.model_library_ui import render_quality_agent_settings
        render_quality_agent_settings(api_get,api_post,friendly_error)
        return
    if view == 'Choose a model':
        _render_model_picker(api_get, api_post, friendly_error)
        return
    if view == 'Advanced':
        advanced=st.segmented_control('Advanced settings',['Connection','Hardware','Resources'],default='Connection',key='ai_advanced_view',label_visibility='collapsed') or 'Connection'
        if advanced=='Hardware': _render_automatic_settings(api_get,api_post,friendly_error)
        elif advanced=='Resources': _render_resources(api_get,friendly_error)
        else: _render_advanced_settings(api_get, api_post, friendly_error)
        return


def _render_automatic_settings(api_get,api_post,friendly_error):
    st.subheader('Hardware matching')
    try:
        info = api_get('/system/ai')
        active = info['active']
        policy = info.get('automation', {})
        st.caption(f"Active · {active['model']}")
        st.session_state.setdefault('ai_preference', policy.get('mode', 'balanced'))
        modes = {'balanced': 'Recommended balance', 'speed': 'Prefer speed', 'capacity': 'Prefer a larger model'}
        preference = st.selectbox('What matters most?', list(modes), format_func=modes.get, key='ai_preference')
        refresh = st.button('Recheck my hardware', key='ai_refresh_hardware')
        plan = api_get('/system/ai/recommendations?' + urlencode({'mode': preference, 'refresh': str(refresh).lower()}))
    except Exception as exc:
        st.error('Automatic setup could not read this computer: ' + friendly_error(exc))
        return
    hardware = plan['hardware']
    memory = hardware.get('memory', {}).get('total_gib')
    disk = hardware.get('disk', {}).get('free_gib')
    devices = hardware.get('gpu', {}).get('devices', [])
    gpu = max((device.get('memory_gib', 0) for device in devices), default=0)
    columns = st.columns(3)
    columns[0].metric('Computer memory', f'{memory:.1f} GiB' if memory is not None else 'Unknown')
    columns[1].metric('Graphics memory', f'{gpu:.1f} GiB' if devices else 'Not detected')
    columns[2].metric('Free storage', f'{disk:.1f} GiB' if disk is not None else 'Unknown')
    if devices:
        st.caption(' · '.join(device.get('name', 'Graphics processor') for device in devices))
    if plan.get('hardware_changed'):
        st.info('Your hardware has changed since the last setup. A fresh model recommendation is available.')
    selected = plan.get('recommended')
    if selected:
        st.subheader(f"Recommended: {selected['name']} · {selected['id']}")
        st.write(selected['fit'])
        st.caption('Installed' if selected['installed'] else f"Download · {selected['download_gb']:.1f} GB")
    if plan.get('blocked_reason'):
        st.warning(plan['blocked_reason'])
    default_auto = policy.get('enabled', False) if policy.get('hardware_signature') else True
    if 'ai_pending_auto_adjust' in st.session_state:
        st.session_state['ai_auto_adjust'] = st.session_state.pop('ai_pending_auto_adjust')
    st.session_state.setdefault('ai_auto_adjust', default_auto)
    automatic = st.checkbox('Automatically adapt when my hardware changes', key='ai_auto_adjust',
                            help='Saved when setup completes. While the app is running, and on the next start, it rechecks changed hardware and prepares the recommended model automatically.')
    if policy.get('enabled'):
        if st.button('Pause automatic matching', key='ai_pause_matching'):
            try:
                api_post('/system/ai/automation/pause', {})
                st.session_state['ai_pending_auto_adjust'] = False
                st.rerun()
            except Exception as exc:
                st.error(friendly_error(exc))
    running = info.get('setup', {}).get('status') == 'running'
    available = info.get('bundled_ollama_available', False)
    if not available:
        st.caption('Use START_PROJECT.cmd to enable automatic downloads and setup with the bundled model engine.')
    if st.button('Optimize AI for this computer', key='ai_optimize', type='primary', width='stretch',
                 disabled=running or not available or bool(plan.get('blocked_reason')) or not selected):
        try:
            api_post('/system/ai/setup', {'mode': preference, 'auto_adjust': automatic})
            st.rerun()
        except Exception as exc:
            st.error(friendly_error(exc))
    _automatic_progress(api_get, api_post, friendly_error, info.get('setup', {'status': 'idle'}))
    with st.expander('Choose another model size'):
        eligible = [item for item in plan['options'] if item['eligible']]
        if eligible:
            choices = {item['id']: item for item in eligible}
            option = st.selectbox('Models that fit this computer', list(choices),
                                  format_func=lambda value: f"{choices[value]['name']} · {value}", key='ai_size_choice')
            item = choices[option]
            st.write(item['fit'])
            st.caption(f"Model download size: about {item['download_gb']:.1f} GB. Already installed models are reused.")
            if st.button('Set up this model automatically', key='ai_setup_choice', disabled=running or not available or bool(plan.get('blocked_reason'))):
                try:
                    api_post('/system/ai/setup', {'mode': preference, 'model': option, 'auto_adjust': False})
                    st.rerun()
                except Exception as exc:
                    st.error(friendly_error(exc))
        st.dataframe([{'Model': item['name'] + ' · ' + item['id'], 'Fit': item['fit'], 'Download GB': item['download_gb']} for item in plan['options']], hide_index=True, width='stretch')
    with st.expander('Hardware details'):
        st.caption(plan['note'])
