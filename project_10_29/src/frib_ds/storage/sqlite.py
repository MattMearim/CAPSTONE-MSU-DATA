from __future__ import annotations
import sqlite3, json
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from frib_ds.models import EngineeringEvent, AnalysisResult, KnowledgeDraft, ReviewRecord, KnowledgeRecord, DocumentChunk

class SQLiteRepository:
    def __init__(self, path: str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True); self._init()
    @contextmanager
    def connect(self):
        conn=sqlite3.connect(self.path)
        conn.row_factory=sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    def _init(self):
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, domain TEXT, event_type TEXT, timestamp TEXT, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS analyses(event_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT);
            CREATE TABLE IF NOT EXISTS drafts(draft_id TEXT PRIMARY KEY, event_id TEXT, status TEXT, payload TEXT NOT NULL, created_at TEXT);
            CREATE TABLE IF NOT EXISTS reviews(review_id TEXT PRIMARY KEY, draft_id TEXT, event_id TEXT, decision TEXT, reviewer TEXT, payload TEXT NOT NULL, timestamp TEXT);
            CREATE TABLE IF NOT EXISTS knowledge(knowledge_id TEXT PRIMARY KEY, event_id TEXT, payload TEXT NOT NULL, searchable_text TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY, filename TEXT NOT NULL, title TEXT NOT NULL, version TEXT, approved INTEGER NOT NULL, uploaded_at TEXT NOT NULL, checksum TEXT NOT NULL, size_bytes INTEGER NOT NULL, indexed_chunks INTEGER NOT NULL, approval_metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS document_chunks(chunk_id TEXT PRIMARY KEY, document_id TEXT NOT NULL, payload TEXT NOT NULL, vector TEXT);
            CREATE TABLE IF NOT EXISTS deleted_documents(document_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS document_chunks_document ON document_chunks(document_id);
            CREATE TABLE IF NOT EXISTS audit(audit_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS event_files(file_id TEXT PRIMARY KEY,event_id TEXT NOT NULL,filename TEXT NOT NULL,uploaded_at TEXT NOT NULL,checksum TEXT NOT NULL,size_bytes INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS repository_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            """)

    def ensure_embedding_compatibility(self,fingerprint:dict):
        """Never hydrate approved chunks with a different embedding definition."""
        serialized=json.dumps(fingerprint,sort_keys=True,separators=(",",":"))
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            existing=c.execute("SELECT value FROM repository_metadata WHERE key='embedding_fingerprint'").fetchone()
            populated=c.execute("SELECT 1 FROM document_chunks dc JOIN documents d ON dc.document_id=d.document_id WHERE d.approved=1 LIMIT 1").fetchone()
            if populated and (not existing or existing["value"]!=serialized):
                raise ValueError("The approved document index was created with different or unknown embedding settings. Use a separate FRIB_DATA_DIR and reupload the original documents before changing embedding provider, model, dimensions or tokenizer version.")
            c.execute("INSERT OR REPLACE INTO repository_metadata VALUES('embedding_fingerprint',?)",(serialized,))
    def save_event(self,e:EngineeringEvent):
        with self.connect() as c: c.execute("INSERT INTO events VALUES(?,?,?,?,?)",(e.event_id,e.domain,e.event_type,e.timestamp.isoformat(),e.model_dump_json()))
    def get_event(self,event_id:str)->EngineeringEvent|None:
        with self.connect() as c: r=c.execute("SELECT payload FROM events WHERE event_id=?",(event_id,)).fetchone()
        return EngineeringEvent.model_validate_json(r["payload"]) if r else None
    def list_events(self,limit:int=100):
        with self.connect() as c: rows=c.execute("SELECT event_id,domain,event_type,timestamp,json_extract(payload,'$.metadata.dataset_name') AS dataset_name,json_array_length(payload,'$.signals') AS signal_count,json_array_length(payload,'$.states') AS state_count,json_array_length(payload,'$.logs') AS log_count,json_array_length(payload,'$.metadata.unit_normalization.warnings') AS unit_warning_count FROM events ORDER BY timestamp DESC LIMIT ?",(limit,)).fetchall()
        return [dict(r) for r in rows]
    def delete_event(self,event_id:str):
        with self.connect() as c:
            c.execute("DELETE FROM analyses WHERE event_id=?",(event_id,))
            c.execute("DELETE FROM reviews WHERE event_id=?",(event_id,))
            c.execute("DELETE FROM drafts WHERE event_id=?",(event_id,))
            c.execute("DELETE FROM knowledge WHERE event_id=?",(event_id,))
            c.execute("DELETE FROM event_files WHERE event_id=?",(event_id,))
            c.execute("DELETE FROM events WHERE event_id=?",(event_id,))

    def save_analysis(self,a:AnalysisResult):
        with self.connect() as c: c.execute("INSERT OR REPLACE INTO analyses VALUES(?,?,?)",(a.event_id,a.model_dump_json(),a.created_at.isoformat()))
    def get_analysis(self,event_id:str)->AnalysisResult|None:
        with self.connect() as c: r=c.execute("SELECT payload FROM analyses WHERE event_id=?",(event_id,)).fetchone()
        return AnalysisResult.model_validate_json(r["payload"]) if r else None
    def save_draft(self,d:KnowledgeDraft):
        with self.connect() as c: c.execute("INSERT OR REPLACE INTO drafts VALUES(?,?,?,?,?)",(d.draft_id,d.event_id,d.status,d.model_dump_json(),d.created_at.isoformat()))
    def get_draft(self,draft_id:str)->KnowledgeDraft|None:
        with self.connect() as c: r=c.execute("SELECT payload FROM drafts WHERE draft_id=?",(draft_id,)).fetchone()
        return KnowledgeDraft.model_validate_json(r["payload"]) if r else None
    def latest_draft_for_event(self,event_id:str)->KnowledgeDraft|None:
        with self.connect() as c: r=c.execute("SELECT payload FROM drafts WHERE event_id=? ORDER BY created_at DESC LIMIT 1",(event_id,)).fetchone()
        return KnowledgeDraft.model_validate_json(r["payload"]) if r else None
    def save_review(self,r:ReviewRecord):
        with self.connect() as c: c.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?,?,?)",(r.review_id,r.draft_id,r.event_id,r.decision.value,r.reviewer,r.model_dump_json(),r.timestamp.isoformat()))
    def commit_review(self,final:KnowledgeDraft,record:ReviewRecord,knowledge:KnowledgeRecord|None):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            original=c.execute("SELECT payload,status FROM drafts WHERE draft_id=?",(final.draft_id,)).fetchone()
            if not original or original["status"]!="draft": raise ValueError("This draft has already been reviewed or is no longer available")
            c.execute("UPDATE drafts SET status=?,payload=? WHERE draft_id=?",(final.status,final.model_dump_json(),final.draft_id))
            c.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?)",(record.review_id,record.draft_id,record.event_id,record.decision.value,record.reviewer,record.model_dump_json(),record.timestamp.isoformat()))
            if knowledge:
                c.execute("INSERT INTO knowledge VALUES(?,?,?,?,?)",(knowledge.knowledge_id,knowledge.event_id,knowledge.model_dump_json(),knowledge.searchable_text,knowledge.created_at.isoformat()))
            details={"original_draft":json.loads(original["payload"]),"final_draft":final.model_dump(mode="json"),
                     "reviewer":record.reviewer,"comments":record.comments,"decision":record.decision.value,"event_id":record.event_id}
            c.execute("INSERT INTO audit(timestamp,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(
                record.timestamp.isoformat(),"review","draft",final.draft_id,json.dumps(details),
            ))
    def save_knowledge(self,k:KnowledgeRecord):
        with self.connect() as c: c.execute("INSERT OR REPLACE INTO knowledge VALUES(?,?,?,?,?)",(k.knowledge_id,k.event_id,k.model_dump_json(),k.searchable_text,k.created_at.isoformat()))
    def list_knowledge(self,limit:int=100):
        with self.connect() as c: rows=c.execute("SELECT payload FROM knowledge ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        return [KnowledgeRecord.model_validate_json(r["payload"]) for r in rows]
    def search_knowledge(self,q:str,limit:int=25):
        token=f"%{q.lower()}%"
        with self.connect() as c: rows=c.execute("SELECT payload FROM knowledge WHERE lower(searchable_text) LIKE ? ORDER BY created_at DESC LIMIT ?",(token,limit)).fetchall()
        return [KnowledgeRecord.model_validate_json(r["payload"]) for r in rows]

    def save_document(self, metadata:dict, chunks:list[DocumentChunk], vectors:list[list[float]]):
        with self.connect() as c:
            c.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?)",(
                metadata["document_id"],metadata["filename"],metadata["title"],metadata.get("version"),
                int(metadata["approved"]),metadata["uploaded_at"],metadata["checksum"],metadata["size_bytes"],
                metadata["indexed_chunks"],json.dumps(metadata.get("approval_metadata",{})),
            ))
            c.executemany("INSERT INTO document_chunks VALUES(?,?,?,?)",[
                (chunk.chunk_id,chunk.document_id,chunk.model_dump_json(),json.dumps(vector))
                for chunk,vector in zip(chunks,vectors)
            ])

    def save_event_file(self,metadata:dict):
        with self.connect() as c:
            c.execute("INSERT INTO event_files VALUES(?,?,?,?,?,?)",tuple(metadata[key] for key in ("file_id","event_id","filename","uploaded_at","checksum","size_bytes")))

    def list_event_files(self,event_id:str)->list[dict]:
        with self.connect() as c: rows=c.execute("SELECT * FROM event_files WHERE event_id=? ORDER BY uploaded_at DESC",(event_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_event_file(self,event_id:str,file_id:str)->dict|None:
        with self.connect() as c: row=c.execute("SELECT * FROM event_files WHERE event_id=? AND file_id=?",(event_id,file_id)).fetchone()
        return dict(row) if row else None

    def delete_event_file(self,event_id:str,file_id:str):
        with self.connect() as c: c.execute("DELETE FROM event_files WHERE event_id=? AND file_id=?",(event_id,file_id))

    @staticmethod
    def _document_metadata(row):
        item=dict(row); item["approved"]=bool(item["approved"])
        item["approval_metadata"]=json.loads(item["approval_metadata"])
        return item

    def get_document(self,document_id:str)->dict|None:
        with self.connect() as c: row=c.execute("SELECT * FROM documents WHERE document_id=?",(document_id,)).fetchone()
        return self._document_metadata(row) if row else None

    def list_documents(self,limit:int=1000)->list[dict]:
        with self.connect() as c: rows=c.execute("SELECT * FROM documents ORDER BY uploaded_at DESC LIMIT ?",(limit,)).fetchall()
        return [self._document_metadata(row) for row in rows]

    def approved_document_chunks(self):
        with self.connect() as c:
            rows=c.execute("SELECT dc.payload,dc.vector FROM document_chunks dc JOIN documents d ON dc.document_id=d.document_id WHERE d.approved=1").fetchall()
        return [(DocumentChunk.model_validate_json(row["payload"]),json.loads(row["vector"])) for row in rows]

    def delete_document(self,document_id:str):
        with self.connect() as c:
            c.execute("DELETE FROM document_chunks WHERE document_id=?",(document_id,))
            c.execute("DELETE FROM documents WHERE document_id=?",(document_id,))
            c.execute("INSERT OR REPLACE INTO deleted_documents VALUES(?,?)",(document_id,datetime.now(timezone.utc).isoformat()))

    def deleted_document_ids(self)->list[str]:
        with self.connect() as c: rows=c.execute("SELECT document_id FROM deleted_documents").fetchall()
        return [row["document_id"] for row in rows]

    def record_audit(self,action:str,entity_type:str,entity_id:str,details:dict|None=None):
        with self.connect() as c:
            c.execute("INSERT INTO audit(timestamp,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(
                datetime.now(timezone.utc).isoformat(),action,entity_type,entity_id,json.dumps(details or {}),
            ))

    def list_audit(self,limit:int=100)->list[dict]:
        with self.connect() as c: rows=c.execute("SELECT * FROM audit ORDER BY audit_id DESC LIMIT ?",(limit,)).fetchall()
        items=[]
        for row in rows:
            item=dict(row); item["details"]=json.loads(item["details"]); items.append(item)
        return items

    DATA_TABLES=("events","analyses","drafts","reviews","knowledge","documents","document_chunks","event_files")

    def data_counts(self)->dict[str,int]:
        with self.connect() as c:
            counts={name:c.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in self.DATA_TABLES}
            counts["audit_entries"]=c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
        return counts

    def metadata(self,key:str)->str|None:
        with self.connect() as c:
            row=c.execute("SELECT value FROM repository_metadata WHERE key=?",(key,)).fetchone()
        return row[0] if row else None

    def pending_reset(self)->dict|None:
        value=self.metadata("reset_pending")
        return json.loads(value) if value else None

    def begin_reset(self,receipt:dict)->None:
        """Commit an empty catalog plus a durable cleanup intent atomically."""
        with self.connect() as c:
            c.execute("PRAGMA secure_delete=ON")
            c.execute("BEGIN IMMEDIATE")
            for table in (*self.DATA_TABLES,"deleted_documents","audit"):
                c.execute(f"DELETE FROM {table}")
            c.execute("DELETE FROM repository_metadata WHERE key<>'embedding_fingerprint'")
            c.execute("INSERT INTO repository_metadata VALUES('reset_pending',?)",(json.dumps(receipt),))

    def finish_reset(self,receipt:dict)->None:
        # There is deliberately no filename, procedure text, event payload or
        # reviewer identity in the one surviving receipt.
        # Compact while the pending marker still exists: an interrupted cleanup
        # can safely be resumed and must never be reported as complete.
        with self.connect() as c:
            c.execute("VACUUM")
            if c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise RuntimeError("Repository checkpoint is busy; retry reset")
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM audit")
            c.execute("INSERT INTO audit(timestamp,action,entity_type,entity_id,details) VALUES(?,?,?,?,?)",(
                receipt["timestamp"],"reset","system",receipt["reset_id"],json.dumps({"removed":receipt["removed"]}),
            ))
            c.execute("DELETE FROM repository_metadata WHERE key='reset_pending'")
            c.execute("INSERT OR REPLACE INTO repository_metadata VALUES('reset_generation',?)",(receipt["reset_id"],))
