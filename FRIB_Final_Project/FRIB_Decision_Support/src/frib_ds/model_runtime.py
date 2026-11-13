"""Share a local inference slot; interactive requests take priority over agents."""
from contextlib import contextmanager
import threading
import time
from functools import wraps
from urllib.parse import urlsplit

_condition = threading.Condition()
_servers = {}


def serialized_inference(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with inference_slot(self.base_url, background=getattr(self, 'background', False), timeout=self.timeout):
            return method(self, *args, **kwargs)
    return call


@contextmanager
def inference_slot(address, *, background=False, timeout=300):
    deadline = time.monotonic() + timeout
    parsed=urlsplit(address)
    if parsed.hostname in {'localhost','127.0.0.1'}:
        address=f'{parsed.scheme}://127.0.0.1:{parsed.port}'+parsed.path.rstrip('/')
    with _condition:
        state = _servers.setdefault(address.rstrip('/'), {'active': False, 'interactive': 0})
        if not background:
            state['interactive'] += 1
        try:
            while state['active'] or (background and state['interactive']):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('The local AI engine is busy. Retry when the current request finishes.')
                _condition.wait(remaining)
            state['active'] = True
        finally:
            if not background:
                state['interactive'] -= 1
                _condition.notify_all()
    try:
        yield
    finally:
        with _condition:
            state['active'] = False
            _condition.notify_all()
