"""Local demo for T4 — Personalization agent (MULTIPLY model, real personas).

Shows the "multiply" flow from the Session 2 slide:
  content_generator (T3) produces one CHANNEL-specific draft per channel
  → personalization (T4) expands each draft into ALL 5 customer personas
  → 2 channels x 5 personas = 10 persona-conditioned, PII-safe variants.

Persona voice + CTA profiles are read directly from the data track's brand files
(structured lookup by persona name) — the same data that's in ChromaDB/RAG.

- No LITELLM_BASE_URL  -> offline LLM stand-in (zero infrastructure).
- Set LITELLM_BASE_URL -> real traced_llm_call, no code change.

Run from the backend/ directory:
    uv run python scripts/demo_personalization.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx

# Ensure backend/ (parent of scripts/) is importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Print UTF-8 cleanly on Windows consoles (real brand copy uses em-dashes etc.).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pipeline.agents import personalization as perso  # noqa: E402
from pipeline.agents.personalization import personalization_agent  # noqa: E402

# ── Real brand persona data (data track output) ────────────────────────────
BRAND_DIR = Path.home() / "Downloads" / "brand-guidelines"
TONE_FILE = BRAND_DIR / "tone_voice_per_persona.json"
CTA_FILE = BRAND_DIR / "cta_library.json"

# ── content_generator (T3) output: one CHANNEL-specific draft per channel ──
# Product: iPhone 17. Each draft keeps a support contact so PII redaction shows.
CHANNEL_DRAFTS = {
    "amazon": (
        "Apple iPhone 17 - A19 Pro chip, 48MP triple-camera system, aerospace-grade "
        "titanium design, all-day battery, 6.3-inch Super Retina display. In stock, "
        "free next-day delivery. Support: support@applestore.com or +1 (800) 555-0100."
    ),
    "whatsapp": (
        "Hi! The all-new iPhone 17 just dropped - A19 Pro chip, pro camera, titanium "
        "design. Want details or a trade-in quote? Reply here or email support@applestore.com."
    ),
}

# Map a demo channel to the nearest CTA key in cta_library's channel_specific.
_CHANNEL_CTA_KEY = {"amazon": "Web", "whatsapp": "Facebook"}

# For the offline shim: tone string -> {opener, cta_by_channel}.
_DEMO_BY_TONE: dict[str, dict] = {}


def load_real_personas():
    """Read real persona voice + CTA profiles. Returns (profiles, persona_list)."""
    if not TONE_FILE.exists() or not CTA_FILE.exists():
        return {}, []
    tone_voice = json.loads(TONE_FILE.read_text(encoding="utf-8"))
    cta_lib = json.loads(CTA_FILE.read_text(encoding="utf-8"))

    profiles: dict[str, dict[str, str]] = {}
    personas: list[str] = []
    for persona, tv in tone_voice.items():
        cta_entry = cta_lib.get(persona, {})
        primary = (cta_entry.get("primary_ctas") or ["Shop Now"])[0]
        chan_ctas = cta_entry.get("channel_specific", {})

        tone = f"{tv['tone']} | style: {tv['language_style']}"
        profiles[persona] = {
            "tone": tone,
            "reading_level": tv.get("sentence_length", "Medium"),
            "cta_style": primary,
        }
        _DEMO_BY_TONE[tone] = {
            "opener": (tv.get("key_messages") or [""])[0],
            "cta_by_channel": {
                ch: chan_ctas.get(_CHANNEL_CTA_KEY[ch], primary) for ch in CHANNEL_DRAFTS
            },
        }
        personas.append(persona)
    return profiles, personas


def _variant(task_id: str, channel: str, segment: str, generated: str) -> dict:
    return {
        "task_id": task_id, "locale": "en-US", "channel": channel, "segment": segment,
        "generated_content": generated, "personalized_content": None,
        "translated_content": None, "final_content": None, "status": "generated",
        "generation_model": "gen-premium", "prompt_version": "v1",
        "brand_guide_version": None, "translation_engine": None,
        "back_translation_score": None, "retry_count": 0,
        "reflexion_applied": False, "failure_reason": None,
    }


def _sample_state(profiles, personas) -> dict:
    # THE MULTIPLY: each channel draft x each persona -> one variant.
    variants = []
    i = 0
    for channel, draft in CHANNEL_DRAFTS.items():
        for persona in personas:
            variants.append(_variant(f"t-{i}", channel, persona, draft))
            i += 1
    return {
        "campaign_id": "demo-1", "org_id": "local-org", "brand_id": "local-brand",
        "user_id": "local-user", "model_aliases": {},
        "org_config": {"segment_profiles": profiles}, "brief": None,
        "variants": variants, "errors": [], "token_cost_usd": 0.0,
    }


async def _groq_llm(model, messages, task, state, **kwargs):
    """Real rewrite via Groq's free OpenAI-compatible API (needs GROQ_API_KEY).
    Produces genuinely reframed, attractive persona copy."""
    key = os.environ["GROQ_API_KEY"]
    groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": groq_model, "messages": messages, "temperature": 0.7},
        )
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"].strip(), {"cost": 0.0}


async def _offline_llm(model, messages, task, state, **kwargs):
    """Deterministic stand-in: persona key-message opener + channel-specific CTA."""
    prompt = messages[1]["content"]
    tone = re.search(r"- Tone: (.+)", prompt)
    chan = re.search(r"Rewrite the following (\S+) content", prompt)
    tone_s = tone.group(1).strip() if tone else ""
    chan_s = chan.group(1).strip() if chan else ""
    content = prompt.split("Content:\n", 1)[-1].strip()  # already PII-redacted
    frame = _DEMO_BY_TONE.get(tone_s, {"opener": "", "cta_by_channel": {}})
    opener = (frame["opener"] + " ") if frame["opener"] else ""
    cta = frame["cta_by_channel"].get(chan_s, "")
    cta = (" " + cta) if cta else ""
    return f"{opener}{content}{cta}", {"cost": 0.0004}


async def main() -> None:
    profiles, personas = load_real_personas()
    using_real = bool(profiles)
    if not using_real:
        profiles = perso.DEFAULT_SEGMENT_PROFILES
        personas = list(profiles.keys())

    # Pick the LLM: Groq (real, free) > LiteLLM proxy > offline stand-in.
    if os.getenv("GROQ_API_KEY"):
        perso.traced_llm_call = _groq_llm
        llm_mode = "REAL LLM (Groq)"
    elif os.getenv("LITELLM_BASE_URL"):
        llm_mode = "REAL LLM (LiteLLM proxy)"
    else:
        perso.traced_llm_call = _offline_llm
        llm_mode = "OFFLINE stand-in (wraps, does not rewrite)"
    persona_src = "real personas (K-Means)" if using_real else "built-in placeholders"

    state = _sample_state(profiles, personas)
    n_ch, n_pers = len(CHANNEL_DRAFTS), len(personas)

    print("\n" + "#" * 80)
    print("#  T4 PERSONALIZATION AGENT - DEMO  (multiply: channels x personas)")
    print(f"#  Product: iPhone 17   |   Personas: {persona_src}   |   LLM: {llm_mode}")
    print("#" * 80)
    print(f"\ncontent_generator (T3) produced {n_ch} CHANNEL drafts.")
    print(f"personalization (T4) multiplies each into {n_pers} personas "
          f"= {n_ch * n_pers} variants.\n")

    result = await personalization_agent(state)

    for channel, draft in CHANNEL_DRAFTS.items():
        print("#" * 80)
        print(f"#  CHANNEL: {channel.upper()}")
        print("#" * 80)
        print("BASE DRAFT (from content_generator):")
        print("  " + draft)
        print(f"\n-> personalized into {n_pers} personas:\n")
        for v in state["variants"]:
            if v["channel"] != channel:
                continue
            pii_gone = "@applestore.com" not in v["personalized_content"]
            print(f"  • {v['segment']}   [PII removed: {pii_gone}]")
            print(f"    {v['personalized_content']}\n")

    print("=" * 80)
    print(f"SUMMARY: {n_ch} channels x {n_pers} personas = {len(state['variants'])} variants "
          f"personalized | cost=${result.get('token_cost_usd'):.4f} | errors={state['errors']}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
