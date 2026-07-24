from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
from uuid import uuid4

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncConnection
import structlog

from core.config import settings
from services.rag import get_vector_store
from services.rag.chunking import chunk_text
from services.rag.embeddings import embed_texts
from services.rag.vector_store import VectorPoint

log = structlog.get_logger()

_BLOCK_PATTERNS = [
    re.compile(r"ignore\s+previous\s+instructions", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
]


def _collection_name(brand_id: str, kind: str) -> str:
    return f"brand_{brand_id}_{kind}"


def _sanitize_text(raw: str) -> str:
    text = raw.replace("\x00", " ").strip()
    for pattern in _BLOCK_PATTERNS:
        if pattern.search(text):
            raise ValueError("Potential prompt-injection text detected in uploaded content")
    return text


def _extract_text(file_bytes: bytes, filename: str) -> str:
    lower_name = filename.lower()
    if lower_name.endswith((".txt", ".md")):
        return file_bytes.decode("utf-8", errors="replace")

    if lower_name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise RuntimeError("pypdf is required for PDF ingestion") from exc

        reader = PdfReader(BytesIO(file_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)

    if lower_name.endswith(".docx"):
        try:
            import docx
        except Exception as exc:
            raise RuntimeError("python-docx is required for DOCX ingestion") from exc

        document = docx.Document(BytesIO(file_bytes))
        return "\n".join(p.text for p in document.paragraphs)

    raise ValueError("Unsupported guide format; allowed: .txt, .md, .pdf, .docx")


def _build_points(
    *,
    brand_id: str,
    locale: str,
    version: str,
    kind: str,
    records: list[dict],
) -> list[VectorPoint]:
    points: list[VectorPoint] = []
    for idx, record in enumerate(records):
        text = _sanitize_text(str(record.get("text", "")))
        if not text:
            continue
        chunks = chunk_text(text)
        for cidx, chunk in enumerate(chunks):
            points.append(
                VectorPoint(
                    id=f"{brand_id}:{kind}:{locale}:{version}:{idx}:{cidx}:{uuid4().hex[:8]}",
                    text=chunk,
                    vector=[],
                    metadata={
                        "brand_id": brand_id,
                        "locale": locale,
                        "version": version,
                        "active": True,
                        "section_type": str(record.get("section_type", kind)),
                        "content_type": str(record.get("content_type", kind)),
                        **{k: v for k, v in record.items() if k not in {"text"}},
                    },
                )
            )
    return points


async def _embed_points(points: list[VectorPoint]) -> list[VectorPoint]:
    if not points:
        return points
    vectors = await embed_texts([p.text for p in points])
    for p, v in zip(points, vectors, strict=False):
        p.vector = v
    return points


async def ingest_brand_guide(
    *,
    db: AsyncConnection,
    brand_id: str,
    file_bytes: bytes,
    filename: str,
    locale: str,
    version: str,
) -> dict:
    if len(file_bytes) > settings.RAG_MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded guide exceeds maximum allowed size")

    raw_text = _extract_text(file_bytes, filename)
    text = _sanitize_text(raw_text)
    chunks = chunk_text(text)
    if not chunks:
        raise ValueError("No extractable text content found in uploaded guide")

    points = [
        VectorPoint(
            id=f"{brand_id}:guidelines:{locale}:{version}:{idx}:{uuid4().hex[:8]}",
            text=chunk,
            vector=[],
            metadata={
                "brand_id": brand_id,
                "locale": locale,
                "version": version,
                "active": True,
                "section_type": "guide",
                "content_type": "brand_guide",
            },
        )
        for idx, chunk in enumerate(chunks)
    ]
    points = await _embed_points(points)

    await get_vector_store().upsert(collection=_collection_name(brand_id, "guidelines"), points=points)

    await db.exec_driver_sql(
        "UPDATE brand_guides SET active = FALSE WHERE brand_id = %(brand_id)s AND locale = %(locale)s AND active = TRUE",
        {"brand_id": brand_id, "locale": locale},
    )
    await db.exec_driver_sql(
        "INSERT INTO brand_guides (brand_id, locale, version, source_filename, indexed_at, active, chunk_count) "
        "VALUES (%(brand_id)s, %(locale)s, %(version)s, %(source_filename)s, NOW(), TRUE, %(chunk_count)s)",
        {
            "brand_id": brand_id,
            "locale": locale,
            "version": version,
            "source_filename": filename,
            "chunk_count": len(points),
        },
    )
    await db.commit()

    return {
        "brand_id": brand_id,
        "locale": locale,
        "version": version,
        "chunks_indexed": len(points),
        "collection": _collection_name(brand_id, "guidelines"),
    }


def _segment_records_from_csv_bytes(file_bytes: bytes, filename: str) -> list[dict]:
    df = pd.read_csv(BytesIO(file_bytes))
    out: list[dict] = []
    for idx, row in df.iterrows():
        row_map = {k: (v.item() if hasattr(v, "item") else v) for k, v in row.to_dict().items()}
        text = " ".join(f"{k}: {v}" for k, v in row_map.items())
        out.append(
            {
                "text": text,
                "section_type": "segments",
                "content_type": "segment_profile",
                "source": filename,
                "row_index": int(idx),
                **row_map,
            }
        )
    return out


def _segment_records_from_json_bytes(file_bytes: bytes, filename: str) -> list[dict]:
    payload = json.loads(file_bytes.decode("utf-8", errors="replace"))
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        raise ValueError("Segment JSON must be an object or list of objects")

    out: list[dict] = []
    for idx, row in enumerate(payload):
        if not isinstance(row, dict):
            continue
        text = " ".join(f"{k}: {v}" for k, v in row.items())
        out.append(
            {
                "text": text,
                "section_type": "segments",
                "content_type": "segment_profile",
                "source": filename,
                "row_index": int(idx),
                **row,
            }
        )
    return out


def _segment_records_from_text_bytes(file_bytes: bytes, filename: str) -> list[dict]:
    lines = [line.strip() for line in file_bytes.decode("utf-8", errors="replace").splitlines()]
    out: list[dict] = []
    for idx, line in enumerate(lines):
        if not line:
            continue
        out.append(
            {
                "text": line,
                "section_type": "segments",
                "content_type": "segment_profile",
                "source": filename,
                "row_index": int(idx),
                "segment": line,
            }
        )
    return out


def _segment_records_from_upload(file_bytes: bytes, filename: str) -> list[dict]:
    lower_name = filename.lower()
    if lower_name.endswith(".csv"):
        return _segment_records_from_csv_bytes(file_bytes, filename)
    if lower_name.endswith(".json"):
        return _segment_records_from_json_bytes(file_bytes, filename)
    if lower_name.endswith((".txt", ".md")):
        return _segment_records_from_text_bytes(file_bytes, filename)
    raise ValueError("Unsupported segment format; allowed: .csv, .json, .txt, .md")


async def ingest_customer_segments(
    *,
    brand_id: str,
    file_bytes: bytes,
    filename: str,
    locale: str,
    version: str,
) -> dict:
    if len(file_bytes) > settings.RAG_MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded segment file exceeds maximum allowed size")

    records = _segment_records_from_upload(file_bytes, filename)
    if not records:
        raise ValueError("No segment records found in upload")

    points = _build_points(
        brand_id=brand_id,
        locale=locale,
        version=version,
        kind="segments",
        records=records,
    )
    points = await _embed_points(points)

    collection = _collection_name(brand_id, "segments")
    store = get_vector_store()
    await store.delete_by_filter(
        collection,
        {
            "brand_id": brand_id,
            "locale": locale,
            "active": True,
            "content_type": "segment_profile",
        },
    )
    await store.upsert(collection=collection, points=points)

    return {
        "brand_id": brand_id,
        "locale": locale,
        "version": version,
        "records_indexed": len(records),
        "chunks_indexed": len(points),
        "collection": collection,
    }


async def list_customer_segments(
    *,
    brand_id: str,
    locale: str,
    version: str | None = None,
    limit: int = 50,
) -> list[dict]:
    filters: dict[str, object] = {
        "brand_id": brand_id,
        "locale": locale,
        "active": True,
        "content_type": "segment_profile",
    }
    if version:
        filters["version"] = version

    collection = _collection_name(brand_id, "segments")
    docs = await get_vector_store().get_documents(collection=collection, filters=filters, limit=limit)
    return [
        {
            "id": doc.id,
            "text": doc.text,
            "metadata": doc.metadata,
        }
        for doc in docs
    ]


def _guidelines_records_from_json(seed_dir: Path) -> list[dict]:
    records: list[dict] = []
    for path in sorted(seed_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key, val in data.items():
                text = json.dumps(val, ensure_ascii=False)
                records.append(
                    {
                        "text": f"{key}: {text}",
                        "section_type": key,
                        "content_type": path.stem,
                        "source": path.name,
                    }
                )
        elif isinstance(data, list):
            for idx, val in enumerate(data):
                text = json.dumps(val, ensure_ascii=False)
                records.append(
                    {
                        "text": text,
                        "section_type": path.stem,
                        "content_type": path.stem,
                        "source": path.name,
                        "row_index": idx,
                    }
                )
    return records


def _records_from_csv(csv_path: Path, kind: str) -> list[dict]:
    df = pd.read_csv(csv_path)
    out: list[dict] = []
    for idx, row in df.iterrows():
        row_map = {k: (v.item() if hasattr(v, "item") else v) for k, v in row.to_dict().items()}
        text = " ".join(f"{k}: {v}" for k, v in row_map.items())
        out.append(
            {
                "text": text,
                "section_type": kind,
                "content_type": kind,
                "source": csv_path.name,
                "row_index": int(idx),
                **row_map,
            }
        )
    return out


async def ingest_seed_datasets(
    *,
    db: AsyncConnection,
    seed_dir: Path,
    brand_id: str,
    locale: str,
    version: str,
) -> dict[str, int]:
    """Ingest del_branch-style datasets into brand-scoped collections.

    Supported directories/files:
    - brand_guidelines/*.json -> guidelines collection
    - customer_segments.csv -> segments collection
    - campaigns_clean.csv + social_media_ads_clean.csv -> campaigns collection
    - sentiment140_clean.csv -> sentiment collection
    """
    counts: dict[str, int] = {"guidelines": 0, "segments": 0, "campaigns": 0, "sentiment": 0}

    guidelines_dir = seed_dir / "brand_guidelines"
    if guidelines_dir.exists():
        records = _guidelines_records_from_json(guidelines_dir)
        points = _build_points(
            brand_id=brand_id,
            locale=locale,
            version=version,
            kind="guidelines",
            records=records,
        )
        points = await _embed_points(points)
        await get_vector_store().upsert(collection=_collection_name(brand_id, "guidelines"), points=points)
        counts["guidelines"] = len(points)

    segments_csv = seed_dir / "customer_segments.csv"
    if segments_csv.exists():
        records = _records_from_csv(segments_csv, "segments")
        points = _build_points(
            brand_id=brand_id,
            locale=locale,
            version=version,
            kind="segments",
            records=records,
        )
        points = await _embed_points(points)
        await get_vector_store().upsert(collection=_collection_name(brand_id, "segments"), points=points)
        counts["segments"] = len(points)

    campaign_files = [seed_dir / "campaigns_clean.csv", seed_dir / "social_media_ads_clean.csv"]
    campaign_records: list[dict] = []
    for p in campaign_files:
        if p.exists():
            campaign_records.extend(_records_from_csv(p, "campaigns"))
    if campaign_records:
        points = _build_points(
            brand_id=brand_id,
            locale=locale,
            version=version,
            kind="campaigns",
            records=campaign_records,
        )
        points = await _embed_points(points)
        await get_vector_store().upsert(collection=_collection_name(brand_id, "campaigns"), points=points)
        counts["campaigns"] = len(points)

    sentiment_csv = seed_dir / "sentiment140_clean.csv"
    if sentiment_csv.exists():
        records = _records_from_csv(sentiment_csv, "sentiment")
        points = _build_points(
            brand_id=brand_id,
            locale=locale,
            version=version,
            kind="sentiment",
            records=records,
        )
        points = await _embed_points(points)
        await get_vector_store().upsert(collection=_collection_name(brand_id, "sentiment"), points=points)
        counts["sentiment"] = len(points)

    await db.commit()
    log.info("seed_datasets_ingested", brand_id=brand_id, locale=locale, version=version, counts=counts)
    return counts
