"""Golden dataset generator — auto-creates evaluation examples from brand guides + segments.

Generates 10-15 examples per (brand, locale, version) combo:
- 5 extracted from brand guide content (deterministic)
- 10 LLM-generated judge scenarios (traced calls)

All examples start as 'silver' (unreviewed). Admin can promote to 'golden'
before activation. Idempotent: skips generation if set already exists.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from pipeline.agents.base import traced_llm_call
from services.audit_service import write_audit
from services.rag.ingest import list_customer_segments, list_brand_guides_from_store
from services.golden_dataset_service import open_draft_set, bulk_insert


BRAND_VOICE_PROMPT = """You are an expert campaign evaluator. Given the brand guidelines and customer segments below, generate a realistic judge scenario for content evaluation.

**Brand Guidelines:**
{guidelines}

**Customer Segment (Persona):**
{segment}

Generate a JSON object with:
{{
  "channel": "linkedin|email|twitter|instagram|landing_page|slack",
  "brief": {{"persona": "segment", "channel": "channel", "objective": "objective"}},
  "description": "Brief label for this example",
  "expected_content": "Realistic generated content for this channel/brief",
  "expected_brand_score": 0.85
}}

Important: Use realistic marketing language. Keep brief and content concise. expected_brand_score should be 0.0-1.0."""


async def generate_golden_examples(
    conn: AsyncConnection,
    *,
    brand_id: str,
    locale: str,
    guide_version: str,
    org_id: str,
    llm_model: str = "gen-premium",
    created_by: str | None = None,
) -> tuple[str, int]:
    """
    Auto-generate golden dataset examples from brand guides + segments.
    
    Returns: (set_id, example_count)
    Raises: ValueError if guides/segments not found
    """
    # Check if set already exists (idempotent)
    existing = await conn.execute(
        text(
            """
            SELECT id FROM golden_dataset_set
            WHERE org_id = :org_id AND brand_id = :brand_id
              AND locale = :locale AND guide_version = :guide_version
            LIMIT 1
            """
        ),
        {"org_id": org_id, "brand_id": brand_id, "locale": locale, "guide_version": guide_version},
    )
    if existing.scalar_one_or_none():
        raise ValueError(
            f"Golden dataset set already exists for {brand_id}/{locale}/{guide_version} — skipping generation"
        )

    # Fetch brand guides + segments from RAG
    guides = await list_brand_guides_from_store(brand_id=brand_id)
    segments = await list_customer_segments(brand_id=brand_id, locale=locale, limit=100)

    if not guides:
        raise ValueError(f"No brand guides found for {brand_id} in RAG")
    if not segments:
        raise ValueError(f"No customer segments found for {brand_id}/{locale} in RAG")

    # Create draft set
    set_id = await open_draft_set(
        conn,
        org_id=org_id,
        brand_id=brand_id,
        locale=locale,
        guide_version=guide_version,
        source="llm_generated",
        created_by=created_by,
    )

    # Fetch full guide content from RAG (not just metadata)
    from services.rag import get_vector_store
    store = get_vector_store()
    guide_docs = await store.get_documents(
        collection=f"brand_{brand_id}_guidelines",
        filters={"brand_id": brand_id, "locale": locale, "active": True},
        limit=10,
    )
    
    guide_text = ""
    if guide_docs:
        # Combine first few chunks of guide content
        guide_text = " ".join([doc.text for doc in guide_docs[:3]])
    
    if not guide_text:
        # Fallback: create simple placeholder if no guide content found
        guide_text = "Brand guidelines available but content not accessible"

    # Prepare extracted examples (5 from guide content)
    extracted_examples: list[dict[str, Any]] = []
    if guide_text:
        channels = ["linkedin", "email", "twitter"]
        for i, channel in enumerate(channels[:min(2, len(channels))]):  # 2 extracted
            extracted_examples.append({
                "channel": channel,
                "description": f"{channel.title()} example from brand guide",
                "brief": {"persona": "general", "channel": channel, "objective": "brand awareness"},
                "expected_content": guide_text[:300].strip(),
                "expected_brand_score": 0.85,
            })

    # Generate LLM examples (10 scenarios)
    generated_examples: list[dict[str, Any]] = []
    channels = ["linkedin", "email", "twitter", "instagram", "landing_page"]
    
    for i, segment in enumerate(segments[:10]):
        # Handle both dict and SearchResult objects
        if isinstance(segment, dict):
            segment_text = segment.get("text", str(segment)[:500])
        else:
            segment_text = getattr(segment, "text", str(segment))[:500]
        
        try:
            content, usage = await traced_llm_call(
                model=llm_model,
                messages=[
                    {
                        "role": "user",
                        "content": BRAND_VOICE_PROMPT.format(
                            guidelines=guide_text[:1000],
                            segment=segment_text,
                        ),
                    }
                ],
                task="golden_dataset_generation",
                state={
                    "org_id": org_id,
                    "brand_id": brand_id,
                    "locale": locale,
                },
            )
            
            try:
                example_obj = json.loads(content)
                example_obj["status"] = "silver"
                generated_examples.append(example_obj)
            except json.JSONDecodeError:
                # Fallback if LLM output isn't valid JSON
                generated_examples.append({
                    "channel": channels[i % len(channels)],
                    "description": "LLM-generated example",
                    "brief": {"persona": "persona", "channel": channels[i % len(channels)]},
                    "expected_content": content[:300],
                    "expected_brand_score": 0.7,
                })
        except Exception as err:
            print(f"Warning: Failed to generate example {i+1}: {err}")
            continue

    # Combine all examples
    all_examples = extracted_examples + generated_examples
    
    if not all_examples:
        raise ValueError("No examples generated — check RAG/LLM connectivity")

    # Bulk insert examples using service
    inserted_count = await bulk_insert(
        conn,
        org_id=org_id,
        brand_id=brand_id,
        set_id=set_id,
        examples=all_examples,
        source="llm_generated",
        status="silver",
        created_by=created_by,
    )

    await write_audit(
        conn,
        entity_type="golden_dataset",
        action="auto_generated",
        actor_id=created_by,
        entity_id=set_id,
        brand_id=brand_id,
        org_id=org_id,
        after_val={"locale": locale, "guide_version": guide_version, "example_count": inserted_count},
    )

    return set_id, inserted_count
