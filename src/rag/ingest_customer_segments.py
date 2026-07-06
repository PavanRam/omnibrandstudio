import chromadb
import pandas as pd

from src.data.loaders import load_csv
from src.rag.config import BATCH_SIZE, CHROMA_PATH, COLLECTION_SEGMENTS, DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("rag.ingest_segments")

EDU_LABELS = {0: "Basic", 1: "2N Cycle", 2: "Graduation", 3: "Master", 4: "PhD"}

# One summary document per persona — written in marketing vocabulary so that
# free-text audience descriptions (from CampaignBrief) match correctly via
# semantic search. These are upserted alongside the individual customer rows
# but tagged content_type=persona_summary to keep them separable.
_PERSONA_SUMMARIES = [
    (
        "persona_summary_high_income",
        "High-Income Store Spender",
        (
            "High-Income Store Spender: Affluent professional with high disposable income, "
            "aged 35-65, preferring premium and luxury brands. Shops predominantly in-store "
            "at upscale retail locations. Values quality, exclusivity, and brand prestige over "
            "price. Aspirational and sophisticated lifestyle. Responds to heritage, craftsmanship, "
            "and understated luxury messaging. High total spend across premium goods, wines, and "
            "gourmet products. Long brand tenure and strong loyalty."
        ),
    ),
    (
        "persona_summary_budget",
        "Budget-Conscious Low Spender",
        (
            "Budget-Conscious Low Spender: Price-sensitive consumer with limited discretionary "
            "income. Prioritises essential purchases and avoids impulse spending. Compares prices "
            "before buying. Responds to economical, practical, and value-for-money messaging. "
            "Low total spend across all categories. Prefers functional over aspirational. "
            "Cautious, frugal, and cost-conscious decision-making."
        ),
    ),
    (
        "persona_summary_web_savvy",
        "Web-Savvy Mid-Tier Buyer",
        (
            "Web-Savvy Mid-Tier Buyer: Digitally fluent professional with moderate mid-range "
            "income. Shops predominantly online and via mobile. Research-driven and comparison-"
            "oriented before purchasing. Comfortable with e-commerce, digital payments, and "
            "online reviews. Convenience and speed are priorities. Responds to digital-first, "
            "tech-forward, and convenience messaging. Mid-tier spend with growing online "
            "purchase frequency."
        ),
    ),
    (
        "persona_summary_deal_seeker",
        "Deal-Seeking Value Hunter",
        (
            "Deal-Seeking Value Hunter: Promotions-driven consumer who actively seeks discounts, "
            "sales events, and special offers before committing to a purchase. Highly price-"
            "conscious and responds strongly to limited-time deals, coupons, and loyalty rewards. "
            "Bargain-hunting mindset with moderate income. Switches brands when better deals are "
            "available. Campaign-responsive when promotional incentives are strong."
        ),
    ),
    (
        "persona_summary_campaign_responder",
        "Highly Engaged Campaign Responder",
        (
            "Highly Engaged Campaign Responder: Loyal brand advocate with high campaign acceptance "
            "rate. Frequently responds to marketing communications and promotional campaigns. "
            "High engagement rate and long brand tenure. Repeat buyer with strong brand affinity. "
            "Responds to loyalty rewards, exclusive member offers, and personalised outreach. "
            "High lifetime value customer with consistent purchase behaviour."
        ),
    ),
]


def _doc_id(customer_id: int) -> str:
    return f"cs_{customer_id}"


def _row_to_text(row: pd.Series) -> str:
    edu = EDU_LABELS.get(int(row["education_level"]), str(row["education_level"]))
    return (
        f"Persona: {row['persona']}. "
        f"Customer ID {int(row['ID'])}: age {int(row['age'])}, "
        f"{edu} education, {row['Marital_Status']}, "
        f"income ${float(row['Income']):,.0f}, household size {int(row['household_size'])}. "
        f"Total spend: ${float(row['total_spend']):,.0f} "
        f"(wines ${int(row['MntWines'])}, meat ${int(row['MntMeatProducts'])}, "
        f"fish ${int(row['MntFishProducts'])}, fruits ${int(row['MntFruits'])}, "
        f"sweets ${int(row['MntSweetProducts'])}, gold ${int(row['MntGoldProds'])}). "
        f"Preferred channel: {row['dominant_channel']}. "
        f"Campaign type: {row['campaign_type']}. "
        f"Engagement rate: {float(row['engagement_rate']):.2f}. "
        f"Accepted {int(row['campaign_acceptance_count'])} of 6 campaigns. "
        f"Tenure: {int(row['tenure_days'])} days. Cluster: {int(row['cluster'])}."
    )


def ingest_customer_segments() -> int:
    df = load_csv(DATA_DIR / "customer_segments.csv")
    logger.info(f"Loaded {len(df)} rows from customer_segments.csv")

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_SEGMENTS,
        metadata={"hnsw:space": "cosine"},
    )

    total = 0
    for start in range(0, len(df), BATCH_SIZE):
        batch = df.iloc[start : start + BATCH_SIZE]
        docs, metas, ids = [], [], []

        for _, row in batch.iterrows():
            docs.append(_row_to_text(row))
            metas.append({
                "source": "customer_segments.csv",
                "customer_id": int(row["ID"]),
                "persona": str(row["persona"]),
                "cluster": int(row["cluster"]),
                "dominant_channel": str(row["dominant_channel"]),
                "campaign_type": str(row["campaign_type"]),
                "content_type": "customer_profile",
            })
            ids.append(_doc_id(int(row["ID"])))

        collection.upsert(documents=docs, metadatas=metas, ids=ids)
        total += len(docs)
        logger.info(f"Upserted batch {start}–{min(start + BATCH_SIZE, len(df))} ({total} total)")

    logger.info(f"customer_segments: upserted {total} documents into ChromaDB")

    # Upsert 5 persona summary documents — marketing-vocabulary descriptions
    # used by _map_persona() for audience segment → persona classification.
    collection.upsert(
        ids=[s[0] for s in _PERSONA_SUMMARIES],
        documents=[s[2] for s in _PERSONA_SUMMARIES],
        metadatas=[
            {
                "source":       "synthetic",
                "persona":      s[1],
                "content_type": "persona_summary",
            }
            for s in _PERSONA_SUMMARIES
        ],
    )
    logger.info("Upserted 5 persona summary documents into customer_segments collection")

    return total + len(_PERSONA_SUMMARIES)


if __name__ == "__main__":
    count = ingest_customer_segments()
    print(f"Done. {count} documents in customer_segments collection.")
