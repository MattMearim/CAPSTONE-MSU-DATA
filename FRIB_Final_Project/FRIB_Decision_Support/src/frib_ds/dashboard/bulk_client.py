"""Stream multipart uploads without building a second copy of an entire batch."""
from __future__ import annotations

import json
import uuid


class MultipartBatch:
    chunk_size = 1024 * 1024

    def __init__(self, uploads, options=None, on_progress=None):
        self.boundary = "frib-" + uuid.uuid4().hex
        self.content_type = "multipart/form-data; boundary=" + self.boundary
        self.on_progress = on_progress
        self.parts = []
        for name, value in (("options", json.dumps(options or {}, allow_nan=False)), ("approved_documents", "false")):
            header = f'--{self.boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            self.parts.append((header, value.encode(), None))
        for upload in uploads:
            filename = str(upload.name)
            if any(character in filename for character in "\r\n\x00"):
                raise ValueError("File names cannot contain control characters.")
            escaped = filename.replace("\\", "\\\\").replace('"', '\\"')
            header = (f'--{self.boundary}\r\nContent-Disposition: form-data; name="files"; filename="{escaped}"\r\n'
                      'Content-Type: application/octet-stream\r\n\r\n').encode("utf-8")
            upload.seek(0, 2)
            size = upload.tell()
            upload.seek(0)
            self.parts.append((header, upload, size))
        self.ending = f"--{self.boundary}--\r\n".encode()
        self.length = sum(len(header) + (len(body) if size is None else size) + 2 for header, body, size in self.parts) + len(self.ending)

    def __len__(self):
        return self.length

    def __iter__(self):
        sent = 0
        for header, body, size in self.parts:
            yield header
            sent += len(header)
            if size is None:
                yield body
                sent += len(body)
            else:
                body.seek(0)
                remaining = size
                while remaining:
                    chunk = body.read(min(self.chunk_size, remaining))
                    if not chunk:
                        raise ValueError("A selected file changed while uploading. Select the batch again.")
                    remaining -= len(chunk)
                    sent += len(chunk)
                    yield chunk
                    if self.on_progress:
                        self.on_progress(sent, self.length)
            yield b"\r\n"
            sent += 2
        yield self.ending
        if self.on_progress:
            self.on_progress(self.length, self.length)
