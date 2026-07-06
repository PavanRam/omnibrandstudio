import hashlib
import json

import chromadb

from src.rag.config import (
    BATCH_SIZE, BRAND_DIR, CHROMA_PATH,
    CHUNK_OVERLAP, CHUNK_SIZE, COLLECTION_BRAND,
)
from src.utils.logger import get_logger

logger = get_logger("rag.ingest_brand")

SECTION_SEP = "=" * 60


# ── ID helpers ────────────────────────────────────────────────────────────────

def _doc_id(text: str) -> str:
    return "bg_" + hashlib.md5(text.encode()).hexdigest()[:16]


# ── Chunking ──────────────────────────────────────────────────────────────────

def _chunk_content(text: str) -> list[str]:
    """Split section content into overlapping chunks by paragraph boundaries."""
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks: list[str] = []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        if current_len + len(para) > CHUNK_SIZE and current:
            chunks.append("\n\n".join(current))
            last = current[-1]
            current = [last, para] if len(last) <= CHUNK_OVERLAP * 3 else [para]
            current_len = sum(len(p) for p in current)
        else:
            current.append(para)
            current_len += len(para)

    if current:
        chunks.append("\n\n".join(current))
    return chunks


# ── JSON → text converters ────────────────────────────────────────────────────

def _brand_identity_to_text(d: dict) -> str:
    return "\n".join([
        f"Brand: {d['brand_name']}",
        f"Tagline: {d['tagline']}",
        f"Industry: {d['industry']}",
        f"Mission: {d['mission']}",
        f"Vision: {d['vision']}",
        "Core Values: "        + " | ".join(d["core_values"]),
        "Brand Personality: "  + " | ".join(d["brand_personality"]),
        "Product Categories: " + " | ".join(d["product_categories"]),
        "Primary Markets: "    + ", ".join(d["primary_markets"]),
        "Primary Languages: "  + ", ".join(d["primary_languages"]),
    ])


def _persona_tone_to_text(persona: str, d: dict) -> str:
    return "\n".join([
        f"Persona: {persona}",
        f"Description: {d['description']}",
        f"Tone: {d['tone']}",
        f"Language Style: {d['language_style']}",
        f"Emotional Appeal: {d['emotional_appeal']}",
        "Key Messages: "     + " | ".join(d["key_messages"]),
        "Content Focus: "    + " | ".join(d["content_focus"]),
        "Avoid: "            + " | ".join(d["avoid"]),
        f"Sentence Length: {d['sentence_length']}",
        "Preferred Channels: " + ", ".join(d["preferred_channels"]),
        f"Campaign Approach: {d['campaign_approach']}",
    ])


def _channel_template_to_text(channel: str, d: dict) -> str:
    parts = [f"Channel: {channel}"]
    for key, val in d.items():
        label = key.replace("_", " ").title()
        if isinstance(val, list):
            parts.append(f"{label}: " + " | ".join(str(v) for v in val))
        else:
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


def _cta_to_text(persona: str, d: dict) -> str:
    channel_ctas = " | ".join(f"{ch}: {cta}" for ch, cta in d["channel_specific"].items())
    return "\n".join([
        f"Persona: {persona}",
        "Primary CTAs: " + " | ".join(d["primary_ctas"]),
        f"Urgency Level: {d['urgency_level']}",
        f"Tone: {d['tone']}",
        f"Channel CTAs: {channel_ctas}",
    ])


def _localization_to_text(lang: str, d: dict) -> str:
    return "\n".join([
        f"Language: {lang}",
        f"Region: {d['region']}",
        f"Formality: {d['formality_level']}",
        f"Date Format: {d['date_format']}",
        f"Currency: {d['currency']}",
        "Cultural Notes: "     + " | ".join(d["cultural_notes"]),
        "Phrases to Avoid: "   + " | ".join(d["phrases_to_avoid"]),
        "Legal Disclaimers: "  + " | ".join(d["legal_disclaimers"]),
    ])


def _compliance_to_text(d: dict) -> str:
    parts: list[str] = []
    for key, val in d.items():
        label = key.replace("_", " ").title()
        if isinstance(val, list):
            parts.append(f"{label}: " + " | ".join(str(v) for v in val))
        elif isinstance(val, dict):
            parts.append(f"{label}: " + " | ".join(f"{k}: {v}" for k, v in val.items()))
        else:
            parts.append(f"{label}: {val}")
    return "\n".join(parts)


# ── Main ingestion ─────────────────────────────────────────────────────────────

def ingest_brand_guidelines() -> int:
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name=COLLECTION_BRAND,
        metadata={"hnsw:space": "cosine"},
    )

    docs:  list[str]  = []
    metas: list[dict] = []
    ids:   list[str]  = []

    # 1. brand_identity.json
    data = json.loads((BRAND_DIR / "brand_identity.json").read_text(encoding="utf-8"))
    text = _brand_identity_to_text(data)
    docs.append(text)
    metas.append({"source": "brand_identity.json", "section": "Brand Identity",
                  "content_type": "brand_identity", "chunk_index": 0})
    ids.append(_doc_id(text))

    # 2. tone_voice_per_persona.json — one doc per persona
    data = json.loads((BRAND_DIR / "tone_voice_per_persona.json").read_text(encoding="utf-8"))
    for persona, pdata in data.items():
        text = _persona_tone_to_text(persona, pdata)
        docs.append(text)
        metas.append({"source": "tone_voice_per_persona.json", "section": "Tone & Voice",
                      "persona": persona, "content_type": "persona_tone", "chunk_index": 0})
        ids.append(_doc_id(text))

    # 3. channel_templates.json — one doc per channel
    data = json.loads((BRAND_DIR / "channel_templates.json").read_text(encoding="utf-8"))
    for channel, cdata in data.items():
        text = _channel_template_to_text(channel, cdata)
        docs.append(text)
        metas.append({"source": "channel_templates.json", "section": "Channel Templates",
                      "channel": channel, "content_type": "channel_template", "chunk_index": 0})
        ids.append(_doc_id(text))

    # 4. cta_library.json — one doc per persona
    data = json.loads((BRAND_DIR / "cta_library.json").read_text(encoding="utf-8"))
    for persona, cdata in data.items():
        text = _cta_to_text(persona, cdata)
        docs.append(text)
        metas.append({"source": "cta_library.json", "section": "CTA Library",
                      "persona": persona, "content_type": "cta_library", "chunk_index": 0})
        ids.append(_doc_id(text))

    # 5. localization_rules.json — one doc per language
    data = json.loads((BRAND_DIR / "localization_rules.json").read_text(encoding="utf-8"))
    for lang, ldata in data.items():
        text = _localization_to_text(lang, ldata)
        docs.append(text)
        metas.append({"source": "localization_rules.json", "section": "Localization Rules",
                      "language": lang, "content_type": "localization_rule", "chunk_index": 0})
        ids.append(_doc_id(text))

    # 6. compliance_rules.json — one document
    data = json.loads((BRAND_DIR / "compliance_rules.json").read_text(encoding="utf-8"))
    text = _compliance_to_text(data)
    docs.append(text)
    metas.append({"source": "compliance_rules.json", "section": "Compliance Rules",
                  "content_type": "compliance_rule", "chunk_index": 0})
    ids.append(_doc_id(text))

    collection.upsert(documents=docs, metadatas=metas, ids=ids)
    total = len(docs)
    logger.info(f"brand_guidelines: upserted {total} documents into ChromaDB")
    return total


if __name__ == "__main__":
    count = ingest_brand_guidelines()
    print(f"Done. {count} documents in brand_guidelines collection.")
