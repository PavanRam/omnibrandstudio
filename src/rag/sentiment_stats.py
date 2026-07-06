"""Aggregate sentiment statistics from sentiment140_clean.csv.

Individual tweets are too short and context-free to be useful as RAG
documents (3-15 words, no product/brand context).  The value of the
sentiment140 dataset lies in *volume* — 16,000 labelled examples whose
aggregate pattern tells you the overall tone landscape.

This module computes those aggregate stats once, caches the result, and
discards the raw DataFrame — so repeated SentimentAnalyzer instantiations
in ContentGenerator cost nothing after the first.

Typical Phase 3 usage
---------------------
    analyzer = SentimentAnalyzer()
    context  = analyzer.tone_signal()   # pass this string to the content generator
    stats    = analyzer.summary()       # full breakdown for dashboards / reports
"""

from pathlib import Path
from typing import Optional

from src.data.loaders import load_csv
from src.rag.config import DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("rag.sentiment_stats")

_SENTIMENT_CSV = DATA_DIR / "sentiment140_clean.csv"

_MONTH_NAMES = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May",  6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}

# Module-level cache — computed once on first use, raw DataFrame is then discarded.
_stats_cache: dict | None = None


def _agg_label(subset) -> dict:
    if subset.empty:
        return {}
    peak_hours  = subset.groupby("hour").size().nlargest(3).index.tolist()
    peak_months = subset.groupby("month").size().nlargest(3).index.tolist()
    return {
        "count":            len(subset),
        "avg_word_count":   round(float(subset["word_count"].mean()), 1),
        "avg_text_length":  round(float(subset["text_length"].mean()), 1),
        "pct_with_mention": round(float(subset["has_mention"].mean()) * 100, 1),
        "pct_with_hashtag": round(float(subset["has_hashtag"].mean()) * 100, 1),
        "pct_with_url":     round(float(subset["has_url"].mean()) * 100, 1),
        "peak_hours":       peak_hours,
        "peak_months":      [_MONTH_NAMES[m] for m in peak_months],
    }


def _load_stats(csv_path: Path) -> dict:
    """Load CSV, compute aggregate stats, cache result, discard DataFrame."""
    global _stats_cache
    if _stats_cache is None:
        df    = load_csv(csv_path)
        total = len(df)
        logger.info(
            "SentimentAnalyzer: computing aggregate stats from %d rows (once) — "
            "raw DataFrame will be released after this.", total,
        )
        neg_df = df[df["sentiment_label"] == "negative"]
        pos_df = df[df["sentiment_label"] == "positive"]
        neg    = len(neg_df)
        pos    = len(pos_df)
        _stats_cache = {
            "overall": {
                "total_feedback": total,
                "negative_count": neg,
                "positive_count": pos,
                "negative_pct":   round(neg / total * 100, 1) if total else 0.0,
                "positive_pct":   round(pos / total * 100, 1) if total else 0.0,
            },
            "negative": _agg_label(neg_df),
            "positive": _agg_label(pos_df),
        }
        logger.info("SentimentAnalyzer: stats cached, DataFrame released.")
    return _stats_cache


class SentimentAnalyzer:
    """Pre-computes aggregate sentiment statistics from the sentiment140 dataset.

    Stats are computed once per process (module-level cache) regardless of
    how many SentimentAnalyzer instances are created.  The raw 15,999-row
    DataFrame is discarded after the first computation.
    """

    def __init__(self, csv_path: Optional[Path] = None) -> None:
        self._stats = _load_stats(csv_path or _SENTIMENT_CSV)

    # ── Public methods ────────────────────────────────────────────────────────

    def overall_stats(self) -> dict:
        """Positive / negative split across all feedback samples."""
        return dict(self._stats["overall"])

    def stats_by_sentiment(self, label: str) -> dict:
        """Behavioural stats for 'positive' or 'negative' feedback."""
        return dict(self._stats.get(label, {}))

    def tone_signal(self) -> str:
        """Single-string sentiment context for LLM prompts in Phase 3.

        Returns a plain-English paragraph that can be appended directly to
        a content generation prompt so the model understands the sentiment
        landscape it is writing for.
        """
        overall   = self._stats["overall"]
        neg_stats = self._stats["negative"]
        pos_stats = self._stats["positive"]

        dominant    = "negative" if overall["negative_pct"] >= 50 else "positive"
        tone_advice = (
            "Use empathetic, reassuring language that acknowledges customer "
            "frustration without amplifying it."
            if dominant == "negative"
            else "Maintain an energetic, affirming tone that reinforces "
                 "positive customer experiences."
        )

        neg_hours = ", ".join(str(h) for h in neg_stats.get("peak_hours", []))
        pos_hours = ", ".join(str(h) for h in pos_stats.get("peak_hours", []))

        return (
            f"Customer sentiment is {overall['negative_pct']}% negative, "
            f"{overall['positive_pct']}% positive "
            f"({overall['total_feedback']:,} feedback samples). "
            f"Negative feedback is short and direct "
            f"(avg {neg_stats.get('avg_word_count', '?')} words), "
            f"with @mentions in {neg_stats.get('pct_with_mention', '?')}% of cases "
            f"— suggesting reactive complaints directed at other users. "
            f"Negative feedback peaks at hours {neg_hours}. "
            f"Positive feedback averages {pos_stats.get('avg_word_count', '?')} words "
            f"and peaks at hours {pos_hours}. "
            f"Recommended tone: {tone_advice}"
        )

    def summary(self) -> dict:
        """Full summary dict — overall breakdown + per-label stats + tone signal."""
        return {
            "overall":     self.overall_stats(),
            "negative":    self.stats_by_sentiment("negative"),
            "positive":    self.stats_by_sentiment("positive"),
            "tone_signal": self.tone_signal(),
        }
