from __future__ import annotations

from typing import Any

import anyio

from services.rag.embeddings import embed_texts
from services.rag.vector_store import SearchResult, VectorPoint


class ChromaVectorStore:
    """Chroma-backed vector store with brand-filtered query semantics."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import chromadb
            except Exception as exc:
                raise RuntimeError(
                    "chromadb is not installed; run 'uv sync' after updating dependencies"
                ) from exc
            self._client = chromadb.PersistentClient(path=self._path)
        return self._client

    def _get_collection(self, collection: str):
        client = self._get_client()
        return client.get_or_create_collection(collection)

    @staticmethod
    def _build_where(filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None
        if len(filters) == 1:
            return filters
        return {"$and": [{k: {"$eq": v}} for k, v in filters.items()]}

    async def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        if not points:
            return

        def _sync_upsert() -> None:
            col = self._get_collection(collection)
            col.upsert(
                ids=[p.id for p in points],
                embeddings=[p.vector for p in points],
                documents=[p.text for p in points],
                metadatas=[p.metadata for p in points],
            )

        await anyio.to_thread.run_sync(_sync_upsert)

    async def query(
        self,
        collection: str,
        query_text: str,
        filters: dict[str, Any],
        n_results: int,
    ) -> list[SearchResult]:
        query_vec = (await embed_texts([query_text]))[0]

        def _sync_query() -> list[SearchResult]:
            col = self._get_collection(collection)
            raw = col.query(
                query_embeddings=[query_vec],
                n_results=n_results,
                where=self._build_where(filters),
            )
            ids = raw.get("ids", [[]])[0]
            docs = raw.get("documents", [[]])[0]
            dists = raw.get("distances", [[]])[0]
            metas = raw.get("metadatas", [[]])[0]

            out: list[SearchResult] = []
            for i, doc, dist, meta in zip(ids, docs, dists, metas, strict=False):
                # Smaller distance means better match; convert to score-like signal.
                out.append(
                    SearchResult(
                        id=str(i),
                        text=str(doc),
                        score=1.0 / (1.0 + float(dist)),
                        metadata=dict(meta or {}),
                    )
                )
            return out

        return await anyio.to_thread.run_sync(_sync_query)

    async def delete_by_filter(self, collection: str, filters: dict[str, Any]) -> None:
        def _sync_delete() -> None:
            col = self._get_collection(collection)
            col.delete(where=self._build_where(filters))

        await anyio.to_thread.run_sync(_sync_delete)

    async def get_documents(
        self,
        collection: str,
        filters: dict[str, Any],
        limit: int | None = None,
    ) -> list[SearchResult]:
        def _sync_get() -> list[SearchResult]:
            col = self._get_collection(collection)
            query_args = {
                "where": self._build_where(filters),
                "include": ["documents", "metadatas"],
            }
            if limit is not None:
                query_args["limit"] = limit
            raw = col.get(**query_args)
            ids = raw.get("ids", [])
            docs = raw.get("documents", [])
            metas = raw.get("metadatas", [])

            out: list[SearchResult] = []
            for i, doc, meta in zip(ids, docs, metas, strict=False):
                out.append(
                    SearchResult(
                        id=str(i),
                        text=str(doc),
                        score=0.0,
                        metadata=dict(meta or {}),
                    )
                )
                if limit is not None and len(out) >= limit:
                    break
            return out

        return await anyio.to_thread.run_sync(_sync_get)
