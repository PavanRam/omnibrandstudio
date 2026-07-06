from __future__ import annotations

import json
import logging
import os
import re

from pydantic import ValidationError

from src.agents.state import WorkflowState
from src.schemas.campaign_brief import ValidationResult

logger = logging.getLogger(__name__)

_OMNIBRAND_DOMAINS = (
    "lifestyle, consumer goods, fashion, food & beverages, home, health, technology"
)

_PERSONAS = """\
1. High-Income Store Spender: Affluent professional with high disposable income, \
preferring premium and luxury brands. Shops predominantly in-store at upscale retail \
locations. They can occasionally shop via other channels too. Values quality, exclusivity, \
and brand prestige over price. Aspirational and sophisticated lifestyle. Responds to \
heritage, craftsmanship, and understated luxury messaging. High total spend across premium \
goods, wines, and gourmet products. Long brand tenure and strong loyalty.

2. Budget-Conscious Low Spender: Price-sensitive consumer with limited discretionary \
income. Prioritises essential purchases and avoids impulse spending. Compares prices \
before buying. Responds to economical, practical, and value-for-money messaging. \
Low total spend across all categories. Prefers functional over aspirational. \
Cautious, frugal, and cost-conscious decision-making.

3. Web-Savvy Mid-Tier Buyer: Digitally fluent professional with moderate mid-range \
income. Shops predominantly online and via mobile. Research-driven and comparison-\
oriented before purchasing. Comfortable with e-commerce, digital payments, and \
online reviews. Convenience and speed are priorities. Responds to digital-first, \
tech-forward, and convenience messaging. Mid-tier spend with growing online \
purchase frequency.

4. Deal-Seeking Value Hunter: Promotions-driven consumer who actively seeks discounts, \
sales events, and special offers before committing to a purchase. Highly price-\
conscious and responds strongly to limited-time deals, coupons, and loyalty rewards. \
Bargain-hunting mindset with moderate income. Switches brands when better deals are \
available. Campaign-responsive when promotional incentives are strong.

5. Highly Engaged Campaign Responder: Loyal brand advocate with high campaign acceptance \
rate. Frequently responds to marketing communications and promotional campaigns. \
High engagement rate and long brand tenure. Repeat buyer with strong brand affinity. \
Responds to loyalty rewards, exclusive member offers, and personalised outreach. \
High lifetime value customer with consistent purchase behaviour."""

_PROMPT = """\
You are a domain classifier for Omnibrand Studio, a Lifestyle & Consumer Goods brand.

Read the campaign brief and audience segment below and answer two questions:

1. Is the campaign brief specific enough to identify a clear product or service, \
AND is that product/service within Omnibrand Studio's domain?
   Omnibrand Studio's domain: {domains}
   Outside domain (always invalid): B2B enterprise software, political campaigns, \
financial instruments, medical devices, legal services.
   Also invalid: briefs that do not name or describe any specific product or service \
(e.g. "we are launching a new product" or "increase brand awareness" with no product named).

2. Which of the 5 customer personas below best matches the audience segment?
   Pick the closest match. If the audience does not resemble any persona at all, set persona to null.

Personas:
{personas}

Campaign Brief: {campaign_brief}
Audience Segment: {audience_segment}

Respond with raw JSON only — no explanation, no markdown:
{{"valid": true, "reason": "one sentence", "persona": "exact persona name from the list or null"}}
{{"valid": false, "reason": "one sentence", "persona": null}}"""


def _get_llm():
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"), temperature=0)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
    raise ValueError(f"Unsupported LLM_PROVIDER '{provider}'. Set to 'groq' or 'openai'.")


_MALFORMED_RESULT = ValidationResult(
    valid=False, reason="LLM returned a malformed response; please retry."
)


def _parse_result(content: str) -> ValidationResult:
    content = content.strip()
    parsed = None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]+\}", content, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                pass

    if parsed is None:
        return _MALFORMED_RESULT
    try:
        return ValidationResult.model_validate(parsed)
    except ValidationError:
        return _MALFORMED_RESULT


def business_validate(state: WorkflowState) -> WorkflowState:
    """LangGraph node: one structured LLM call that judges domain relevance and resolves persona."""
    brief = state["brief"]
    prompt = _PROMPT.format(
        campaign_brief=brief["campaign_brief"],
        audience_segment=brief["audience_segment"],
        domains=_OMNIBRAND_DOMAINS,
        personas=_PERSONAS,
    )

    logger.info("Business validator — prompt sent:\n%s", prompt)
    try:
        response = _get_llm().invoke(prompt)
        logger.info("Business validator — raw LLM response: %s", response.content)
        result = _parse_result(response.content)
    except Exception as exc:
        logger.error("Business validator — LLM call failed: %s", exc, exc_info=True)
        result = ValidationResult(valid=False, reason=f"Validation service error: {exc}")

    valid = result.valid
    reason = result.reason
    persona = result.persona or None  # treat empty string as None
    logger.info("Business validator — persona resolved: %s", persona)
    return {
        **state,
        "business_valid": valid,
        "validation_error": None if valid else reason,
        "status": "approved" if valid else "business_failed",
        "persona": persona,
    }
