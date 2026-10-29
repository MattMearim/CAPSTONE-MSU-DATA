from __future__ import annotations
from pathlib import Path
import uuid, re
from frib_ds.models import DocumentChunk

class DocumentLoader:
    def __init__(self, max_chars:int=1600, overlap_chars:int=220):
        if not 64 <= max_chars <= 100000 or not 0 <= overlap_chars < max_chars:
            raise ValueError("Document chunks need 64 to 100,000 characters and overlap smaller than chunk size")
        self.max_chars=max_chars
        self.overlap_chars=overlap_chars
    def load(self,path:str|Path,approved:bool=False,title:str|None=None,version:str|None=None,document_id:str|None=None,source_path:str|None=None)->list[DocumentChunk]:
        p=Path(path); suffix=p.suffix.lower(); pages=[]
        if suffix in {".txt",".md"}:
            pages=[p.read_text(encoding="utf-8")]
        elif suffix==".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as e:
                raise RuntimeError("Install the 'rag' extra to load PDF files") from e
            try:
                reader=PdfReader(str(p))
                if reader.is_encrypted: raise ValueError("Password-protected PDFs are not supported")
                if len(reader.pages)>500: raise ValueError("PDF exceeds the 500-page upload limit")
                pages=[page.extract_text() or "" for page in reader.pages]
            except ValueError: raise
            except Exception as exc: raise ValueError("The PDF could not be read; upload a valid text-based PDF") from exc
        else: raise ValueError(f"Unsupported document type: {suffix}")
        doc_id=document_id or f"DOC-{uuid.uuid4().hex[:10]}"; chunks=[]
        for page_no,text in enumerate(pages,start=1):
            chunks.extend(self._chunk_page(doc_id,title or p.stem,text,page_no,approved,version,source_path or p.name,self.max_chars,self.overlap_chars))
        return chunks

    def _chunk_page(self,doc_id,title,text,page,approved,version,source_path,max_chars=1600,overlap=220):
        text=re.sub(r"\r\n?","\n",text).strip()
        if not text: return []
        paragraphs=[x.strip() for x in re.split(r"\n\s*\n",text) if x.strip()]
        out=[]; buf=""; section=None
        def emit(body):
            if body.strip():
                idx=len(out)+1; out.append(DocumentChunk(chunk_id=f"{doc_id}-P{page}-C{idx}",document_id=doc_id,title=title,text=body.strip(),page=page,section=section,version=version,approved=approved,source_path=source_path))
        for para in paragraphs:
            first=para.splitlines()[0] if para else ""
            if len(first)<120 and (first.startswith("#") or re.match(r"^\d+(\.\d+)*\s+",first)):
                emit(buf)
                buf=""
                section=first.lstrip("# ")
            if len(para)>max_chars:
                emit(buf)
                buf=""
                for start in range(0,len(para),max_chars-overlap):
                    emit(para[start:start+max_chars])
                continue
            if len(buf)+len(para)+2<=max_chars: buf=(buf+"\n\n"+para).strip()
            else:
                emit(buf)
                prefix=(buf[-overlap:]+"\n\n") if overlap and buf and len(para)+overlap+2<=max_chars else ""
                buf=(prefix+para).strip()
        emit(buf); return out
