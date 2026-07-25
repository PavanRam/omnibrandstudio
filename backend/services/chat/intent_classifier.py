from __future__ import annotations

import json

from pipeline.conversation_models import IntentClassification, UserIntent


class IntentClassifier:
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
