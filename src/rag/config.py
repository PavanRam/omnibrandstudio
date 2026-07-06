from pathlib import Path

PROJECT_ROOT   = Path(__file__).resolve().parents[2]  # src/rag/config.py → project root
CHROMA_PATH    = str(PROJECT_ROOT / "knowledge_base" / "chroma")
DATA_DIR       = PROJECT_ROOT / "datasets" / "processed"
BRAND_DIR      = DATA_DIR / "brand_guidelines"
BM25_CACHE_DIR = PROJECT_ROOT / "knowledge_base" / "bm25_cache"

COLLECTION_BRAND     = "brand_guidelines"
COLLECTION_SEGMENTS  = "customer_segments"
COLLECTION_CAMPAIGNS = "campaign_performance"
COLLECTION_SENTIMENT = "sentiment_insights"

CHUNK_SIZE    = 600
CHUNK_OVERLAP = 80
BATCH_SIZE    = 500

# Hybrid search & re-ranking
HYBRID_FETCH_K = 20    # oversample from vector + BM25 before merging/reranking
RRF_K          = 60    # RRF rank-constant (standard value)
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# MMR (Maximal Marginal Relevance)
# λ=1.0 → pure relevance (standard ranking); λ=0.0 → pure diversity
# 0.7 gives 70% relevance weight, 30% diversity — good default for marketing content
MMR_LAMBDA = 0.7
