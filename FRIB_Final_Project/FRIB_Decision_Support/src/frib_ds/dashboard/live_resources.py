"""A browser-polled monitor keeps updating during long Streamlit operations."""
from urllib.parse import urlsplit

import streamlit as st


def render_live_resources(api_url, *, visible=True):
    if not visible:
        return
    address = urlsplit(api_url)
    if address.scheme not in {'http', 'https'} or address.hostname not in {'localhost', '127.0.0.1', '::1'} or address.username or address.password:
        return
    st.markdown('''<style>
    [data-testid="stLayoutWrapper"]:has(> .st-key-live_resource_monitor) {position:sticky;top:3.5rem;z-index:50;
        background:var(--background-color,#f7faf5);border-radius:14px;}
    .st-key-live_resource_monitor iframe {border-radius:14px;}
    @media(max-height:520px){[data-testid="stLayoutWrapper"]:has(> .st-key-live_resource_monitor){position:static;}}
    </style>''', unsafe_allow_html=True)
    with st.container(key='live_resource_monitor'):
        st.iframe(api_url.rstrip('/') + '/system/ai/monitor', height=166,
                  alt='Live CPU, RAM and GPU monitor. Updates every two seconds, including while AI is working.')
