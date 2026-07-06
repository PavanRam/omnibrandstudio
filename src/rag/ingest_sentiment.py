import chromadb
import pandas as pd

from src.data.loaders import load_csv
from src.rag.config import BATCH_SIZE, CHROMA_PATH, COLLECTION_SENTIMENT, DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("rag.ingest_sentiment")


def _doc_id(tweet_id: int) -> str:
    return f"si_{tweet_id}"


def ingest_sentiment() -> int:
    df = load_csv(DATA_DIR / "sentiment140_clean.csv")
    df = df.dropna(subset=["text_clean"])
    df = df[df["text_clean"].str.strip() != ""]
    logger.info(f"Loaded {len(df)} rows from sentiment140_clean.csv")

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_SENTIMENT,
        metadata={"hnsw:space": "cosine"},
    )

    total = 0
    for start in range(0, len(df), BATCH_SIZE):
        batch = df.iloc[start : start + BATCH_SIZE]
        docs, metas, ids = [], [], []

        for _, row in batch.iterrows():
            docs.append(str(row["text_clean"]))
            metas.append({
                "source": "sentiment140_clean.csv",
                "tweet_id": int(row["id"]),
                "sentiment_label": str(row["sentiment_label"]),
                "sentiment_binary": int(row["sentiment_binary"]),
                "year": int(row["year"]),
                "month": int(row["month"]),
                "has_mention": int(row["has_mention"]),
                "has_hashtag": int(row["has_hashtag"]),
                "word_count": int(row["word_count"]),
                "content_type": "customer_feedback",
            })
            ids.append(_doc_id(int(row["id"])))

        collection.upsert(documents=docs, metadatas=metas, ids=ids)
        total += len(docs)

        if start % 5000 == 0 and start > 0:
            logger.info(f"Progress: {total}/{len(df)} tweets upserted")

    logger.info(f"sentiment_insights: upserted {total} documents into ChromaDB")
    return total


if __name__ == "__main__":
    count = ingest_sentiment()
    print(f"Done. {count} documents in sentiment_insights collection.")
