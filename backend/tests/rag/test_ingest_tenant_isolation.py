from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from services.rag import ingest as ingest_mod
from services.rag.vector_store import VectorPoint


@dataclass
class _FakeVectorStore:
    upserts: list[tuple[str, list[VectorPoint]]] = field(default_factory=list)
    deletes: list[tuple[str, dict]] = field(default_factory=list)

    async def upsert(self, collection: str, points: list[VectorPoint]) -> None:
        self.upserts.append((collection, points))

    async def delete_by_filter(self, collection: str, filters: dict) -> None:
        self.deletes.append((collection, filters))

    async def get_documents(self, collection: str, filters: dict, limit: int | None = None):
        _ = collection, filters, limit
        return []


@dataclass
class _FakeDB:
    calls: list[tuple[str, dict]] = field(default_factory=list)
    committed: bool = False

    async def exec_driver_sql(self, query: str, params: dict) -> None:
        self.calls.append((query, params))

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_ingest_brand_guide_scopes_collection_metadata_and_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_store = _FakeVectorStore()
    fake_db = _FakeDB()

    monkeypatch.setattr(ingest_mod, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(ingest_mod, "chunk_text", lambda text: ["chunk-1", "chunk-2"])

    async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [[0.1] for _ in texts]

    monkeypatch.setattr(ingest_mod, "embed_texts", _fake_embed_texts)

    result = await ingest_mod.ingest_brand_guide(
        db=fake_db,
        brand_id="brand-a",
        file_bytes=b"Brand guide content",
        filename="guide.md",
        locale="en-US",
        version="v1",
    )

    assert result["collection"] == "brand_brand-a_guidelines"
    assert result["brand_id"] == "brand-a"
    assert result["locale"] == "en-US"
    assert fake_db.committed is True

    assert len(fake_store.upserts) == 1
    collection, points = fake_store.upserts[0]
    assert collection == "brand_brand-a_guidelines"
    assert len(points) == 2
    for point in points:
        assert point.metadata["brand_id"] == "brand-a"
        assert point.metadata["locale"] == "en-US"
        assert point.metadata["active"] is True
        assert point.metadata["content_type"] == "brand_guide"
        assert point.id.startswith("brand-a:guidelines:en-US:v1:")

    assert len(fake_db.calls) == 2
    update_query, update_params = fake_db.calls[0]
    assert "UPDATE brand_guides SET active = FALSE" in update_query
    assert "WHERE brand_id = %(brand_id)s AND locale = %(locale)s" in update_query
    assert update_params == {"brand_id": "brand-a", "locale": "en-US"}


@pytest.mark.asyncio
async def test_ingest_seed_datasets_scopes_all_collections_by_brand(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_store = _FakeVectorStore()
    fake_db = _FakeDB()

    monkeypatch.setattr(ingest_mod, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(ingest_mod, "chunk_text", lambda text: [text])

    async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [[0.2] for _ in texts]

    monkeypatch.setattr(ingest_mod, "embed_texts", _fake_embed_texts)

    guidelines_dir = tmp_path / "brand_guidelines"
    guidelines_dir.mkdir(parents=True, exist_ok=True)
    (guidelines_dir / "tone.json").write_text('{"voice": "clear"}', encoding="utf-8")

    (tmp_path / "customer_segments.csv").write_text("segment,size\nSMB,120\n", encoding="utf-8")
    (tmp_path / "campaigns_clean.csv").write_text("name,ctr\nLaunch,0.12\n", encoding="utf-8")
    (tmp_path / "sentiment140_clean.csv").write_text("text,label\nGreat,positive\n", encoding="utf-8")

    counts = await ingest_mod.ingest_seed_datasets(
        db=fake_db,
        seed_dir=tmp_path,
        brand_id="brand-a",
        locale="en-US",
        version="seed-v1",
    )

    assert fake_db.committed is True
    assert counts["guidelines"] >= 1
    assert counts["segments"] >= 1
    assert counts["campaigns"] >= 1
    assert counts["sentiment"] >= 1

    collections = [c for c, _ in fake_store.upserts]
    assert "brand_brand-a_guidelines" in collections
    assert "brand_brand-a_segments" in collections
    assert "brand_brand-a_campaigns" in collections
    assert "brand_brand-a_sentiment" in collections

    for _, points in fake_store.upserts:
        for point in points:
            assert point.metadata["brand_id"] == "brand-a"
            assert point.metadata["locale"] == "en-US"
            assert point.metadata["active"] is True


@pytest.mark.asyncio
async def test_ingest_customer_segments_scopes_segments_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_store = _FakeVectorStore()

    monkeypatch.setattr(ingest_mod, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(ingest_mod, "chunk_text", lambda text: [text])

    async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [[0.3] for _ in texts]

    monkeypatch.setattr(ingest_mod, "embed_texts", _fake_embed_texts)

    content = "segment,size\nSMB,120\nEnterprise,20\n".encode("utf-8")
    result = await ingest_mod.ingest_customer_segments(
        brand_id="brand-a",
        file_bytes=content,
        filename="segments.csv",
        locale="en-US",
        version="v1",
    )

    assert result["collection"] == "brand_brand-a_segments"
    assert result["records_indexed"] == 2
    assert len(fake_store.deletes) == 1
    assert fake_store.deletes[0][0] == "brand_brand-a_segments"

    assert len(fake_store.upserts) == 1
    _, points = fake_store.upserts[0]
    for point in points:
        assert point.metadata["brand_id"] == "brand-a"
        assert point.metadata["locale"] == "en-US"
        assert point.metadata["content_type"] == "segment_profile"
