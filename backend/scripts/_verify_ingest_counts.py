import asyncio
import json
from services.rag import get_vector_store

BRAND_ID = "00000000-0000-0000-0000-000000000002"
VERSION = "datasets-v1"

async def main():
    store = get_vector_store()
    collections = ["guidelines", "segments", "campaigns", "sentiment"]
    out = {}
    for kind in collections:
        collection = f"brand_{BRAND_ID}_{kind}"
        docs = await store.get_documents(collection, {"brand_id": BRAND_ID}, limit=50000)
        version_docs = [d for d in docs if str(d.metadata.get("version", "")) == VERSION]
        out[kind] = {
            "collection": collection,
            "total_docs": len(docs),
            "version_docs": len(version_docs),
        }
    with open("..\\docs\\rag-ingest-verification.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

asyncio.run(main())
