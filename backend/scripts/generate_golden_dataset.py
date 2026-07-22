#!/usr/bin/env python
"""
Generate *silver* golden-dataset examples for a brand from its brand guide.

For each requested channel the script:
  1. retrieves the brand guide context from RAG (Chroma), tenant-scoped by
     ``brand_id`` + ``locale``;
  2. asks a cheap utility model (``util-fast`` alias, through the LiteLLM proxy)
     to synthesise an evaluation example — a brief, the ideal on-brand content,
     the expected composite brand score, a grounding-score target, and a set of
     hallucination traps a weak generator might fall into;
  3. collects the parsed examples and bulk-inserts them into a fresh *draft* set
     via ``golden_dataset_service`` (tenant-isolated, audited).

The examples land as ``silver`` (machine-generated, unreviewed). A human then
promotes the strong ones to ``golden`` and activates the set from the Admin UI
or via ``golden_dataset_service.activate_set``.

Every LLM call goes through ``traced_llm_call`` (no ``campaign_id`` is set, so no
cost-attribution row is written). All model access is by alias, so switching the
free↔paid panel is a config flip with no code change here.

Usage:
    cd backend && uv run python scripts/generate_golden_dataset.py \
        --brand-id 00000000-0000-0000-0000-000000000002 \
        --org-id   00000000-0000-0000-0000-000000000001 \
        --locale en-US --guide-version v1 \
        --channels linkedin,email --count 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

# Add backend/ to path so core/* + pipeline/* + services/* imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.agents.base import traced_llm_call  # noqa: E402
from pipeline.initial_state import resolve_model_aliases  # noqa: E402
from services import golden_dataset_service  # noqa: E402
from services.rag import get_retriever  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

POSTGRES_DSN: str = os.getenv(
    "POSTGRES_DSN",
    "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand",
)

_GEN_SYSTEM = (
    "You are a brand-compliance evaluation author. Given a brand guide excerpt, "
    "you produce ONE high-quality reference example for a {channel} post in "
    "{locale}. The example is used to calibrate an LLM-as-judge panel, so the "
    "'expected_content' must be genuinely on-brand and the 'expected_brand_score' "
    "must reflect how a strict rubric would grade that content on a 0-10 scale."
)

_GEN_USER = (
    "Brand guide excerpt:\n"
    "-----\n{brand_guide}\n-----\n\n"
    "Author one evaluation example for channel '{channel}', locale '{locale}'.\n\n"
    "Return ONLY a JSON object with exactly these keys:\n"
    '  "description": short label for this example,\n'
    '  "brief": object with "objective", "key_messages" (array), "tone",\n'
    '  "expected_content": the ideal on-brand {channel} copy,\n'
    '  "expected_brand_score": number 0-10 (a strong on-brand piece scores 8.5-9.5),\n'
    '  "grounding_score_target": number 0-10 (factual grounding target, usually 9-10),\n'
    '  "known_hallucination_traps": array of strings describing plausible off-brand\n'
    "     or unfounded claims a weak generator might introduce.\n"
)


def _parse_example(raw: str) -> dict[str, Any] | None:
    """Slice to the outermost JSON object and validate the required shape."""
    if not raw:
        return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "expected_content" not in data:
        return None
    return data


async def _brand_guide_context(brand_id: str, locale: str, channel: str) -> str:
    chunks = await get_retriever().retrieve(
        query=f"brand voice, tone, and {channel} formatting guidance",
        brand_id=brand_id,
        locale=locale,
        n_results=6,
    )
    text = "\n\n".join(c.content for c in chunks).strip()
    return text or "(no brand guide retrieved — generate from general best practice)"


async def _generate_one(
    state: dict[str, Any], brand_id: str, locale: str, channel: str
) -> dict[str, Any] | None:
    brand_guide = await _brand_guide_context(brand_id, locale, channel)
    messages = [
        {"role": "system", "content": _GEN_SYSTEM.format(channel=channel, locale=locale)},
        {
            "role": "user",
            "content": _GEN_USER.format(
                brand_guide=brand_guide, channel=channel, locale=locale
            ),
        },
    ]
    raw, _usage = await traced_llm_call(
        model=state["model_aliases"].get("util-fast", "util-fast"),
        messages=messages,
        task="generate_golden_dataset",
        state=state,
        agent="generate_golden_dataset",
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    parsed = _parse_example(raw)
    if parsed is None:
        print(f"  ! failed to parse example for channel={channel}")
        return None
    parsed["channel"] = channel
    parsed["locale"] = locale
    return parsed


async def generate(args: argparse.Namespace) -> None:
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    state: dict[str, Any] = {
        "model_aliases": resolve_model_aliases(),
        "org_id": args.org_id,
        "brand_id": args.brand_id,
        "campaign_id": None,
        "request_id": "generate_golden_dataset",
    }

    examples: list[dict[str, Any]] = []
    for channel in channels:
        for _ in range(args.count):
            example = await _generate_one(state, args.brand_id, args.locale, channel)
            if example is not None:
                examples.append(example)
                print(f"  + generated {channel} example: {example.get('description', '')[:60]}")

    if not examples:
        print("No examples generated — aborting without opening a set.")
        return

    engine = create_async_engine(POSTGRES_DSN, echo=False)
    async with engine.begin() as conn:
        set_id = await golden_dataset_service.open_draft_set(
            conn,
            org_id=args.org_id,
            brand_id=args.brand_id,
            locale=args.locale,
            guide_version=args.guide_version,
            source="llm_generated",
            created_by=args.created_by,
        )
        inserted = await golden_dataset_service.bulk_insert(
            conn,
            org_id=args.org_id,
            brand_id=args.brand_id,
            set_id=set_id,
            examples=examples,
            source="llm_generated",
            status="silver",
            created_by=args.created_by,
        )
    await engine.dispose()
    print(
        f"\nOpened draft set {set_id} with {inserted} silver example(s). "
        "Promote strong examples to golden and activate the set from the Admin UI."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate silver golden-dataset examples.")
    parser.add_argument("--brand-id", required=True, dest="brand_id")
    parser.add_argument("--org-id", required=True, dest="org_id")
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--guide-version", default=None, dest="guide_version")
    parser.add_argument("--channels", default="linkedin,email")
    parser.add_argument("--count", type=int, default=3, help="examples per channel")
    parser.add_argument("--created-by", default=None, dest="created_by")
    return parser


if __name__ == "__main__":
    asyncio.run(generate(_build_parser().parse_args()))
