# Judge Gate Agent (`judge_planner.py`)

## Purpose
Runs after `translation_agent`, before the judge panel. A deterministic
(no-LLM) gate that decides how much judge scrutiny a campaign needs, so the
3-judge panel isn't run at full cost for every low-risk campaign.

File: `backend/pipeline/agents/judge_planner.py`

## Write permissions (`AGENT_WRITE_PERMISSIONS["judge_gate"]`)
`judge_mode`

## Modes (`state["judge_mode"]`)
- **`"full"`** — fan out to all three cross-family judges (`judge_claude`,
  `judge_gpt4o`, `judge_llama`). Default; always used for a brand's first
  campaign and for regulated/high-risk content.
- **`"lite"`** — single judge (`judge_claude`) only; `confidence_aggregator`
  runs in degraded mode and is biased toward flagging for human review.
  Used for established brands with low-risk briefs and no override.
- **`"skip"`** — bypass judging entirely, go straight to `review_gate`. Only
  reachable via explicit org/brand config (`judge_mode` in
  `brand_config`/`org_config`) — never auto-selected.

## Decision precedence (`_resolve_mode`)
1. First campaign for the brand (`prior_campaigns` empty) → always `"full"`.
2. High-risk keyword match in the brief (`_HIGH_RISK_KEYWORDS`: health,
   medical, financial, legal, compliance, insurance, tax, pharma, etc.,
   checked against `raw_text` + `key_messages`) → always `"full"`.
3. Explicit `brand_config`/`org_config["judge_mode"]` override (if one of the
   three valid modes) → use it.
4. Otherwise → `"lite"`.

This is a cheap heuristic (no LLM call), designed so calibration data can
later tighten the risk bands without any agent code change.

## Router (`judge_gate_router`, conditional edge)
- `"skip"` → `["review_gate"]`
- `"lite"` → `["judge_claude"]`
- default/`"full"` → `["judge_claude", "judge_gpt4o", "judge_llama"]`

## Wrapping
`judge_gate(state)` → `safe_agent_run(_impl, state)`.
