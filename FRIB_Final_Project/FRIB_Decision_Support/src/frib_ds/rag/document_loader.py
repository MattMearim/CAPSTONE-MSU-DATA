from __future__ import annotations
import io
from pathlib import Path
import uuid, re
from frib_ds.models import DocumentChunk

# Budgets apply before embedding, including unapproved-document validation.
# The output budget also bounds duplication caused by large overlap settings.
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARS = 20 * 1024 * 1024
MAX_DOCUMENT_CHUNKS = 10_000
MAX_CHUNK_TEXT_CHARS = 32 * 1024 * 1024

class DocumentLoader:
    def __init__(self, max_chars:int=1600, overlap_chars:int=220):
        if not 64 <= max_chars <= 100000 or not 0 <= overlap_chars < max_chars:
            raise ValueError("Document chunks need 64 to 100,000 characters and overlap smaller than chunk size")
        self.max_chars=max_chars
        self.overlap_chars=overlap_chars
    def load(self,path:str|Path,approved:bool=False,title:str|None=None,version:str|None=None,document_id:str|None=None,source_path:str|None=None)->list[DocumentChunk]:
        p=Path(path); suffix=p.suffix.lower()
        if suffix not in {".txt",".md",".pdf"}: raise ValueError(f"Unsupported document type: {suffix}")
        with p.open("rb") as stream:
            contents=stream.read(MAX_SOURCE_BYTES+1)
        if len(contents)>MAX_SOURCE_BYTES: raise ValueError("Document exceeds the 20 MB upload limit")
        if suffix in {".txt",".md"}:
            try: text=contents.decode("utf-8-sig")
            except UnicodeDecodeError as exc: raise ValueError("Text documents must use UTF-8 encoding") from exc
            if "\x00" in text: raise ValueError("Upload a nonempty text document without binary data")
            pages=[text]
        else:
            pages=self._pdf_pages(contents)
        doc_id=document_id or f"DOC-{uuid.uuid4().hex[:10]}"; chunks=[]
        extracted_chars=0
        budget={"chunks":0,"text_chars":0}
        for page_no,text in enumerate(pages,start=1):
            extracted_chars+=len(text)
            if extracted_chars>MAX_EXTRACTED_CHARS:
                raise ValueError("Document extracted text exceeds the 20 million character limit; upload a smaller document")
            chunks.extend(self._chunk_page(doc_id,title or p.stem,text,page_no,approved,version,source_path or p.name,self.max_chars,self.overlap_chars,budget=budget))
        return chunks

    @staticmethod
    def _pdf_pages(contents):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Install the 'rag' extra to load PDF files") from exc
        try:
            reader=PdfReader(io.BytesIO(contents))
            if reader.is_encrypted: raise ValueError("Password-protected PDFs are not supported")
            if len(reader.pages)>500: raise ValueError("PDF exceeds the 500-page upload limit")
            for page in reader.pages:
                yield page.extract_text() or ""
        except ValueError: raise
        except Exception as exc: raise ValueError("The PDF could not be read; upload a valid text-based PDF") from exc

    def _chunk_page(self,doc_id,title,text,page,approved,version,source_path,max_chars=1600,overlap=220,*,budget=None):
        text=re.sub(r"\r\n?","\n",text).strip()
        if not text: return []
        paragraphs=[x.strip() for x in re.split(r"\n\s*\n",text) if x.strip()]
        out=[]; buf=""; section=None
        budget=budget if budget is not None else {"chunks":0,"text_chars":0}
        def emit(body):
            body=body.strip()
            if body:
                if budget["chunks"]>=MAX_DOCUMENT_CHUNKS:
                    raise ValueError("Document exceeds the 10,000 chunk limit; upload a smaller document or increase the chunk size")
                if budget["text_chars"]+len(body)>MAX_CHUNK_TEXT_CHARS:
                    raise ValueError("Document chunk text exceeds the processing limit; reduce chunk overlap or upload a smaller document")
                budget["chunks"]+=1
                budget["text_chars"]+=len(body)
                idx=len(out)+1; out.append(DocumentChunk(chunk_id=f"{doc_id}-P{page}-C{idx}",document_id=doc_id,title=title,text=body,page=page,section=section,version=version,approved=approved,source_path=source_path))
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
                    if start+max_chars>=len(para): break
                continue
            if len(buf)+len(para)+2<=max_chars: buf=(buf+"\n\n"+para).strip()
            else:
                emit(buf)
                prefix=(buf[-overlap:]+"\n\n") if overlap and buf and len(para)+overlap+2<=max_chars else ""
                buf=(prefix+para).strip()
        emit(buf); return out
