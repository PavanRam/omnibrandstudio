from __future__ import annotations

from typing import Any

import anyio

from services.rag.embeddings import embed_texts
from services.rag.vector_store import SearchResult, VectorPoint


class PineconeVectorStore:
    """Pinecone-backed adapter using namespace-per-brand tenancy."""

    def __init__(self, api_key: str, environment: str, index_name: str) -> None:
        self._api_key = api_key
        self._environment = environment
        self._index_name = index_name
        self._index = None

    def _get_index(self):
        if self._index is not None:
            return self._index

        if not self._api_key:
            raise RuntimeError("PINECONE_API_KEY is required when VECTOR_STORE_BACKEND=pinecone")

        try:
            from pinecone import Pinecone
        except Exception as exc:
            raise RuntimeError("pinecone package is not installed; run 'uv sync'") from exc

        client = Pinecone(api_key=self._api_key)
        self._index = client.Index(self._index_name)
        return self._index

    @staticmethod
    def _namespace(filters: dict[str, Any]) -> str:
        brand_id = str(filters.get("brand_id", "")).strip()
        if not brand_id:
            raise RuntimeError("brand_id filter is required for Pinecone namespace isolation")
        return brand_id

    async def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        if not points:
            return

        namespace = self._namespace(points[0].metadata)

        def _sync_upsert() -> None:
            index = self._get_index()
            vectors = [
                {
                    "id": p.id,
                    "values": p.vector,
                    "metadata": {**p.metadata, "text": p.text, "collection": collection},
                }
                for p in points
            ]
            index.upsert(vectors=vectors, namespace=namespace)

        await anyio.to_thread.run_sync(_sync_upsert)

    async def query(
        self,
        collection: str,
        query_text: str,
        filters: dict[str, Any],
        n_results: int,
    ) -> list[SearchResult]:
        namespace = self._namespace(filters)
        vector = (await embed_texts([query_text]))[0]

        pinecone_filter = {
            k: v for k, v in filters.items() if k != "brand_id"
        }
        pinecone_filter["collection"] = collection

        def _sync_query() -> list[SearchResult]:
            index = self._get_index()
            response = index.query(
                vector=vector,
                top_k=n_results,
                namespace=namespace,
                include_metadata=True,
                filter=pinecone_filter or None,
            )
            out: list[SearchResult] = []
            matches = getattr(response, "matches", [])
            for match in matches:
                metadata = dict(getattr(match, "metadata", {}) or {})
                out.append(
                    SearchResult(
                        id=str(getattr(match, "id", "")),
                        text=str(metadata.get("text", "")),
                        score=float(getattr(match, "score", 0.0)),
                        metadata=metadata,
                    )
                )
            return out

        return await anyio.to_thread.run_sync(_sync_query)

    async def delete_by_filter(self, collection: str, filters: dict[str, Any]) -> None:
        namespace = self._namespace(filters)
        pinecone_filter = {
            k: v for k, v in filters.items() if k != "brand_id"
        }
        pinecone_filter["collection"] = collection

        def _sync_delete() -> None:
            index = self._get_index()
            index.delete(filter=pinecone_filter or None, namespace=namespace)

        await anyio.to_thread.run_sync(_sync_delete)

    async def get_documents(
        self,
        collection: str,
        filters: dict[str, Any],
        limit: int | None = None,
    ) -> list[SearchResult]:
        # Pinecone does not provide an efficient full namespace scan for this
        # usage pattern. Retriever falls back to vector-candidate lexical merge
        # when corpus-wide BM25 documents are unavailable.
        return []
