import hashlib

import chromadb
import pandas as pd

from src.data.loaders import load_csv
from src.rag.config import BATCH_SIZE, CHROMA_PATH, COLLECTION_CAMPAIGNS, DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("rag.ingest_campaigns")


def _campaign_doc_id(customer_id: int) -> str:
    return f"cp_cmp_{customer_id}"


def _ad_doc_id(text: str) -> str:
    # Campaign_ID is not unique in the dataset — use content hash instead
    return "cp_sma_" + hashlib.md5(text.encode()).hexdigest()[:16]


def _campaign_row_to_text(row: pd.Series) -> str:
    return (
        f"Customer {int(row['ID'])}: age {int(row['age'])}, "
        f"{row['education_level']} education, {row['Marital_Status']}, "
        f"income ${float(row['Income']):,.0f}. "
        f"Total spend ${float(row['total_spend']):,.0f}. "
        f"Channel: {row['dominant_channel']}. "
        f"Campaign type: {row['campaign_type']}. "
        f"Engagement rate: {float(row['engagement_rate']):.2f}. "
        f"{int(row['campaign_acceptance_count'])} campaigns accepted. "
        f"Web purchases: {int(row['NumWebPurchases'])}, "
        f"catalog: {int(row['NumCatalogPurchases'])}, "
        f"store: {int(row['NumStorePurchases'])}. "
        f"Tenure: {int(row['tenure_days'])} days."
    )


def _ad_row_to_text(row: pd.Series) -> str:
    return (
        f"{row['Channel_Used']} campaign for {row['Campaign_Goal']} "
        f"targeting {row['Customer_Segment']} segment, {row['Target_Audience']}. "
        f"CTR: {float(row['ctr']):.1%}. "
        f"Conversion rate: {float(row['Conversion_Rate']):.1%}. "
        f"ROI: {float(row['ROI']):.2f}. "
        f"Engagement score: {int(row['Engagement_Score'])} ({row['engagement_tier']} tier). "
        f"Cost per click: ${float(row['cost_per_click']):.2f}. "
        f"Duration: {int(row['duration_days'])} days. "
        f"Location: {row['Location']}. Language: {row['Language']}. "
        f"Company: {row['Company']}."
    )


def ingest_campaign_data() -> int:
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_CAMPAIGNS,
        metadata={"hnsw:space": "cosine"},
    )

    total = 0

    # campaigns_clean.csv
    df_cmp = load_csv(DATA_DIR / "campaigns_clean.csv")
    logger.info(f"Loaded {len(df_cmp)} rows from campaigns_clean.csv")

    for start in range(0, len(df_cmp), BATCH_SIZE):
        batch = df_cmp.iloc[start : start + BATCH_SIZE]
        docs, metas, ids = [], [], []

        for _, row in batch.iterrows():
            docs.append(_campaign_row_to_text(row))
            metas.append({
                "source": "campaigns_clean.csv",
                "customer_id": int(row["ID"]),
                "channel": str(row["dominant_channel"]),
                "campaign_type": str(row["campaign_type"]),
                "content_type": "campaign_record",
            })
            ids.append(_campaign_doc_id(int(row["ID"])))

        collection.upsert(documents=docs, metadatas=metas, ids=ids)
        total += len(docs)

    logger.info(f"Upserted {total} campaign records from campaigns_clean.csv")

    # social_media_ads_clean.csv
    df_ads = load_csv(DATA_DIR / "social_media_ads_clean.csv")
    logger.info(f"Loaded {len(df_ads)} rows from social_media_ads_clean.csv")

    for start in range(0, len(df_ads), BATCH_SIZE):
        batch = df_ads.iloc[start : start + BATCH_SIZE]
        docs, metas, ids = [], [], []

        for _, row in batch.iterrows():
            text = _ad_row_to_text(row)
            docs.append(text)
            metas.append({
                "source": "social_media_ads_clean.csv",
                "campaign_id": int(row["Campaign_ID"]),
                "channel": str(row["Channel_Used"]),
                "goal": str(row["Campaign_Goal"]),
                "segment": str(row["Customer_Segment"]),
                "engagement_tier": str(row["engagement_tier"]),
                "language": str(row["Language"]),
                "content_type": "ad_performance",
            })
            ids.append(_ad_doc_id(text))

        collection.upsert(documents=docs, metadatas=metas, ids=ids)
        total += len(docs)

    logger.info(f"campaign_performance: upserted {total} total documents into ChromaDB")
    return total


if __name__ == "__main__":
    count = ingest_campaign_data()
    print(f"Done. {count} documents in campaign_performance collection.")
