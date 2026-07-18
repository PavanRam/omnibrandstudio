from __future__ import annotations

from core.config import settings
from services.rag.chroma_store import ChromaVectorStore
from services.rag.pinecone_store import PineconeVectorStore
from services.rag.retriever import RAGRetriever
from services.rag.vector_store import VectorStoreAdapter

_vector_store: VectorStoreAdapter | None = None
_retriever: RAGRetriever | None = None


def get_vector_store() -> VectorStoreAdapter:
    """Return a cached vector-store adapter selected by runtime config."""
    global _vector_store
    if _vector_store is not None:
        return _vector_store

    backend = settings.VECTOR_STORE_BACKEND.strip().lower()
    if backend == "pinecone":
        _vector_store = PineconeVectorStore(
            api_key=settings.PINECONE_API_KEY,
            environment=settings.PINECONE_ENVIRONMENT,
            index_name=settings.PINECONE_INDEX,
        )
    else:
        _vector_store = ChromaVectorStore(path=settings.CHROMA_PERSIST_PATH)
    return _vector_store


def get_retriever() -> RAGRetriever:
    """Return a cached retriever wired to the configured vector backend."""
    global _retriever
    if _retriever is None:
        _retriever = RAGRetriever(store=get_vector_store())
    return _retriever