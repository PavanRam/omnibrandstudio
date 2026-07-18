from __future__ import annotations

import asyncio
import json
from pathlib import Path

from services.rag import get_vector_store

BRAND_ID = "00000000-0000-0000-0000-000000000002"
VERSION = "datasets-v1"


async def main() -> None:
    store = get_vector_store()
    kinds = ["guidelines", "segments", "campaigns", "sentiment"]
    output: dict[str, dict[str, int | str]] = {}

    for kind in kinds:
        collection = f"brand_{BRAND_ID}_{kind}"
        docs = await store.get_documents(collection, {"brand_id": BRAND_ID}, limit=50000)
        version_docs = [d for d in docs if str(d.metadata.get("version", "")) == VERSION]
        output[kind] = {
            "collection": collection,
            "total_docs": len(docs),
            "version_docs": len(version_docs),
        }

    artifact = Path(__file__).resolve().parents[2] / "docs" / "rag-ingest-verification.json"
    artifact.write_text(json.dumps(output, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
