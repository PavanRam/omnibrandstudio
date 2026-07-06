from sentence_transformers import SentenceTransformer

_encoder: SentenceTransformer | None = None


def get_encoder() -> SentenceTransformer:
    """Return the shared all-MiniLM-L6-v2 encoder singleton."""
    global _encoder
    if _encoder is None:
        _encoder = SentenceTransformer("all-MiniLM-L6-v2")
    return _encoder
