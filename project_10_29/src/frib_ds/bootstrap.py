from functools import lru_cache
from datetime import datetime,timezone
import uuid
from frib_ds.config import get_config
from frib_ds.storage.sqlite import SQLiteRepository
from frib_ds.storage.files import EventFileStore
from frib_ds.storage.documents import DocumentStore
from frib_ds.storage.reset import DataLifecycleLock,owned_store_inventory,clear_owned_stores,legacy_index_inventory,clear_legacy_indexes
from frib_ds.generator.registry import GeneratorRegistry
from frib_ds.processing.registry import ProcessorRegistry
from frib_ds.rag.embeddings import build_embedding_provider
from frib_ds.rag.vector_store import build_vector_store
from frib_ds.rag.llm import build_llm_provider
from frib_ds.rag.service import RAGService
from frib_ds.knowledge.service import KnowledgeService

def embedding_fingerprint(config:dict)->dict:
    provider=config.get("provider","hash")
    if provider=="hash":
        return {"provider":"hash","dimensions":int(config.get("dimensions",384)),"tokenizer_version":2}
    return {"provider":provider,"model":config.get("model","all-MiniLM-L6-v2")}

class Services:
    def __init__(self):
        c=get_config(); self.config=c
        self.repo=SQLiteRepository(c.database_path); self.files=EventFileStore(c.event_dir); self.generators=GeneratorRegistry(); self.processors=ProcessorRegistry()
        self.repo.ensure_embedding_compatibility(embedding_fingerprint(c.models.get("embeddings",{})))
        self.embedding=build_embedding_provider(c.models.get("embeddings",{}))
        vcfg=dict(c.models.get("vector_store",{})); vcfg["persist_dir"]=str(c.chroma_dir)
        self.vector=build_vector_store(vcfg,str(c.chroma_dir)); self.llm=build_llm_provider(c.models.get("llm",{}))
        self.documents=DocumentStore(c.data_dir/"documents",self.repo,self.embedding,self.vector,c.rag)
        # Complete a previously committed reset before hydrating any procedure.
        # The same process-safe lock wraps API data requests and full downloads.
        with DataLifecycleLock(c.data_dir):
            pending=self.repo.pending_reset()
            if pending: self._finish_reset(pending)
            self.documents.hydrate()
            self.reset_generation=self.repo.metadata("reset_generation")
        self.rag=RAGService(self.embedding,self.vector,self.llm,c.rag,c.prompts_dir)
        self.knowledge=KnowledgeService(self.repo,self.llm,c.prompts_dir,self.files)

    def data_status(self)->dict:
        stored,_=owned_store_inventory(self.config,self.files,self.documents)
        legacy,_=legacy_index_inventory(self.config,self.vector)
        counts=self.repo.data_counts()
        counts.update(stored_files=len(stored)+len(legacy),legacy_index_files=len(legacy),retrieval_vectors=self.vector.count())
        return {"counts":counts,"reset_pending":bool(self.repo.pending_reset()),
                "preserved":["application configuration","embedding configuration","source code","sample data","logs"],
                "audit_policy":"Uploaded content and old audits are deleted; one minimal reset receipt remains."}

    def refresh_data_state(self)->bool:
        """Prevent stale in-memory retrieval in a second API worker after reset."""
        if self.repo.pending_reset(): return False
        generation=self.repo.metadata("reset_generation")
        if generation!=self.reset_generation:
            self.vector.clear()
            self.documents.hydrate()
            self.reset_generation=generation
        return True

    def _finish_reset(self,receipt:dict)->None:
        # Recheck every filesystem target before modifying the external index.
        owned_store_inventory(self.config,self.files,self.documents)
        legacy_index_inventory(self.config,self.vector)
        self.vector.clear()
        clear_owned_stores(self.config,self.files,self.documents)
        clear_legacy_indexes(self.config,self.vector)
        if self.vector.count(): raise RuntimeError("Retrieval index cleanup is incomplete")
        if owned_store_inventory(self.config,self.files,self.documents)[0]:
            raise RuntimeError("Stored file cleanup is incomplete")
        self.repo.finish_reset(receipt)
        self.reset_generation=receipt["reset_id"]

    def reset_data(self)->dict:
        """Called while the API lifecycle lock excludes all content requests."""
        # Complete preflight before removing catalog records. A junction, symlink
        # or redirected store must leave all current records untouched.
        owned_store_inventory(self.config,self.files,self.documents)
        legacy_index_inventory(self.config,self.vector)
        receipt=self.repo.pending_reset()
        if not receipt:
            receipt={"reset_id":f"RESET-{uuid.uuid4().hex}",
                     "timestamp":datetime.now(timezone.utc).isoformat(),
                     "removed":self.data_status()["counts"]}
            self.repo.begin_reset(receipt)
        self._finish_reset(receipt)
        return {"reset":True,**receipt,"remaining":self.data_status()["counts"]}

@lru_cache(maxsize=1)
def get_services(): return Services()
