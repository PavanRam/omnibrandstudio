from __future__ import annotations

import logging
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)

from src.agents.workflow import validation_graph
from src.schemas.campaign_brief import VALID_CHANNELS, VALID_LANGUAGES

st.set_page_config(page_title="Omnibrand Studio Campaign Hub", layout="wide")
st.title("Omnibrand Studio — Campaign Content Hub")
st.caption("Submit a campaign brief to validate and generate on-brand content across channels.")

if "attempts" not in st.session_state:
    st.session_state.attempts = 0

# ── Content render helper ─────────────────────────────────────────────────────

_FIELD_ORDER = [
    ("subject",      "Subject"),
    ("preview_text", "Preview Text"),
    ("title",        "Title"),
    ("headline",     "Headline"),
    ("subheadline",  "Subheadline"),
    ("body",         "Body"),
    ("description",  "Description"),
    ("hashtags",     "Hashtags"),
    ("cta",          "Call to Action"),
]
_KNOWN_FIELDS = {f for f, _ in _FIELD_ORDER} | {"notes", "error", "raw"}


def _render_content(content: dict, channel: str) -> None:
    """Render one channel × language content block."""
    if not content:
        st.info("No content available.")
        return

    if "error" in content:
        st.warning(f"Generation error: {content['error']}")
        if "raw" in content:
            with st.expander("Raw LLM response"):
                st.text(content["raw"])
        return

    for field, label in _FIELD_ORDER:
        val = content.get(field)
        if not val:
            continue

        if field == "hashtags":
            tags = val if isinstance(val, list) else [val]
            st.markdown(f"**{label}:** " + "  ".join(f"`{t}`" for t in tags))

        elif field == "cta":
            st.success(f"**{label}:** {val}")

        elif field in ("body", "description"):
            st.markdown(f"**{label}:**")
            st.markdown(val)
            st.markdown("")

        else:
            st.markdown(f"**{label}:** {val}")

    extras = {k: v for k, v in content.items() if k not in _KNOWN_FIELDS}
    if extras:
        with st.expander("Additional fields"):
            st.json(extras)

    notes = content.get("notes")
    if notes:
        st.caption(f"Notes: {notes}")


# ── Brief form ────────────────────────────────────────────────────────────────

with st.form("brief_form"):
    st.subheader("Campaign Brief")

    campaign_brief = st.text_area(
        "Campaign Brief *",
        placeholder="Describe the campaign, product, and key messages...",
        height=130,
        key="campaign_brief",
    )
    audience_segment = st.text_input(
        "Audience Segment *",
        placeholder="e.g. Eco-conscious shoppers, 22–40, urban, premium segment",
        key="audience_segment",
    )
    brand_tone = st.text_input(
        "Brand Tone *",
        placeholder="e.g. Authentic, values-driven, premium but not elitist",
        key="brand_tone",
    )
    campaign_goal = st.text_input(
        "Campaign Goal *",
        placeholder="e.g. Website traffic and first purchase",
        key="campaign_goal",
    )

    col1, col2 = st.columns(2)
    with col1:
        target_channels = st.multiselect(
            "Target Channels *",
            options=sorted(VALID_CHANNELS),
            default=["Instagram", "Facebook"],
            key="target_channels",
        )
    with col2:
        target_languages = st.multiselect(
            "Target Languages *",
            options=sorted(VALID_LANGUAGES),
            default=["English"],
            key="target_languages",
        )

    restricted_words_raw = st.text_input(
        "Restricted Words (comma-separated)",
        placeholder="e.g. Cheap, fast fashion, eco-washing",
        key="restricted_words",
    )

    submitted = st.form_submit_button("Validate & Generate", type="primary")

# ── Pipeline execution ────────────────────────────────────────────────────────

if submitted:
    restricted_words = [w.strip() for w in restricted_words_raw.split(",") if w.strip()]
    brief_dict = {
        "campaign_brief":      campaign_brief,
        "audience_segment":    audience_segment,
        "target_channels":     target_channels,
        "target_languages":    target_languages,
        "brand_tone":          brand_tone,
        "campaign_goal":       campaign_goal,
        "restricted_words":    restricted_words,
        "validation_attempts": st.session_state.attempts,
        "human_approved":      False,
    }

    with st.spinner("Validating brief and generating content across channels…"):
        result = validation_graph.invoke({
            "brief":             brief_dict,
            "system_valid":      None,
            "input_scan_valid":  None,
            "business_valid":    None,
            "validation_error":  None,
            "status":            "pending",
            "persona":           None,
            "assembled_context": None,
            "generated_content": None,
        })

    st.session_state.attempts += 1
    status = result.get("status", "")

    # ── Error states ──────────────────────────────────────────────────────────

    if status == "system_failed":
        st.error(f"**System validation failed:** {result.get('validation_error', '')}")
        st.info("Fix the issue above and resubmit.")

    elif status == "input_scan_failed":
        st.error(f"**Input security scan failed:** {result.get('validation_error', '')}")
        st.info("Remove the flagged content and resubmit.")

    elif status == "business_failed":
        st.error(f"**Brief rejected:** {result.get('validation_error', '')}")
        st.info("Review your brief for completeness and domain relevance, then resubmit.")

    elif status == "context_failed":
        st.error(f"**Context assembly failed:** {result.get('validation_error', '')}")
        st.warning(
            "The MCP server may not be running.  "
            "Start it with: `venv\\Scripts\\python -m src.rag.mcp_server`"
        )

    elif status == "generation_failed":
        st.error(f"**Content generation failed:** {result.get('validation_error', '')}")
        st.warning("Check the MCP server logs for details.")

    # ── Success ───────────────────────────────────────────────────────────────

    elif status == "completed":
        persona   = result.get("persona") or "General Audience"
        generated = result.get("generated_content") or {}

        st.success("Brief validated and content generated.")
        st.markdown(f"**Resolved Persona:** {persona}")
        st.divider()

        channels = list(generated.keys())
        if not channels:
            st.warning("No content was generated.")
        else:
            st.subheader("Generated Content")
            channel_tabs = st.tabs(channels)

            for ch_tab, channel in zip(channel_tabs, channels):
                with ch_tab:
                    lang_content = generated.get(channel, {})
                    languages    = list(lang_content.keys())

                    if not languages:
                        st.info("No content for this channel.")
                        continue

                    if len(languages) == 1:
                        _render_content(lang_content[languages[0]], channel)
                    else:
                        lang_tabs = st.tabs(languages)
                        for l_tab, language in zip(lang_tabs, languages):
                            with l_tab:
                                _render_content(lang_content.get(language, {}), channel)

        with st.expander("View submitted brief", expanded=False):
            st.json(brief_dict)

    else:
        st.error(f"Unexpected pipeline status: {status!r}")
