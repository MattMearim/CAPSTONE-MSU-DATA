from __future__ import annotations
from abc import ABC, abstractmethod
from contextlib import contextmanager
import json, sqlite3
import heapq
from pathlib import Path
import numpy as np
from pydantic_core import from_json
from frib_ds.models import DocumentChunk

class VectorStore(ABC):
    @abstractmethod
    def add(self,chunks:list[DocumentChunk],vectors:list[list[float]]): raise NotImplementedError
    @abstractmethod
    def search(self,vector:list[float],top_k:int=5)->list[tuple[DocumentChunk,float]]: raise NotImplementedError
    @abstractmethod
    def delete_document(self,document_id:str)->None: raise NotImplementedError
    @abstractmethod
    def clear(self)->None: raise NotImplementedError
    @abstractmethod
    def count(self)->int: raise NotImplementedError

class MemoryVectorStore(VectorStore):
    def __init__(self): self.rows=[]
    def add(self,chunks,vectors):
        ids={chunk.chunk_id for chunk in chunks}
        self.rows=[row for row in self.rows if row[0].chunk_id not in ids]
        self.rows.extend(zip(chunks,vectors))
    def delete_document(self,document_id):
        self.rows=[row for row in self.rows if row[0].document_id != document_id]
    def clear(self): self.rows=[]
    def count(self): return len(self.rows)
    def search(self,vector,top_k=5):
        q=np.asarray(vector,float); scores=[]
        for chunk,v in self.rows:
            a=np.asarray(v,float)
            if a.shape != q.shape: continue
            denom=np.linalg.norm(q)*np.linalg.norm(a); score=float(np.dot(q,a)/denom) if denom else 0.0
            scores.append((chunk,score))
        return sorted(scores,key=lambda x:x[1],reverse=True)[:top_k]

class SQLiteVectorStore(VectorStore):
    """Small persistent cosine index requiring no vector server or model download."""
    def __init__(self,path:str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS vectors(chunk_id TEXT PRIMARY KEY,document_id TEXT NOT NULL,payload TEXT NOT NULL,vector TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS vectors_document ON vectors(document_id)")
    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally: connection.close()
    def add(self,chunks,vectors):
        if len(chunks) != len(vectors): raise ValueError("Each document chunk requires one vector")
        with self.connect() as connection:
            connection.executemany("INSERT OR REPLACE INTO vectors VALUES(?,?,?,?)",[
                (chunk.chunk_id,chunk.document_id,chunk.model_dump_json(),json.dumps(vector)) for chunk,vector in zip(chunks,vectors)
            ])
    def delete_document(self,document_id):
        with self.connect() as connection:
            connection.execute("DELETE FROM vectors WHERE document_id=?",(document_id,))
    def clear(self):
        with self.connect() as connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("DELETE FROM vectors")
        # Remove unused database pages containing former retrieval payloads.
        with self.connect() as connection:
            connection.execute("VACUUM")
            if connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]:
                raise RuntimeError("Retrieval database checkpoint is busy; retry reset")
    def count(self):
        with self.connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM vectors").fetchone()[0]
    def search(self,vector,top_k=5):
        # Rank the stored vectors before decoding full procedure chunks. A query
        # needs only its best candidates, not a Pydantic object for every chunk
        # in the library. Read the current SQLite snapshot each time so another
        # worker's deletions and data resets remain immediately visible.
        query=np.asarray(vector,float)
        query_norm=np.linalg.norm(query)
        def scores(rows):
            for payload,values in rows:
                candidate=np.asarray(from_json(values),float)
                if candidate.shape != query.shape: continue
                denominator=query_norm*np.linalg.norm(candidate)
                score=float(np.dot(query,candidate)/denominator) if denominator else 0.0
                yield payload,score
        # nlargest retains input order for tied scores, matching the original
        # stable sort. Preserve ordinary slice behavior for direct callers that
        # pass a negative limit, though API retrieval always uses a positive one.
        # Stream SQLite rows into a bounded heap. A large procedure library
        # must not require every source payload and vector to coexist in RAM.
        with self.connect() as connection:
            scored=scores(connection.execute("SELECT payload,vector FROM vectors"))
            hits=heapq.nlargest(top_k,scored,key=lambda item:item[1]) if top_k>=0 else sorted(scored,key=lambda item:item[1],reverse=True)[:top_k]
        return [(DocumentChunk.model_validate_json(payload),score) for payload,score in hits]

class ChromaVectorStore(VectorStore):
    def __init__(self,persist_dir:str,collection_name:str):
        try: import chromadb
        except ImportError as e: raise RuntimeError("Install the 'rag' extra to use ChromaDB") from e
        self.client=chromadb.PersistentClient(path=persist_dir); self.collection=self.client.get_or_create_collection(collection_name,metadata={"hnsw:space":"cosine"})
    def add(self,chunks,vectors):
        if not chunks: return
        self.collection.upsert(ids=[c.chunk_id for c in chunks],embeddings=vectors,documents=[c.text for c in chunks],metadatas=[{"payload":c.model_dump_json(),"document_id":c.document_id} for c in chunks])
    def delete_document(self,document_id):
        # Scan payloads as well so indexes created by older versions are removable.
        result=self.collection.get(include=["metadatas"])
        ids=[]
        for chunk_id,meta in zip(result.get("ids",[]),result.get("metadatas",[])):
            if meta and (meta.get("document_id")==document_id or DocumentChunk.model_validate_json(meta["payload"]).document_id==document_id):
                ids.append(chunk_id)
        if ids: self.collection.delete(ids=ids)
    def clear(self):
        # Delete every entry in this application's collection, including orphan
        # entries without a catalog record. The configured persistence directory
        # is application-owned; old collection names must not resurrect uploads.
        if hasattr(self,"client"):
            active_name=self.collection.name
            for collection in self.client.list_collections():
                name=collection if isinstance(collection,str) else collection.name
                if name!=active_name: self.client.delete_collection(name=name)
        while True:
            ids=self.collection.get(limit=1000,include=[]).get("ids",[])
            if not ids: break
            before=self.collection.count()
            self.collection.delete(ids=ids)
            if self.collection.count()>=before:
                raise RuntimeError("Chroma cleanup did not remove the requested entries")
    def count(self): return self.collection.count()
    def search(self,vector,top_k=5):
        count=self.collection.count()
        if not count: return []
        r=self.collection.query(query_embeddings=[vector],n_results=min(top_k,count),include=["metadatas","distances"])
        out=[]
        for meta,dist in zip(r.get("metadatas",[[]])[0],r.get("distances",[[]])[0]):
            chunk=DocumentChunk.model_validate_json(meta["payload"]); score=1.0-float(dist); out.append((chunk,score))
        return out

def build_vector_store(config:dict,data_dir:str):
    p=config.get("provider","memory")
    if p=="memory": return MemoryVectorStore()
    if p=="sqlite": return SQLiteVectorStore(config.get("path",str(Path(data_dir)/"vectors.sqlite")))
    if p=="chroma": return ChromaVectorStore(config.get("persist_dir",data_dir),config.get("collection","frib_official_documents"))
    raise ValueError(f"Unknown vector store: {p}")
