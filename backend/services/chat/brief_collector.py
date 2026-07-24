from __future__ import annotations

import json
import re
from typing import Any

from pipeline.agents.base import traced_llm_call
from pipeline.conversation_models import ExtractionMeta, PartialBrief

_EXTRACTION_PROMPT = (
    "Extract structured campaign brief updates from the user message. "
    "Return strict JSON with keys: objective, target_audience, key_messages, tone_override, "
    "channels, locales, audience_segments, token_budget, raw_text, field_confidence. "
    "field_confidence must be an object with numeric 0..1 confidence for extracted fields. "
    "Use null for unknown scalars and [] for unknown arrays."
)
_STRIP_CHARS = " \t\r\n\"'"
_LLM_CONFIDENCE_THRESHOLD = 0.8


class BriefCollector:
    async def update_partial_brief_with_meta(
        self,
        *,
        current: PartialBrief,
        user_message: str,
        state: dict[str, Any],
    ) -> tuple[PartialBrief, ExtractionMeta]:
        if self._is_non_brief_turn(user_message):
            merged = self._merge(current, {}, user_message)
            return merged, ExtractionMeta(field_confidence={}, source="non_brief")

        fallback_patch = self._fallback_patch_from_text(user_message)
        fallback_confidence = self._fallback_confidence(fallback_patch)

        content, _ = await traced_llm_call(
            model=state.get("model_aliases", {}).get("brief_collector", "brief-collector"),
            messages=[
                {"role": "system", "content": _EXTRACTION_PROMPT},
                {"role": "user", "content": user_message},
            ],
            task="brief_collector",
            state=state,
            temperature=0,
        )

        patch, meta = self._parse_patch_with_meta(content)
        if not patch:
            patch = fallback_patch
            meta = ExtractionMeta(field_confidence=fallback_confidence, source="fallback")
        elif fallback_patch:
            patch = self._merge_missing_patch_fields(patch, fallback_patch)
            for key, value in fallback_confidence.items():
                meta.field_confidence.setdefault(key, value)

        patch = self._ground_patch(
            llm_patch=patch,
            fallback_patch=fallback_patch,
            confidence=meta.field_confidence,
            user_message=user_message,
        )

        if not patch and user_message.strip() and not self._is_non_brief_turn(user_message):
            patch = {"key_messages": [user_message.strip()]}
            meta.field_confidence.setdefault("key_messages", 0.7)

        merged = self._merge(current, patch, user_message)
        return merged, meta

    def _ground_patch(
        self,
        *,
        llm_patch: dict[str, Any],
        fallback_patch: dict[str, Any],
        confidence: dict[str, float],
        user_message: str,
    ) -> dict[str, Any]:
        grounded: dict[str, Any] = {}

        for field in ("channels", "locales", "audience_segments", "token_budget"):
            if field in fallback_patch:
                grounded[field] = fallback_patch[field]

        for field in ("objective", "target_audience", "tone_override", "key_messages"):
            if field in fallback_patch:
                grounded[field] = fallback_patch[field]
                continue

            value = llm_patch.get(field)
            if not self._has_patch_value(value):
                continue

            field_confidence = confidence.get(field, 0.0)
            if field_confidence >= _LLM_CONFIDENCE_THRESHOLD and self._message_has_signal(user_message):
                grounded[field] = value

        return grounded

    def _has_patch_value(self, value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, list):
            return len(value) > 0
        if isinstance(value, int):
            return value > 0
        return True

    def _message_has_signal(self, text: str) -> bool:
        normalized = text.strip()
        if not normalized:
            return False

        words = [w for w in re.split(r"\s+", normalized) if w]
        return len(words) >= 4 or ":" in normalized or "," in normalized

    async def update_partial_brief(
        self,
        *,
        current: PartialBrief,
        user_message: str,
        state: dict[str, Any],
    ) -> PartialBrief:
        merged, _ = await self.update_partial_brief_with_meta(
            current=current,
            user_message=user_message,
            state=state,
        )
        return merged

    def _parse_patch_with_meta(self, content: str) -> tuple[dict[str, Any], ExtractionMeta]:
        parsed = self._parse_patch(content)
        if not parsed:
            return {}, ExtractionMeta(field_confidence={}, source="llm")

        raw_conf = parsed.pop("field_confidence", {})
        confidence: dict[str, float] = {}
        if isinstance(raw_conf, dict):
            for key, value in raw_conf.items():
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    continue
                confidence[str(key)] = max(0.0, min(1.0, numeric))

        return parsed, ExtractionMeta(field_confidence=confidence, source="llm")

    def next_question(self, brief: PartialBrief) -> str:
        missing = brief.missing_slots()
        if not missing:
            return "Great, your brief is complete. Say 'run campaign' to start execution."

        question_by_slot = {
            "objective": "What is the primary campaign objective?",
            "channels": "Which channels should we target?",
            "locales": "Which locales should we generate content for?",
            "audience_segments": "Which audience segments should we target?",
            "token_budget": "What token budget should we use for this campaign?",
        }
        slot = missing[0]
        return question_by_slot.get(slot, "Please provide the missing campaign details.")

    def _parse_patch(self, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {}

    def _is_non_brief_turn(self, text: str) -> bool:
        normalized = " ".join(text.lower().strip().split())
        if not normalized:
            return True

        if self._has_brief_signal(text):
            return False

        exact_smalltalk = {
            "hi",
            "hello",
            "hey",
            "yo",
            "thanks",
            "thank you",
            "ok",
            "okay",
            "cool",
            "sounds good",
            "good morning",
            "good afternoon",
            "good evening",
        }
        if normalized in exact_smalltalk:
            return True

        control_phrases = (
            "run campaign",
            "check status",
            "current campaign status",
            "what happened in the last step",
            "show outputs",
            "show output",
            "rerun",
        )
        return any(phrase in normalized for phrase in control_phrases)

    def _has_brief_signal(self, text: str) -> bool:
        normalized = text.strip()
        lowered = normalized.lower()

        explicit_markers = (
            "objective:",
            "target audience:",
            "target_audience:",
            "key messages:",
            "tone:",
            "tone override:",
            "channels:",
            "locales:",
            "audience segment:",
            "audience segments:",
            "token budget:",
        )
        if any(marker in lowered for marker in explicit_markers):
            return True

        return bool(self._fallback_patch_from_text(normalized))

    def _fallback_confidence(self, patch: dict[str, Any]) -> dict[str, float]:
        return {
            key: 0.65
            for key in patch
            if key
            in {
                "objective",
                "target_audience",
                "key_messages",
                "tone_override",
                "channels",
                "locales",
                "audience_segments",
                "token_budget",
            }
        }

    def _merge_missing_patch_fields(
        self,
        primary_patch: dict[str, Any],
        fallback_patch: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(primary_patch)

        for key in ("objective", "target_audience", "tone_override", "token_budget"):
            if merged.get(key) is None and fallback_patch.get(key) is not None:
                merged[key] = fallback_patch[key]

        for key in ("key_messages", "channels", "locales", "audience_segments"):
            value = merged.get(key)
            if isinstance(value, list) and value:
                continue
            fallback_value = fallback_patch.get(key)
            if isinstance(fallback_value, list) and fallback_value:
                merged[key] = fallback_value

        return merged

    def _fallback_patch_from_text(self, text: str) -> dict[str, Any]:
        normalized = text.strip()
        lowered = normalized.lower()
        patch: dict[str, Any] = {}

        objective = self._extract_objective(normalized)
        if objective:
            patch["objective"] = objective

        audience_segments = self._extract_audience_segments(normalized)
        if audience_segments:
            patch["audience_segments"] = audience_segments

        token_budget = self._extract_token_budget(normalized)
        if token_budget is not None:
            patch["token_budget"] = token_budget

        patch.update(self._extract_explicit_list_fields(normalized))

        if "channels" not in patch:
            inferred_channels = self._infer_channels(lowered)
            if inferred_channels:
                patch["channels"] = inferred_channels

        if "locales" not in patch:
            inferred_locales = self._infer_locales(normalized)
            if inferred_locales:
                patch["locales"] = inferred_locales

        if "audience_segments" not in patch:
            inferred_segments = self._infer_audience_segments(lowered)
            if inferred_segments:
                patch["audience_segments"] = inferred_segments

        return patch

    def _extract_objective(self, normalized: str) -> str | None:
        patterns = (
            r"(?:^|\b)(?:objective\s*:\s*|primary campaign objective is to\s+|primary campaign objective is\s+)([^\.!?\n]+)",
            r"(?:^|\b)(?:the\s+)?(?:absolute\s+)?(?:first\s+)?concrete outcome(?:\s+this campaign)?\s+must\s+drive(?:\s+first)?\s+is\s+([^\.!?\n]+)",
            r"(?:^|\b)(?:the\s+)?(?:primary|main)\s+outcome\s+is\s+([^\.!?\n]+)",
            r"(?:^|\b)(?:we\s+need\s+to\s+drive|this campaign should drive)\s+([^\.!?\n]+)",
        )
        for pattern in patterns:
            objective_match = re.search(pattern, normalized, re.IGNORECASE)
            if not objective_match:
                continue
            objective = objective_match.group(1).strip(_STRIP_CHARS)
            if objective:
                return objective
        return None

    def _extract_audience_segments(self, normalized: str) -> list[str]:
        patterns = (
            r"(?:^|\b)(?:audience segments?\s*:\s*)([^\.!?\n]+)",
            r"(?:^|\b)(?:target audience\s*:\s*|we want to reach\s+|we need to reach\s+)([^\.!?\n]+)",
            r"(?:^|\b)(?:target|reach|prioritize)\s+([^\.!?\n]+(?:\s+buyers|\s+leaders|\s+teams|\s+customers|\s+audiences?))",
        )
        for pattern in patterns:
            audience_match = re.search(pattern, normalized, re.IGNORECASE)
            if not audience_match:
                continue
            raw_value = audience_match.group(1).strip(_STRIP_CHARS)
            if not raw_value:
                continue
            if "," in raw_value:
                values = [item.strip(_STRIP_CHARS) for item in raw_value.split(",")]
                values = [item for item in values if item]
                if values:
                    return values
            return [raw_value]
        return []

    def _extract_token_budget(self, normalized: str) -> int | None:
        token_budget_match = re.search(
            r"(?:token budget\s*:\s*|token budget should be\s+|token budget is\s+)(\d+)",
            normalized,
            re.IGNORECASE,
        )
        if not token_budget_match:
            return None
        return int(token_budget_match.group(1))

    def _extract_explicit_list_fields(self, normalized: str) -> dict[str, list[str]]:
        extracted: dict[str, list[str]] = {}
        list_patterns = {
            "channels": r"channels?\s*:\s*([^\.\n]+)",
            "locales": r"locales?\s*:\s*([^\.\n]+)",
            "audience_segments": r"audience segments?\s*:\s*([^\.\n]+)",
            "key_messages": r"key messages?\s*:\s*([^\.\n]+)",
        }
        for field, pattern in list_patterns.items():
            match = re.search(pattern, normalized, re.IGNORECASE)
            if not match:
                continue
            items = [item.strip(" \t\r\n\"'") for item in match.group(1).split(",")]
            values = [item for item in items if item]
            if values:
                extracted[field] = values
        return extracted

    def _infer_channels(self, lowered: str) -> list[str]:
        inferred_channels = []
        for channel in ("linkedin", "email", "instagram", "facebook", "twitter", "whatsapp", "landing page"):
            if re.search(rf"\b{channel}\b", lowered):
                inferred_channels.append(channel)
        return inferred_channels

    def _infer_locales(self, normalized: str) -> list[str]:
        return re.findall(r"\b[a-z]{2}-[A-Z]{2}\b", normalized)

    def _infer_audience_segments(self, lowered: str) -> list[str]:
        inferred_segments = []
        for segment in ("enterprise", "sme", "consumer"):
            if re.search(rf"\b{segment}\b", lowered):
                inferred_segments.append(segment)
        return inferred_segments

    def _merge(self, current: PartialBrief, patch: dict[str, Any], raw_text: str) -> PartialBrief:
        data = current.model_dump()
        for key in (
            "objective",
            "target_audience",
            "tone_override",
            "token_budget",
        ):
            value = patch.get(key)
            if value is not None:
                data[key] = value

        for key in ("key_messages", "channels", "locales", "audience_segments"):
            value = patch.get(key)
            if isinstance(value, list) and value:
                data[key] = [str(v) for v in value]

        existing_raw = str(data.get("raw_text", "")).strip()
        if existing_raw:
            data["raw_text"] = f"{existing_raw}\n{raw_text}"[-4000:]
        else:
            data["raw_text"] = raw_text[-4000:]

        return PartialBrief.model_validate(data)


brief_collector = BriefCollector()
