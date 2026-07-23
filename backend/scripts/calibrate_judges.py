#!/usr/bin/env python
"""
Calibrate the judge panel against a brand's *golden* dataset.

Runs each of the three panel judges (aliases ``judge-1/2/3`` — whichever tier is
active) over every golden example's reference content and compares the judge's
weighted composite (computed exactly as the aggregator does) against the
example's ``expected_brand_score``. It reports, per judge:

  • bias   — mean signed error (positive ⇒ the judge is too generous);
  • MAE    — mean absolute error vs the expected score;
  • n      — number of examples successfully scored;

and, for the panel as a whole, the mean composite, the mean inter-judge score
range (a proxy for the disagreement signal the aggregator routes on), and a
sanity check of the current auto-approve / auto-reject thresholds against the
golden set.

Use this before flipping the free↔paid panel (or after re-seeding golden data)
to decide whether ``DEFAULT_THRESHOLDS`` need tuning per org/brand via
``*_config["aggregator_thresholds"]`` — no agent-code change is ever required.

Every LLM call goes through ``traced_llm_call`` (no ``campaign_id`` set, so no
cost-attribution row is written).

Usage:
    cd backend && uv run python scripts/calibrate_judges.py \
        --brand-id 00000000-0000-0000-0000-000000000002 \
        --org-id   00000000-0000-0000-0000-000000000001 \
        [--set-id <uuid>] [--output docs/judge-calibration.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from typing import Any

# Add backend/ to path so core/* + pipeline/* + services/* imports resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.agents.aggregator import DEFAULT_THRESHOLDS, _weighted_composite_10  # noqa: E402
from pipeline.agents.base import traced_llm_call  # noqa: E402
from pipeline.agents.judges import _parse_brand_score, _to_brand_score  # noqa: E402
from pipeline.agents.prompts.judge_prompts import build_judge_messages  # noqa: E402
from pipeline.initial_state import resolve_model_aliases  # noqa: E402
from services import golden_dataset_service  # noqa: E402
from services.rag import get_retriever  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

POSTGRES_DSN: str = os.getenv(
    "POSTGRES_DSN",
    "postgresql+asyncpg://omnibrand:changeme_local_32chars@localhost:5432/omnibrand",
)

_JUDGE_ALIAS_KEYS: tuple[str, ...] = ("judge-1", "judge-2", "judge-3")


async def _brand_guide_context(brand_id: str, locale: str, channel: str) -> str:
    chunks = await get_retriever().retrieve(
        query=f"brand voice, tone, and {channel} formatting guidance",
        brand_id=brand_id,
        locale=locale,
        n_results=6,
    )
    text = "\n\n".join(c.content for c in chunks).strip()
    return text or "(no brand guide retrieved)"


async def _judge_composite(
    state: dict[str, Any], alias: str, brand_guide: str, channel: str, locale: str, content: str
) -> float | None:
    """Score one example with one judge and return its weighted composite (0-10)."""
    messages = build_judge_messages(
        brand_guide=brand_guide, channel=channel, locale=locale, content=content
    )
    raw, _usage = await traced_llm_call(
        model=alias,
        messages=messages,
        task="calibrate_judges",
        state=state,
        agent="calibrate_judges",
        response_format={"type": "json_object"},
        temperature=0,
    )
    parsed = _parse_brand_score(raw)
    if parsed is None:
        return None
    brand_score = _to_brand_score("calibration", alias, parsed, 0, 0)
    return _weighted_composite_10(brand_score["scores"])


def _summarise(
    per_judge_errors: dict[str, list[float]],
    per_judge_composites: dict[str, list[float]],
    panel_ranges: list[float],
    expected_scores: list[float],
) -> dict[str, Any]:
    judges: dict[str, dict[str, Any]] = {}
    for alias, errors in per_judge_errors.items():
        if not errors:
            judges[alias] = {"n": 0, "bias": None, "mae": None, "mean_composite": None}
            continue
        composites = per_judge_composites[alias]
        judges[alias] = {
            "n": len(errors),
            "bias": round(statistics.fmean(errors), 3),
            "mae": round(statistics.fmean(abs(e) for e in errors), 3),
            "mean_composite": round(statistics.fmean(composites), 3),
        }
    return {
        "judges": judges,
        "panel": {
            "examples_scored": len(panel_ranges),
            "mean_expected_score": (
                round(statistics.fmean(expected_scores), 3) if expected_scores else None
            ),
            "mean_inter_judge_range": (
                round(statistics.fmean(panel_ranges), 3) if panel_ranges else None
            ),
        },
        "thresholds": {
            "auto_approve_10": round(DEFAULT_THRESHOLDS["auto_approve"] * 10, 2),
            "auto_reject_10": round(DEFAULT_THRESHOLDS["auto_reject"] * 10, 2),
            "variance_01": DEFAULT_THRESHOLDS["variance"],
        },
    }


async def calibrate(args: argparse.Namespace) -> None:
    state: dict[str, Any] = {
        "model_aliases": resolve_model_aliases(),
        "org_id": args.org_id,
        "brand_id": args.brand_id,
        "campaign_id": None,
        "request_id": "calibrate_judges",
    }
    aliases = {key: state["model_aliases"].get(key, key) for key in _JUDGE_ALIAS_KEYS}

    engine = create_async_engine(POSTGRES_DSN, echo=False)
    async with engine.connect() as conn:
        examples = await golden_dataset_service.list_examples(
            conn,
            org_id=args.org_id,
            brand_id=args.brand_id,
            status="golden",
            set_id=args.set_id,
        )
    await engine.dispose()

    if not examples:
        print("No golden examples found for this brand — nothing to calibrate.")
        return

    per_judge_errors: dict[str, list[float]] = {a: [] for a in aliases.values()}
    per_judge_composites: dict[str, list[float]] = {a: [] for a in aliases.values()}
    panel_ranges: list[float] = []
    expected_scores: list[float] = []

    for i, ex in enumerate(examples, start=1):
        expected = ex.get("expected_brand_score")
        content = ex.get("expected_content")
        if expected is None or not content:
            continue
        expected_f = float(expected)
        channel = ex.get("channel") or "unknown"
        locale = ex.get("locale") or "en-US"
        brand_guide = await _brand_guide_context(args.brand_id, locale, channel)

        composites: list[float] = []
        for alias in aliases.values():
            composite = await _judge_composite(
                state, alias, brand_guide, channel, locale, content
            )
            if composite is None:
                continue
            per_judge_errors[alias].append(composite - expected_f)
            per_judge_composites[alias].append(composite)
            composites.append(composite)

        if composites:
            expected_scores.append(expected_f)
            panel_ranges.append(max(composites) - min(composites))
        print(f"  [{i}/{len(examples)}] scored {channel} example (expected {expected_f:.2f})")

    report = _summarise(
        per_judge_errors, per_judge_composites, panel_ranges, expected_scores
    )
    print("\n=== Judge calibration report ===")
    print(json.dumps(report, indent=2))

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nWrote report to {args.output}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate the judge panel on golden data.")
    parser.add_argument("--brand-id", required=True, dest="brand_id")
    parser.add_argument("--org-id", required=True, dest="org_id")
    parser.add_argument("--set-id", default=None, dest="set_id")
    parser.add_argument("--output", default=None, help="optional path to write JSON report")
    return parser


if __name__ == "__main__":
    asyncio.run(calibrate(_build_parser().parse_args()))
