"""
Run all four RAG ingestion pipelines in sequence.

Usage:
    venv\\Scripts\\python -m src.rag.run_ingestion
"""
import time

from src.rag.ingest_brand_guidelines import ingest_brand_guidelines
from src.rag.ingest_campaign_data import ingest_campaign_data
from src.rag.ingest_customer_segments import ingest_customer_segments
from src.rag.ingest_sentiment import ingest_sentiment
from src.utils.logger import get_logger

logger = get_logger("rag.run_ingestion")

PIPELINES = [
    ("brand_guidelines",     ingest_brand_guidelines),
    ("customer_segments",    ingest_customer_segments),
    ("campaign_performance", ingest_campaign_data),
    ("sentiment_insights",   ingest_sentiment),
]


def run_all() -> None:
    print("\n" + "=" * 57)
    print("  RAG Knowledge Base -- Full Ingestion")
    print("=" * 57)

    results: list[tuple[str, int, float]] = []
    overall_start = time.time()

    for name, fn in PIPELINES:
        print(f"\n[>>] Ingesting: {name}")
        t0 = time.time()
        try:
            count = fn()
            elapsed = time.time() - t0
            results.append((name, count, elapsed))
            print(f"     Done: {count:,} documents  ({elapsed:.1f}s)")
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error(f"{name} failed after {elapsed:.1f}s: {exc}", exc_info=True)
            print(f"     FAILED: {exc}")
            results.append((name, 0, elapsed))

    total_elapsed = time.time() - overall_start
    total_docs    = sum(r[1] for r in results)

    print("\n" + "=" * 57)
    print("  Summary")
    print("=" * 57)
    print(f"  {'Collection':<26} {'Docs':>7}  {'Time':>7}")
    print(f"  {'-'*26} {'-'*7}  {'-'*7}")
    for name, count, elapsed in results:
        print(f"  {name:<26} {count:>7,}  {elapsed:>6.1f}s")
    print(f"  {'-'*26} {'-'*7}  {'-'*7}")
    print(f"  {'TOTAL':<26} {total_docs:>7,}  {total_elapsed:>6.1f}s")
    print("=" * 57 + "\n")


if __name__ == "__main__":
    run_all()
