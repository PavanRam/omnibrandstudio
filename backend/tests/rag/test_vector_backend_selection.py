from __future__ import annotations

import pytest

import services.rag as rag
from core.config import settings


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    rag._vector_store = None
    rag._retriever = None


def test_selects_chroma_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, str] = {}

    class _DummyChroma:
        def __init__(self, path: str) -> None:
            created["path"] = path

    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "chroma")
    monkeypatch.setattr(settings, "CHROMA_PERSIST_PATH", "/tmp/chroma-test")
    monkeypatch.setattr(rag, "ChromaVectorStore", _DummyChroma)

    store = rag.get_vector_store()

    assert isinstance(store, _DummyChroma)
    assert created["path"] == "/tmp/chroma-test"


def test_selects_pinecone_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, str] = {}

    class _DummyPinecone:
        def __init__(self, api_key: str, environment: str, index_name: str) -> None:
            created["api_key"] = api_key
            created["environment"] = environment
            created["index_name"] = index_name

    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "pinecone")
    monkeypatch.setattr(settings, "PINECONE_API_KEY", "key")
    monkeypatch.setattr(settings, "PINECONE_ENVIRONMENT", "env")
    monkeypatch.setattr(settings, "PINECONE_INDEX", "idx")
    monkeypatch.setattr(rag, "PineconeVectorStore", _DummyPinecone)

    store = rag.get_vector_store()

    assert isinstance(store, _DummyPinecone)
    assert created == {"api_key": "key", "environment": "env", "index_name": "idx"}


def test_invalid_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "VECTOR_STORE_BACKEND", "unknown")

    with pytest.raises(ValueError, match="Invalid VECTOR_STORE_BACKEND"):
        rag.get_vector_store()
