"""Bound local API requests before parsing uploads or mutating saved data."""
from __future__ import annotations

import tempfile
from urllib.parse import urlsplit

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from frib_ds.storage.documents import MAX_DOCUMENT_BYTES

# One 20 MB upload plus its multipart fields; the per-file limit still applies.
MAX_REQUEST_BYTES = MAX_DOCUMENT_BYTES + 1024 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _local_address(value: str, *, origin: bool) -> bool:
    try:
        address = urlsplit(value if origin else "http://" + value)
        allowed = LOCAL_HOSTS if origin else LOCAL_HOSTS | {"testserver"}
        return (address.scheme in {"http", "https"} and address.hostname in allowed
                and address.username is None and address.password is None
                and not address.path and not address.query and not address.fragment
                and (address.port is None or 1 <= address.port <= 65535))
    except ValueError:
        return False


class LocalRequestSecurityMiddleware:
    """Keep untrusted websites out of a single-user loopback-only API.

    Python dashboard/CLI requests have no Origin header and remain supported.
    Bodies are bounded before Starlette's multipart parser can create files.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.lower(), []).append(value.decode("latin-1"))
        hosts = headers.get(b"host", [])
        origins = headers.get(b"origin", [])
        if len(hosts) != 1 or not _local_address(hosts[0], origin=False):
            await JSONResponse({"detail": "This API accepts local workspace hosts only."}, status_code=400)(scope, receive, send)
            return
        if origins and (len(origins) != 1 or not _local_address(origins[0], origin=True)):
            await JSONResponse({"detail": "Requests from unrelated websites are not allowed."}, status_code=403)(scope, receive, send)
            return
        # A single explicit bulk upload route has a separate disk-backed budget.
        # Ordinary file endpoints retain their existing 21 MiB request ceiling.
        request_limit=MAX_REQUEST_BYTES
        if scope.get("path")=="/ingestion/bulk" and scope.get("method")=="POST":
            from frib_ds.ingestion.bulk import bulk_limits
            request_limit=bulk_limits()["max_total_bytes"]+16*1024*1024
        lengths = headers.get(b"content-length", [])
        try:
            if len(lengths) > 1 or (lengths and (not lengths[0].isascii() or not lengths[0].isdigit())):
                raise ValueError
            if lengths and int(lengths[0]) > request_limit:
                await self._too_large(scope, receive, send,request_limit)
                return
        except ValueError:
            await JSONResponse({"detail": "Invalid request body length."}, status_code=400)(scope, receive, send)
            return

        # A bounded disk-backed spool validates chunked bodies too. No route or
        # multipart parser runs until the entire request fits the request budget.
        with tempfile.SpooledTemporaryFile(max_size=1024 * 1024) as body:
            total = 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                total += len(chunk)
                if total > request_limit:
                    await self._too_large(scope, receive, send,request_limit)
                    return
                if chunk:
                    await run_in_threadpool(body.write, chunk)
                if not message.get("more_body", False):
                    break
            body.seek(0)
            replay_finished = False

            async def replay():
                nonlocal replay_finished
                if replay_finished:
                    return await receive()
                chunk = await run_in_threadpool(body.read, 65536)
                more = body.tell() < total
                replay_finished = not more
                return {"type": "http.request", "body": chunk, "more_body": more}

            async def safe_send(message):
                if message["type"] == "http.response.start":
                    safe = {b"x-content-type-options": b"nosniff", b"cache-control": b"no-store", b"referrer-policy": b"no-referrer"}
                    existing = [(key, value) for key, value in message.get("headers", []) if key.lower() not in safe]
                    message = {**message, "headers": existing + list(safe.items())}
                await send(message)

            await self.app(scope, replay, safe_send)

    @staticmethod
    async def _too_large(scope, receive, send,limit=MAX_REQUEST_BYTES):
        detail="Request exceeds the 21 MB limit, including upload fields." if limit==MAX_REQUEST_BYTES else "Bulk upload exceeds the batch request size limit. Split the folder into smaller batches."
        await JSONResponse({"detail":detail}, status_code=413)(scope, receive, send)
