"""Unit tests for pipeline/initial_state.py::resolve_model_aliases()."""
from __future__ import annotations

from core.config import settings
from pipeline.initial_state import resolve_model_aliases


def test_personalization_key_present_in_both_tiers():
    free_aliases = resolve_model_aliases("free")
    paid_aliases = resolve_model_aliases("paid")

    assert free_aliases["personalization"] == free_aliases["generation"]
    assert paid_aliases["personalization"] == paid_aliases["generation"]


def test_override_replaces_only_its_own_key(monkeypatch):
    monkeypatch.setattr(settings, "JUDGE_1_MODEL_ALIAS", "custom-judge-1")

    aliases = resolve_model_aliases("free")

    assert aliases["judge-1"] == "custom-judge-1"
    assert aliases["judge-2"] == "judge-2-free"
    assert aliases["generation"] == "gen-free"
