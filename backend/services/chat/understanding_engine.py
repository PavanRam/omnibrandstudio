from __future__ import annotations

import json
from typing import Any

from pipeline.agents.base import traced_llm_call
from pipeline.conversation_models import (
    ExtractionMeta,
    IntentClassification,
    PartialBrief,
    UnderstandingResult,
)
from services.chat.brief_collector import brief_collector
from services.chat.intent_classifier import intent_classifier

# Single merged prompt that performs BOTH intent classification and brief
# extraction in one pass, using conversation history for context. This removes
# the previous two-call design where the brief extractor never saw history and
# could disagree with the intent classifier.
_UNDERSTANDING_PROMPT = (
    "You are the understanding engine for OmniBrand Studio's campaign planning copilot. "
    "On every user turn you do TWO things at once and return a SINGLE strict JSON object.\n"
    "\n"
    "TASK 1 — intent classification. Classify the user's latest message (using the "
    "conversation history for context) into one primary intent and optional secondary intents.\n"
    "Available intents: collect_brief, modify_brief, submit_campaign, check_status, "
    "explain_progress, show_agent_output, view_history, iterate_campaign, rerun_campaign, "
    "ask_product, greeting, other.\n"
    "collect_brief = user is supplying or requesting brief details; "
    "modify_brief = changing existing brief fields; "
    "submit_campaign = explicitly asking to finalize/execute; "
    "check_status/explain_progress/show_agent_output/view_history = campaign monitoring; "
    "iterate_campaign/rerun_campaign = improvement or rerun requests; "
    "ask_product = product capability questions; "
    "greeting = conversational opener with no concrete request.\n"
    "For output requests, if the user asks to see generated content, agent output, step output, "
    "or 'what content_generator produced', classify as show_agent_output (even if the brief is complete).\n"
    "Do not classify campaign-monitoring questions as collect_brief or submit_campaign unless the user "
    "explicitly asks to run/launch/execute the campaign.\n"
    "\n"
    "TASK 2 — brief extraction. Extract ANY campaign brief details present in the latest "
    "message, resolving references against the conversation history and the current brief "
    "already captured. The brief fields are:\n"
    "- objective (string): the concrete outcome the campaign should drive\n"
    "- target_audience (string): who the campaign speaks to\n"
    "- key_messages (string array): the main points to communicate\n"
    "- tone_override (string): explicit tone/voice instruction\n"
    "- channels (string array): e.g. linkedin, email, instagram, landing page\n"
    "- locales (string array): e.g. en-US, en-GB, de-DE\n"
    "- audience_segments (string array): e.g. enterprise, sme, consumer\n"
    "- token_budget (integer): numeric generation budget\n"
    "\n"
    "EXTRACTION RULES:\n"
    "- Understand natural language; do NOT require the user to use 'field: value' syntax. "
    "'we want to drive demo requests' -> objective. 'use LinkedIn and email' -> channels.\n"
    "- If the user pastes JSON, extract values from it directly.\n"
    "- Only include a field when the user actually provided or changed it this turn. "
    "Use null for unknown scalars and [] for unknown arrays. NEVER invent values.\n"
    "- field_confidence: an object with a 0..1 confidence for EACH field you extracted "
    "this turn (higher = more certain the value is correct and complete).\n"
    "\n"
    "Return ONLY this JSON shape (no prose, no markdown fences):\n"
    "{\n"
    '  "intent": {"primary": "...", "secondary": [], "confidence": 0.0, '
    '"requires_action": false, "mutation_intent": false},\n'
    '  "brief": {"objective": null, "target_audience": null, "key_messages": [], '
    '"tone_override": null, "channels": [], "locales": [], "audience_segments": [], '
    '"token_budget": null},\n'
    '  "field_confidence": {}\n'
    "}\n"
    "\n"
    "EXAMPLE\n"
    "Current brief: {\"objective\": null, \"channels\": []}\n"
    "User: We're launching a security add-on and want to drive qualified demo requests "
    "from enterprise IT leaders on LinkedIn and email.\n"
    "Output: {\"intent\": {\"primary\": \"collect_brief\", \"secondary\": [], "
    "\"confidence\": 0.95, \"requires_action\": false, \"mutation_intent\": false}, "
    "\"brief\": {\"objective\": \"drive qualified demo requests\", \"target_audience\": "
    "\"enterprise IT leaders\", \"key_messages\": [], \"tone_override\": null, "
    "\"channels\": [\"linkedin\", \"email\"], \"locales\": [], \"audience_segments\": "
    "[\"enterprise\"], \"token_budget\": null}, \"field_confidence\": {\"objective\": 0.9, "
    "\"target_audience\": 0.88, \"channels\": 0.95, \"audience_segments\": 0.8}}\n"
    "\n"
    "EDGE-CASE EXAMPLES\n"
    "Example 2 (correction turn):\n"
    "Current brief: {\"objective\": \"drive demo requests\", \"channels\": [\"linkedin\"]}\n"
    "User: Actually, make the tone formal, not casual.\n"
    "Output: {\"intent\": {\"primary\": \"modify_brief\", \"secondary\": [], "
    "\"confidence\": 0.95, \"requires_action\": false, \"mutation_intent\": true}, "
    "\"brief\": {\"objective\": null, \"target_audience\": null, \"key_messages\": [], "
    "\"tone_override\": \"formal\", \"channels\": [], \"locales\": [], "
    "\"audience_segments\": [], \"token_budget\": null}, "
    "\"field_confidence\": {\"tone_override\": 0.95}}\n"
    "\n"
    "Example 3 (vague message with an active campaign):\n"
    "Current brief: {\"objective\": \"launch hydration campaign\", \"channels\": [\"email\"]}\n"
    "User: How is it going?\n"
    "Output: {\"intent\": {\"primary\": \"check_status\", \"secondary\": [], "
    "\"confidence\": 0.8, \"requires_action\": false, \"mutation_intent\": false}, "
    "\"brief\": {\"objective\": null, \"target_audience\": null, \"key_messages\": [], "
    "\"tone_override\": null, \"channels\": [], \"locales\": [], \"audience_segments\": [], "
    "\"token_budget\": null}, \"field_confidence\": {}}"
)

_BRIEF_FIELDS = (
    "objective",
    "target_audience",
    "key_messages",
    "tone_override",
    "channels",
    "locales",
    "audience_segments",
    "token_budget",
)


class UnderstandingEngine:
    async def understand(
        self,
        *,
        current: PartialBrief,
        user_message: str,
        conversation_history: list[dict[str, str]],
        state: dict[str, Any],
    ) -> UnderstandingResult:
        shortcut = self._deterministic_shortcut(current, user_message)
        if shortcut is not None:
            return shortcut

        # Deterministic regex extraction is always computed as a safety net and
        # merged with the LLM output so nothing that clearly parses is dropped.
        fallback_patch = brief_collector._fallback_patch_from_text(user_message)
        fallback_confidence = brief_collector._fallback_confidence(fallback_patch)

        intent, patch, meta = await self._call_llm(
            user_message=user_message,
            conversation_history=conversation_history,
            current=current,
            state=state,
        )

        if not patch:
            patch = fallback_patch
            if patch:
                meta = ExtractionMeta(field_confidence=fallback_confidence, source="fallback")
        elif fallback_patch:
            patch = brief_collector._merge_missing_patch_fields(patch, fallback_patch)
            for key, value in fallback_confidence.items():
                meta.field_confidence.setdefault(key, value)

        merged_brief = brief_collector._merge(current, patch, user_message)
        return UnderstandingResult(intent=intent, brief=merged_brief, extraction_meta=meta)

    def _deterministic_shortcut(
        self, current: PartialBrief, user_message: str
    ) -> UnderstandingResult | None:
        normalized = " ".join(user_message.lower().strip().split())
        if not normalized:
            return None

        greetings = {
            "hi",
            "hello",
            "hey",
            "yo",
            "hiya",
            "good morning",
            "good afternoon",
            "good evening",
        }
        smalltalk = {"thanks", "thank you", "ok", "okay", "cool", "sounds good"}

        # A short greeting/smalltalk that carries no brief signal never needs an
        # LLM call and must not disturb the already-captured brief.
        if normalized in greetings and not brief_collector._has_brief_signal(user_message):
            intent = IntentClassification(
                primary="greeting",
                secondary=[],
                confidence=1.0,
                requires_action=False,
                mutation_intent=False,
            )
            merged = brief_collector._merge(current, {}, user_message)
            return UnderstandingResult(
                intent=intent,
                brief=merged,
                extraction_meta=ExtractionMeta(field_confidence={}, source="shortcut"),
            )

        if normalized in smalltalk and not brief_collector._has_brief_signal(user_message):
            intent = IntentClassification(
                primary="other",
                secondary=[],
                confidence=0.6,
                requires_action=False,
                mutation_intent=False,
            )
            merged = brief_collector._merge(current, {}, user_message)
            return UnderstandingResult(
                intent=intent,
                brief=merged,
                extraction_meta=ExtractionMeta(field_confidence={}, source="shortcut"),
            )

        return None

    async def _call_llm(
        self,
        *,
        user_message: str,
        conversation_history: list[dict[str, str]],
        current: PartialBrief,
        state: dict[str, Any],
    ) -> tuple[IntentClassification, dict[str, Any], ExtractionMeta]:
        history = conversation_history[-8:]
        history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history)
        current_brief_json = json.dumps(
            {field: getattr(current, field) for field in _BRIEF_FIELDS},
            ensure_ascii=True,
        )
        user_payload = (
            f"Current brief (already captured):\n{current_brief_json}\n\n"
            f"Conversation history:\n{history_text or '(none)'}\n\n"
            f"Latest message:\n{user_message}"
        )

        content, _ = await traced_llm_call(
            model=state.get("model_aliases", {}).get("understanding", "understanding"),
            messages=[
                {"role": "system", "content": _UNDERSTANDING_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            task="understanding_engine",
            state=state,
            temperature=0,
        )

        return self._parse(content)

    def _parse(
        self, content: str
    ) -> tuple[IntentClassification, dict[str, Any], ExtractionMeta]:
        parsed = self._loads(content)

        intent_raw = parsed.get("intent")
        if isinstance(intent_raw, dict):
            intent = intent_classifier._parse_classification(json.dumps(intent_raw))
        else:
            intent = IntentClassification(primary="other", secondary=[], confidence=0.0)

        brief_raw = parsed.get("brief")
        patch: dict[str, Any] = {}
        if isinstance(brief_raw, dict):
            for field in _BRIEF_FIELDS:
                if field not in brief_raw:
                    continue
                value = brief_raw[field]
                if value is None:
                    continue
                if isinstance(value, list) and not value:
                    continue
                patch[field] = value

        confidence: dict[str, float] = {}
        raw_conf = parsed.get("field_confidence", {})
        if isinstance(raw_conf, dict):
            for key, value in raw_conf.items():
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                if str(key) in _BRIEF_FIELDS:
                    confidence[str(key)] = max(0.0, min(1.0, numeric))

        return intent, patch, ExtractionMeta(field_confidence=confidence, source="llm")

    def _loads(self, content: str) -> dict[str, Any]:
        text = (content or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Tolerate models that wrap JSON in prose or code fences by extracting
        # the outermost JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(text[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        return {}


understanding_engine = UnderstandingEngine()
