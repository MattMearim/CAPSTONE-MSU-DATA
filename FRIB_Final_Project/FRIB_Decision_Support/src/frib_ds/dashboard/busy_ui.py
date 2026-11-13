"""Offline run animation and honest progress for blocking application requests.

The UI stays on Streamlit's thread. Only the supplied operation runs in a daemon
thread; requests must retain their own bounded network timeout. Opaque AI calls
show explicitly estimated progress, never claiming measured token completion.
File jobs use ``render_run_animation`` beside server-reported progress instead.
"""
from __future__ import annotations

from html import escape
import json
import math
from pathlib import Path
import queue
import threading
import time
import uuid
from typing import Callable, TypeVar

import streamlit as st
import streamlit.components.v1 as components

T = TypeVar("T")
ASSETS = Path(__file__).with_name("run_component")
LOOP_END_FRAME = 26
NOTICE_KEY = "frib_run_receipt"
UPDATE_INTERVAL_SECONDS = .25


def estimated_progress(elapsed_seconds: float) -> int:
    """A monotonic waiting estimate; only an actual response can complete it.

    A typical request passes the midpoint at about 23 seconds. Slower requests
    approach 95% gradually and remain there, rather than falsely finishing.
    This estimates elapsed waiting, not model tokens or server work units.
    """
    elapsed = max(0.0, float(elapsed_seconds))
    return min(95, max(1, round(1 + 94 * -math.expm1(-elapsed / 30))))


def _running_progress_text(percentage: int) -> str:
    return f"{percentage}% estimated · {'Still running' if percentage == 95 else 'Working on your request'}"


def _running_progress_detail(elapsed_seconds: float) -> str:
    return (f"{max(0, int(elapsed_seconds))}s elapsed · Estimated progress; the service does not report "
            "intermediate percentages. 100% means the response is ready.")


def animation_document(state: str = "running", label: str = "Working", *, reduced: bool = False) -> str:
    """Build a self-contained iframe using only the curated local animation."""
    if state not in {"running", "success", "failed"}:
        raise ValueError("Unknown run animation state")
    data = json.loads((ASSETS / "cred_success.json").read_text(encoding="utf-8"))
    if data.get("fr") != 30 or data.get("op", 0) <= LOOP_END_FRAME:
        raise ValueError("The run animation has an unsupported timeline")
    # The supplied composition is shapes only. Never permit file or URL assets.
    if any(asset.get("p") or asset.get("u") for asset in data.get("assets", [])):
        raise ValueError("Run animation assets must be local shapes")
    player = (ASSETS / "lottie_light.min.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    encoded = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    state_json = json.dumps(state)
    forced_reduced = json.dumps(bool(reduced))
    safe_label = escape(str(label))
    caption = {"running": "Working on your request", "success": "Completed successfully", "failed": "Request needs attention"}[state]
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box}}body{{margin:0;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#193b2c;background:transparent}}
.run{{display:flex;align-items:center;gap:14px;min-height:94px;padding:5px 12px;border:1px solid #d5e5d9;border-radius:16px;background:linear-gradient(120deg,#f0f7ef,#fff)}}
#art{{width:86px;height:86px;flex:0 0 86px}}.copy{{min-width:0}}strong{{display:block;font-size:15px;font-weight:650;line-height:1.4}}p{{margin:4px 0 0;color:#5d6e63;font-size:12px;line-height:1.4}}.failure{{font-size:38px;color:#a54835;text-align:center;line-height:86px}}
</style></head><body><div class="run" role="status" aria-live="polite"><div id="art" aria-hidden="true"></div><div class="copy"><strong>{safe_label}</strong><p>{caption}</p></div></div>
<script>{player}</script><script>
const state={state_json};const forceReduced={forced_reduced};const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
if(state==='failed'){{document.getElementById('art').textContent='!';document.getElementById('art').className='failure';}}
else{{const animation=lottie.loadAnimation({{container:document.getElementById('art'),renderer:'svg',loop:false,autoplay:false,animationData:{encoded}}});
function play(){{if(forceReduced||reduced.matches){{animation.goToAndStop(state==='success'?64:0,true);return;}}if(state==='success'){{animation.loop=false;animation.playSegments([26,65],true);}}else{{animation.loop=true;animation.playSegments([0,26],true);}}}}
animation.addEventListener('DOMLoaded',play);reduced.addEventListener('change',play);
animation.addEventListener('complete',()=>{{if(state==='success')animation.goToAndStop(64,true);}});
}}
</script></body></html>'''


def render_run_animation(state: str = "running", label: str = "Working"):
    components.html(animation_document(state, label, reduced=not st.session_state.get("interface_motion", True)), height=108, scrolling=False)


def _progress_style():
    st.markdown('''<style>
[class*="st-key-frib_run_status_"] [data-testid="stProgress"] [role="progressbar"],
.st-key-frib_run_receipt [data-testid="stProgress"] [role="progressbar"],
.st-key-bulk_progress [data-testid="stProgress"] [role="progressbar"]{height:12px;border-radius:999px;box-shadow:0 0 0 1px #c5d9c7;}
[class*="st-key-frib_run_status_"] [data-testid="stProgress"] p,
.st-key-frib_run_receipt [data-testid="stProgress"] p,
.st-key-bulk_progress [data-testid="stProgress"] p{font-size:.9rem;font-weight:650;color:#24573d;}
[class*="st-key-frib_run_status_"] [data-testid="stProgress"] [role="progressbar"][aria-valuenow="0"]{background:linear-gradient(90deg,#d8ead7 20%,#83b887 50%,#d8ead7 80%);background-size:200% 100%;animation:frib-wait 1.8s ease-in-out infinite;}
@keyframes frib-wait{to{background-position:-200% 0}}
@media(prefers-reduced-motion:reduce){[class*="st-key-frib_run_status_"] [data-testid="stProgress"] [role="progressbar"]{animation:none!important;}}
</style>''', unsafe_allow_html=True)


def _worker(operation: Callable[[], T], result: queue.Queue):
    try:
        result.put((True, operation()))
    except BaseException as exc:
        result.put((False, exc))


def run_with_progress(operation: Callable[[], T], label: str = "Working…", *, completed_label: str = "Finished",
                      retain_receipt: bool = True) -> T:
    """Run once; animate until a response is validated, then finish or fail.

    Intermediate AI percentages are unavailable from the current service. The
    numeric waiting estimate updates in place and is capped at 95%; 100% means
    the operation returned successfully. Exceptions are re-raised unchanged,
    and an error never plays the completion/checkmark segment. Callers that
    remain on their current page can disable the separate next-rerun receipt.
    """
    st.session_state.pop(NOTICE_KEY, None)
    _progress_style()
    slot = st.empty()
    with slot.container():
        with st.container(key="frib_run_status_" + uuid.uuid4().hex):
            animation = st.empty()
            with animation.container():
                render_run_animation("running", label)
            progress = st.progress(1, text=_running_progress_text(1))
            detail = st.empty()
            detail.caption(_running_progress_detail(0))
    result: queue.Queue = queue.Queue(maxsize=1)
    worker = threading.Thread(target=_worker, args=(operation, result), daemon=True, name="frib-ui-request")
    started = time.monotonic()
    worker.start()
    while True:
        try:
            succeeded, value = result.get(timeout=UPDATE_INTERVAL_SECONDS)
            break
        except queue.Empty:
            elapsed = time.monotonic() - started
            # Update native controls in their original position. The animation
            # iframe is not replaced, so its bouncing loop stays uninterrupted.
            percentage = estimated_progress(elapsed)
            progress.progress(percentage, text=_running_progress_text(percentage))
            detail.caption(_running_progress_detail(elapsed))
    if not succeeded:
        with animation.container():
            render_run_animation("failed", "Request needs attention")
        progress.empty()
        detail.caption("The request did not complete. Review the error below before retrying.")
        raise value
    progress.progress(100, text="100% · " + completed_label)
    detail.empty()
    with animation.container():
        render_run_animation("success", completed_label)
    if retain_receipt:
        st.session_state[NOTICE_KEY] = {"label": str(completed_label), "token": uuid.uuid4().hex}
    return value


def render_run_receipt():
    """Keep the success ending visible after a caller immediately reruns the app."""
    notice = st.session_state.pop(NOTICE_KEY, None)
    if isinstance(notice, dict) and notice.get("label"):
        _progress_style()
        with st.container(key="frib_run_receipt"):
            render_run_animation("success", str(notice["label"]))
            st.progress(100, text="100% · " + str(notice["label"]))
