from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
import uuid

from frib_ds.rag.document_loader import DocumentLoader


MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
SUPPORTED_DOCUMENT_TYPES = {".pdf", ".txt", ".md"}


class DocumentStore:
    """Manage originals, provenance and retrieval as one document lifecycle."""

    def __init__(self, directory:Path, repo, embedding, vector, rag_config=None):
        self.directory=Path(directory).resolve()
        self.directory.mkdir(parents=True,exist_ok=True)
        self.repo=repo; self.embedding=embedding; self.vector=vector
        chunking=(rag_config or {}).get("chunking",{})
        self.loader=DocumentLoader(int(chunking.get("max_chars",1600)),int(chunking.get("overlap_chars",220)))

    def _directory(self,document_id:str)->Path:
        if not re.fullmatch(r"DOC-[A-Za-z0-9]{10,32}",document_id):
            raise ValueError("invalid document identifier")
        path=(self.directory/document_id).resolve()
        if path.parent != self.directory: raise ValueError("invalid document location")
        return path

    @staticmethod
    def validate_filename(filename:str)->str:
        # Uploaded filenames are display metadata, never an input filesystem path.
        if not filename or len(filename)>240 or any(char in filename for char in ("/","\\",":","\x00","\r","\n")):
            raise ValueError("Upload a filename without a filesystem path")
        suffix=Path(filename).suffix.lower()
        if suffix not in SUPPORTED_DOCUMENT_TYPES:
            raise ValueError("Supported document types are PDF, TXT and MD")
        return suffix

    def upload(self,filename:str,contents:bytes,approved:bool=False,title:str|None=None,version:str|None=None)->dict:
        suffix=self.validate_filename(filename)
        if not contents: raise ValueError("The uploaded document is empty")
        if len(contents)>MAX_DOCUMENT_BYTES: raise ValueError("Document exceeds the 20 MB upload limit")
        if suffix==".pdf" and not contents.lstrip().startswith(b"%PDF-"):
            raise ValueError("The uploaded file is not a valid PDF")
        if suffix in {".txt",".md"}:
            try: text=contents.decode("utf-8-sig")
            except UnicodeDecodeError as exc: raise ValueError("Text documents must use UTF-8 encoding") from exc
            if not text.strip() or "\x00" in text: raise ValueError("Upload a nonempty text document")
        clean_title=(title or Path(filename).stem).strip()
        if not clean_title or len(clean_title)>300: raise ValueError("Document title must contain 1 to 300 characters")
        clean_version=version.strip() if version else None
        if clean_version and len(clean_version)>100: raise ValueError("Document version must be at most 100 characters")
        document_id=f"DOC-{uuid.uuid4().hex}"
        directory=self._directory(document_id); directory.mkdir(exist_ok=False)
        original=directory/f"original{suffix}"
        try:
            original.write_bytes(contents)
            chunks=self.loader.load(original,approved=approved,title=clean_title,version=clean_version,
                                    document_id=document_id,source_path=f"document:{document_id}/{filename}")
            if not chunks: raise ValueError("No readable text found; upload a text-based PDF, TXT or MD document")
            timestamp=datetime.now(timezone.utc).isoformat()
            metadata={"document_id":document_id,"filename":filename,"title":clean_title,"version":clean_version,
                      "approved":approved,"uploaded_at":timestamp,"checksum":hashlib.sha256(contents).hexdigest(),
                      "size_bytes":len(contents),"indexed_chunks":len(chunks) if approved else 0,
                      "approval_metadata":{"explicitly_approved":approved,"approved_at":timestamp if approved else None,
                                           "method":"upload_checkbox"}}
            vectors=self.embedding.embed([chunk.text for chunk in chunks]) if approved else []
            self.repo.save_document(metadata,chunks if approved else [],vectors)
            if approved: self.vector.add(chunks,vectors)
            self.repo.record_audit("upload","document",document_id,{"filename":filename,"checksum":metadata["checksum"],"approved":approved})
            return metadata
        except Exception:
            self.vector.delete_document(document_id)
            self.repo.delete_document(document_id)
            if directory.exists(): shutil.rmtree(directory)
            raise

    def original(self,document_id:str)->tuple[Path,dict]:
        metadata=self.repo.get_document(document_id)
        if not metadata: raise KeyError("document not found")
        suffix=self.validate_filename(metadata["filename"])
        path=self._directory(document_id)/f"original{suffix}"
        if not path.is_file(): raise FileNotFoundError("The stored original document is unavailable")
        return path,metadata

    def delete(self,document_id:str)->None:
        metadata=self.repo.get_document(document_id)
        if not metadata: raise KeyError("document not found")
        directory=self._directory(document_id)
        # Commit deletion before touching external index/files. Startup resumes
        # cleanup after an interrupted delete, so hydration cannot restore it.
        self.repo.delete_document(document_id)
        self.vector.delete_document(document_id)
        if directory.exists(): shutil.rmtree(directory)
        self.repo.record_audit("delete","document",document_id,{"filename":metadata["filename"],"checksum":metadata["checksum"]})

    def hydrate(self)->None:
        # The catalog is authoritative: deleted originals cannot be resurrected.
        for document_id in self.repo.deleted_document_ids():
            self.vector.delete_document(document_id)
            directory=self._directory(document_id)
            if directory.exists(): shutil.rmtree(directory)
        rows=self.repo.approved_document_chunks()
        if rows: self.vector.add([chunk for chunk,_ in rows],[vector for _,vector in rows])
