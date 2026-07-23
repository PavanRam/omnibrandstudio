from __future__ import annotations

import json
from typing import Any

from pipeline.agents.base import traced_llm_call
from pipeline.conversation_models import IntentClassification, UserIntent

_PROMPT = (
    "You are an intent classifier for OmniBrand Studio's campaign planning copilot. "
    "Classify the user's latest message using conversation context into one primary intent and optional secondary intents. "
    "Return strict JSON only: "
    "{\"primary\": \"...\", \"secondary\": [...], \"confidence\": 0.0, \"requires_action\": false, \"mutation_intent\": false}. "
    "Available intents: collect_brief, modify_brief, submit_campaign, check_status, explain_progress, "
    "show_agent_output, view_history, iterate_campaign, rerun_campaign, ask_product, greeting, other. "
    "Intent guidance: "
    "collect_brief means the user is supplying or requesting campaign brief details; "
    "modify_brief means changing existing brief fields; "
    "submit_campaign means explicitly asking to finalize or execute the campaign; "
    "check_status/explain_progress/show_agent_output/view_history are campaign monitoring intents; "
    "iterate_campaign/rerun_campaign are improvement or rerun requests for outputs/pipeline; "
    "ask_product is product capability/workflow questions; "
    "greeting is a conversational opener with no concrete campaign request. "
    "Rules: use latest message plus history; infer user goal, not keywords alone; "
    "set strongest goal as primary and place additional goals in secondary; "
    "set requires_action=true when user asks the system to do something; "
    "set mutation_intent=true when the user asks to change brief data, campaign execution state, or generated assets; "
    "do not invent facts and return valid JSON only."
)


class IntentClassifier:
    async def classify_detailed(
        self,
        *,
        message: str,
        conversation_history: list[dict[str, str]],
        state: dict[str, Any],
    ) -> IntentClassification:
        normalized = " ".join(message.lower().strip().split())
        if normalized in {
            "hi",
            "hello",
            "hey",
            "yo",
            "hiya",
            "good morning",
            "good afternoon",
            "good evening",
        }:
            return IntentClassification(
                primary="greeting",
                secondary=[],
                confidence=1.0,
                requires_action=False,
                mutation_intent=False,
            )

        if normalized in {
            "thanks",
            "thank you",
            "ok",
            "okay",
            "cool",
            "sounds good",
        }:
            return IntentClassification(
                primary="other",
                secondary=[],
                confidence=0.6,
                requires_action=False,
                mutation_intent=False,
            )

        history = conversation_history[-8:]
        history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history)
        content, _ = await traced_llm_call(
            model=state.get("model_aliases", {}).get("utility", "util-fast"),
            messages=[
                {"role": "system", "content": _PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"History:\n{history_text or '(none)'}\n\n"
                        f"Latest message:\n{message}"
                    ),
                },
            ],
            task="intent_classifier",
            state=state,
            temperature=0,
        )
        return self._parse_classification(content)

    async def classify(
        self,
        *,
        message: str,
        conversation_history: list[dict[str, str]],
        state: dict[str, Any],
    ) -> UserIntent:
        classification = await self.classify_detailed(
            message=message,
            conversation_history=conversation_history,
            state=state,
        )
        return classification.primary

    def _parse_classification(self, content: str) -> IntentClassification:
        allowed = {
            "collect_brief",
            "modify_brief",
            "submit_campaign",
            "check_status",
            "explain_progress",
            "show_agent_output",
            "rerun_campaign",
            "view_history",
            "iterate_campaign",
            "ask_product",
            "greeting",
            "other",
        }

        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"primary": content.strip().lower(), "secondary": [], "confidence": 0.0}

        primary = str(parsed.get("primary", parsed.get("intent", "other"))).strip().lower()
        if primary not in allowed:
            primary = "other"

        secondary_raw = parsed.get("secondary", [])
        secondary: list[UserIntent] = []
        if isinstance(secondary_raw, list):
            for candidate in secondary_raw:
                intent = str(candidate).strip().lower()
                if intent in allowed and intent != primary:
                    secondary.append(intent)  # type: ignore[arg-type]

        requires_action = self._coerce_bool(parsed.get("requires_action"), default=False)
        mutation_intent = self._coerce_bool(parsed.get("mutation_intent"), default=False)

        if primary == "submit_campaign" or "submit_campaign" in secondary:
            requires_action = True

        mutation_intents = {"modify_brief", "iterate_campaign", "rerun_campaign"}
        if primary in mutation_intents or any(intent in mutation_intents for intent in secondary):
            mutation_intent = True

        confidence_value = parsed.get("confidence", 0.0)
        try:
            confidence = float(confidence_value)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        return IntentClassification(
            primary=primary,  # type: ignore[arg-type]
            secondary=secondary,
            confidence=confidence,
            requires_action=requires_action,
            mutation_intent=mutation_intent,
        )

    def _coerce_bool(self, value: object, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    def _parse_intent(self, content: str) -> UserIntent:
        return self._parse_classification(content).primary


intent_classifier = IntentClassifier()
