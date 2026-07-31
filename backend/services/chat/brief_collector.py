from __future__ import annotations

import json
import re
from typing import Any

from pipeline.agents.base import traced_llm_call
from pipeline.agents.prompts.channel_prompts import DEFAULT_CHANNEL_CONSTRAINTS
from pipeline.conversation_models import ExtractionMeta, PartialBrief
from pipeline.locale_utils import is_locale_supported, normalize_locale

_EXTRACTION_PROMPT = (
    "Extract structured campaign brief updates from the user message. "
    "Return strict JSON with keys: objective, target_audience, key_messages, tone_override, "
    "channels, locales, audience_segments, token_budget, end_date, raw_text, field_confidence. "
    "end_date is an OPTIONAL campaign validity/expiry date (e.g. 'runs through March 31') — "
    "never required, never blocks anything. "
    "field_confidence must be an object with numeric 0..1 confidence for extracted fields. "
    "Use null for unknown scalars and [] for unknown arrays."
)
_STRIP_CHARS = " \t\r\n\"'"


class BriefCollector:
    async def update_partial_brief_with_meta(
        self,
        *,
        current: PartialBrief,
        user_message: str,
        state: dict[str, Any],
    ) -> tuple[PartialBrief, ExtractionMeta]:
        if self._is_non_brief_turn(user_message):
            merged, _ = self._merge(current, {}, user_message)
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

        merged, rejected = self._merge(current, patch, user_message)
        meta.rejected = rejected
        return merged, meta

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

        slot = missing[0]
        # token_budget removed from missing_slots() (2026-07-29) — no longer asked from users.

        question_by_slot = {
            "objective": "What is the primary campaign objective?",
            "channels": "Which channels should we target?",
            "locales": "Which locales should we generate content for?",
            "audience_segments": "Which audience segments should we target?",
        }
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
                "end_date",
            }
        }

    def _merge_missing_patch_fields(
        self,
        primary_patch: dict[str, Any],
        fallback_patch: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(primary_patch)

        for key in ("objective", "target_audience", "tone_override", "token_budget", "end_date"):
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

        end_date = self._extract_end_date(normalized)
        if end_date:
            patch["end_date"] = end_date

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

    def _extract_end_date(self, normalized: str) -> str | None:
        """Optional campaign validity/expiry date — 'runs through March 31',
        'valid until 2026-08-15', 'ends on Friday'. Extracted verbatim in
        whatever form the user stated it, never required."""
        patterns = (
            r"(?:^|\b)(?:end date\s*:\s*)([^\.!?\n]+)",
            r"(?:^|\b)(?:runs?|valid|good)\s+(?:through|until|till)\s+([^\.!?\n]+)",
            r"(?:^|\b)ends?\s+(?:on|by)\s+([^\.!?\n]+)",
            r"(?:^|\b)expires?\s+(?:on|by)?\s*([^\.!?\n]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip(_STRIP_CHARS)
            if value:
                return value
        return None

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

    def _merge(
        self, current: PartialBrief, patch: dict[str, Any], raw_text: str
    ) -> tuple[PartialBrief, dict[str, list[str]]]:
        """Merge an extraction patch into the current brief.

        Returns (merged_brief, rejected) — `rejected` maps field name to the
        values from THIS patch that were dropped rather than written into the
        brief: unsupported channels/locales, or any audience_segments value at
        all (see below). Callers surface this to the user instead of silently
        ignoring what they said (next_tasks.md item 23d, 2026-07-27).
        """
        rejected: dict[str, list[str]] = {}

        data = current.model_dump()
        for key in (
            "objective",
            "target_audience",
            "tone_override",
            "token_budget",
            "end_date",
        ):
            value = patch.get(key)
            if value is not None:
                data[key] = value

        value = patch.get("key_messages")
        if isinstance(value, list) and value:
            data["key_messages"] = [str(v) for v in value]

        channels_patch = patch.get("channels")
        if isinstance(channels_patch, list) and channels_patch:
            normalized = [str(v).strip().lower() for v in channels_patch]
            valid = [c for c in normalized if c in DEFAULT_CHANNEL_CONSTRAINTS]
            invalid = [c for c in normalized if c not in DEFAULT_CHANNEL_CONSTRAINTS]
            if valid:
                data["channels"] = valid
            if invalid:
                rejected["channels"] = invalid

        locales_patch = patch.get("locales")
        if isinstance(locales_patch, list) and locales_patch:
            # Normalize once here — the single choke point every locales value
            # funnels through (LLM extraction and the regex fallback both end
            # up in this same merge), so RAG retrieval, translation's
            # SUPPORTED_LOCALES gate, and channel prompts all see the same
            # canonical form regardless of how the brief was phrased. See
            # pipeline/locale_utils.py.
            normalized = [normalize_locale(str(v)) for v in locales_patch]
            valid = [loc for loc in normalized if is_locale_supported(loc)]
            invalid = [
                str(orig)
                for orig, norm in zip(locales_patch, normalized)
                if not is_locale_supported(norm)
            ]
            if valid:
                data["locales"] = valid
            if invalid:
                rejected["locales"] = invalid

        # audience_segments is picker-only (2026-07-27) — real segments must
        # match the brand's actual seeded persona data (surfaced via the
        # structured picker / set_brief_field), never a free-text guess. The
        # previous backstop here treated any raw reply as a segment label to
        # avoid an infinite re-ask loop; that's no longer needed since the
        # picker now handles this slot directly. If the user names one in
        # free text anyway, note it as rejected (so the assistant can point
        # them at the picker) but never write it into the brief.
        segments_patch = patch.get("audience_segments")
        if isinstance(segments_patch, list) and segments_patch:
            # Only flag values that aren't already a selected segment. The
            # understanding engine re-echoes captured segments from history on
            # later turns (incl. the bare "yes" confirmation), and re-flagging
            # an already-valid picker selection fired the heads-up on every
            # turn after selection.
            already_selected = {
                str(s).strip().lower() for s in data.get("audience_segments", []) if s
            }
            new_free_text = [
                str(v) for v in segments_patch if str(v).strip().lower() not in already_selected
            ]
            if new_free_text:
                rejected["audience_segments"] = new_free_text

        existing_raw = str(data.get("raw_text", "")).strip()
        if existing_raw:
            data["raw_text"] = f"{existing_raw}\n{raw_text}"[-4000:]
        else:
            data["raw_text"] = raw_text[-4000:]

        return PartialBrief.model_validate(data), rejected


brief_collector = BriefCollector()
