from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class VectorPoint:
    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStoreAdapter(Protocol):
    async def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        ...

    async def query(
        self,
        collection: str,
        query_text: str,
        filters: dict[str, Any],
        n_results: int,
    ) -> list[SearchResult]:
        ...

    async def delete_by_filter(self, collection: str, filters: dict[str, Any]) -> None:
        ...

    async def get_documents(
        self,
        collection: str,
        filters: dict[str, Any],
        limit: int | None = None,
    ) -> list[SearchResult]:
        ...
