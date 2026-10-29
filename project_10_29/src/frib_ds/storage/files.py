from pathlib import Path
import hashlib
import shutil
import re
import uuid
from datetime import datetime, timezone
from frib_ds.models import EngineeringEvent

class EventFileStore:
    def __init__(self, event_dir: Path):
        self.event_dir=Path(event_dir).resolve(); self.event_dir.mkdir(parents=True,exist_ok=True)
    def directory(self,event_id:str)->Path:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",event_id) or event_id in {".",".."}:
            raise ValueError("event_id must contain only letters, numbers, underscores, periods or hyphens")
        directory=(self.event_dir/event_id).resolve()
        if directory.parent != self.event_dir:
            raise ValueError("invalid event file location")
        return directory
    def save(self,event:EngineeringEvent)->Path:
        d=self.directory(event.event_id); d.mkdir(exist_ok=False)
        payload=event.model_dump_json(indent=2)
        p=d/"event.json"
        try:
            original_bytes=payload.encode("utf-8")
            p.write_bytes(original_bytes)
            checksum=hashlib.sha256(original_bytes).hexdigest()
            (d/"sha256.txt").write_text(checksum+"\n",encoding="utf-8")
        except Exception:
            self.delete(event.event_id)
            raise
        return p

    def original(self,event_id:str)->Path:
        return self.directory(event_id)/"event.json"

    def attachment_path(self,event_id:str,file_id:str)->Path:
        if not re.fullmatch(r"FILE-[a-f0-9]{32}",file_id): raise ValueError("invalid file identifier")
        directory=self.directory(event_id)
        attachments=(directory/"attachments").resolve()
        if attachments.parent != directory: raise ValueError("invalid attachment location")
        return attachments/file_id

    def save_attachment(self,event_id:str,filename:str,contents:bytes)->dict:
        if not filename or len(filename)>240 or any(char in filename for char in ("/","\\",":","\x00","\r","\n")):
            raise ValueError("Upload a filename without a filesystem path")
        if Path(filename).suffix.lower() not in {".csv",".tsv",".json",".txt",".log",".md",".pdf",".png",".jpg",".jpeg"}:
            raise ValueError("Supported evidence files: CSV, TSV, JSON, TXT, LOG, MD, PDF, PNG and JPG")
        if not contents: raise ValueError("The uploaded evidence file is empty")
        if len(contents)>20*1024*1024: raise ValueError("Evidence file exceeds the 20 MB upload limit")
        file_id=f"FILE-{uuid.uuid4().hex}"
        path=self.attachment_path(event_id,file_id)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("xb") as stream: stream.write(contents)
        return {"file_id":file_id,"event_id":event_id,"filename":filename,
                "uploaded_at":datetime.now(timezone.utc).isoformat(),"checksum":hashlib.sha256(contents).hexdigest(),"size_bytes":len(contents)}

    def delete_attachment(self,event_id:str,file_id:str):
        self.attachment_path(event_id,file_id).unlink(missing_ok=True)

    def delete(self,event_id:str)->None:
        d=self.directory(event_id)
        if d.exists(): shutil.rmtree(d)
