#!/usr/bin/env python
"""
Seed script — inserts the minimal data the worker and pipeline need to boot
without errors:

  • 1 test organisation
  • 1 test brand
  • prompt templates (intake, generator, personalisation, translation,
    judge panel, reflexion, aggregator, review-gate, publisher, brief-validator)

Judge + reflexion prompts are sourced from the canonical templates in
`pipeline/agents/prompts/judge_prompts.py`, so the DB copy and the in-code
fallback used by the judges never drift.

Run after every fresh `make migrate`.

Usage:
    cd backend && uv run python ../scripts/seed_prompts.py
"""
from __future__ import annotations

import asyncio
import os
import sys

# Add backend/ to path so core/* + pipeline/* imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from pipeline.agents.prompts.judge_prompts import (  # noqa: E402
    JUDGE_SYSTEM_TEMPLATE,
    JUDGE_USER_TEMPLATE,
    REFLEXION_SYSTEM_TEMPLATE,
    REFLEXION_USER_TEMPLATE,
    RUBRIC_TEXT,
)
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

POSTGRES_DSN: str = os.getenv(
    "POSTGRES_DSN",
    "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand",
)

ORG_ID    = "00000000-0000-0000-0000-000000000001"
BRAND_ID  = "00000000-0000-0000-0000-000000000002"

# The judge panel system prompt is pre-rendered with the fixed rubric; the
# {channel}/{locale} and {brand_guide}/{content} placeholders remain for the
# PromptService to fill at call time. Judges + reflexion are sourced from the
# canonical templates so the DB copy and in-code fallback never drift.
_JUDGE_SYSTEM = JUDGE_SYSTEM_TEMPLATE.replace("{rubric}", RUBRIC_TEXT)

# (name, system_prompt, user_prompt, variables)
PROMPTS: list[tuple[str, str, str, list[str]]] = [
    (
        "intake_brief_parser",
        "You are the Intake Agent. Parse the brief into structured fields.",
        "Brief:\n{brief}\n\nReturn structured fields.",
        ["brief"],
    ),
    (
        "brief_validator",
        "You validate campaign briefs for completeness.",
        "Brief:\n{brief}\n\nList any missing or ambiguous fields.",
        ["brief"],
    ),
    (
        "content_generator",
        "You generate on-brand {channel} content for {brand_name}.",
        "Brief:\n{brief}\n\nTone: {tone}\n\nWrite the content.",
        ["channel", "brand_name", "brief", "tone"],
    ),
    (
        "personalization_agent",
        "You personalise content for a specific audience segment.",
        "Segment: {segment}\n\nContent:\n{content}\n\nRewrite for the segment.",
        ["segment", "content"],
    ),
    (
        "translation_agent",
        "You translate marketing content while preserving brand voice.",
        "Target locale: {target_locale}\n\nContent:\n{content}",
        ["target_locale", "content"],
    ),
    (
        "judge_panel",
        _JUDGE_SYSTEM,
        JUDGE_USER_TEMPLATE,
        ["channel", "locale", "brand_guide", "content"],
    ),
    (
        "reflexion",
        REFLEXION_SYSTEM_TEMPLATE,
        REFLEXION_USER_TEMPLATE,
        ["channel", "locale", "content", "reasons", "critical"],
    ),
    (
        "confidence_aggregator",
        "You summarise aggregated judge scores for a reviewer.",
        "Scores:\n{scores}\n\nSummarise the consensus and routing.",
        ["scores"],
    ),
    (
        "review_gate",
        "You summarise a review request for a human reviewer.",
        "Scores: {scores}\nContent: {content}",
        ["scores", "content"],
    ),
    (
        "publishing_agent",
        "You prepare the final content payload for publication.",
        "Channel: {channel}\nContent:\n{content}",
        ["channel", "content"],
    ),
]


async def seed() -> None:
    engine = create_async_engine(POSTGRES_DSN, echo=False)
    async with engine.begin() as conn:
        # Idempotent — skip if rows already exist
        result = await conn.execute(
            text("SELECT id FROM orgs WHERE id = :id"),
            {"id": ORG_ID},
        )
        if result.first() is None:
            await conn.execute(
                text(
                    "INSERT INTO orgs (id, name, slug, tier, config) "
                    "VALUES (:id, 'Demo Org', 'demo-org', 'free', '{}'::jsonb)"
                ),
                {"id": ORG_ID},
            )
            print(f"  Created org  {ORG_ID}")

        result = await conn.execute(
            text("SELECT id FROM brands WHERE id = :id"),
            {"id": BRAND_ID},
        )
        if result.first() is None:
            await conn.execute(
                text(
                    "INSERT INTO brands (id, org_id, name, config) "
                    "VALUES (:id, :org_id, 'Demo Brand', '{}'::jsonb)"
                ),
                {"id": BRAND_ID, "org_id": ORG_ID},
            )
            print(f"  Created brand {BRAND_ID}")

        for name, system_prompt, user_prompt, variables in PROMPTS:
            result = await conn.execute(
                text("SELECT id FROM prompt_registry WHERE name = :name AND org_id IS NULL"),
                {"name": name},
            )
            if result.first() is None:
                await conn.execute(
                    text(
                        "INSERT INTO prompt_registry "
                        "  (name, version, org_id, status, system_prompt, user_prompt, variables) "
                        "VALUES "
                        "  (:name, '1.0.0', NULL, 'active', "
                        ":system_prompt, :user_prompt, :variables)"
                    ),
                    {
                        "name": name,
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                        "variables": variables,
                    },
                )
                print(f"  Seeded prompt: {name}")

    await engine.dispose()
    print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
