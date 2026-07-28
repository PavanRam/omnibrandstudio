"""
Stage 4 EDA: Sentiment140 Dataset
Source: kazanova/sentiment140 (Kaggle)
Format: CSV with no header, 6 columns, ~1.6M rows, latin-1 encoded

Columns (no header in raw file):
  polarity  — 0 = negative, 4 = positive
  id        — tweet ID
  date      — tweet timestamp (e.g. "Mon Apr 06 22:19:45 PDT 2009")
  query     — search query used (mostly NO_QUERY)
  user      — Twitter username
  text      — raw tweet text

Sampling strategy: 1% stratified by polarity (~16,000 rows)
Stratification ensures equal positive/negative representation.

Engineered features:
  - sentiment_label   = "positive" / "negative" (mapped from polarity)
  - sentiment_binary  = 0 / 1
  - text_clean        = URL + mention stripped text (for analysis; original kept for RAG)
  - text_length       = character count of original text
  - word_count        = word count of original text
  - has_mention       = 1 if tweet contains @user, else 0
  - has_hashtag       = 1 if tweet contains #tag, else 0
  - has_url           = 1 if tweet contains a URL, else 0
  - year, month, hour = extracted from parsed date

Output: datasets/processed/sentiment140_clean.csv
Charts: outputs/reports/eda_sentiment140.png
"""

import re
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import warnings

warnings.filterwarnings("ignore")

# ── Schema & Validation ────────────────────────────────────────────────────────
SCHEMA = {
    "expected_columns": ["polarity", "id", "date", "query", "user", "text"],
    "numeric_columns":  ["polarity", "id"],
    "valid_values": {
        "polarity": [0, 4],
    },
    "null_threshold": {
        "text": 0.01,
    },
    "min_rows": 500000,
}


def validate_schema(df, schema, dataset_name="dataset"):
    errors        = []
    warnings_list = []

    # 1. Column presence
    missing = set(schema.get("expected_columns", [])) - set(df.columns)
    extra   = set(df.columns) - set(schema.get("expected_columns", []))
    if missing:
        errors.append(f"Missing columns         : {sorted(missing)}")
    if extra:
        warnings_list.append(f"Extra columns (not in schema): {sorted(extra)}")

    # 2. Minimum row count
    if len(df) < schema.get("min_rows", 0):
        errors.append(f"Row count {len(df)} is below minimum expected {schema['min_rows']}")

    # 3. Numeric column type
    for col in schema.get("numeric_columns", []):
        if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
            errors.append(f"Column '{col}' expected numeric, got {df[col].dtype}")

    # 4. Categorical value validation
    for col, valid in schema.get("categorical_columns", {}).items():
        if col in df.columns:
            unexpected = set(df[col].dropna().unique()) - set(valid)
            if unexpected:
                warnings_list.append(f"Column '{col}' has unexpected values: {unexpected}")

    # 5. Value range validation
    for col, (lo, hi) in schema.get("value_ranges", {}).items():
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            if lo is not None and df[col].min() < lo:
                errors.append(f"Column '{col}' min={df[col].min()} below expected {lo}")
            if hi is not None and df[col].max() > hi:
                errors.append(f"Column '{col}' max={df[col].max()} exceeds expected {hi}")

    # 6. Binary column validation (0/1 only)
    for col in schema.get("binary_columns", []):
        if col in df.columns:
            unique_vals = set(df[col].dropna().unique())
            if not unique_vals.issubset({0, 1}):
                errors.append(f"Column '{col}' expected binary 0/1, got: {unique_vals}")

    # 7. Null threshold validation
    for col, threshold in schema.get("null_threshold", {}).items():
        if col in df.columns:
            null_pct = df[col].isnull().mean()
            if null_pct > threshold:
                errors.append(
                    f"Column '{col}' null% {null_pct:.2%} exceeds allowed {threshold:.2%}"
                )

    # 8. Valid specific values (for numeric categoricals)
    for col, valid_vals in schema.get("valid_values", {}).items():
        if col in df.columns:
            unexpected = set(df[col].dropna().unique()) - set(valid_vals)
            if unexpected:
                errors.append(
                    f"Column '{col}' has invalid values: {unexpected} — expected {set(valid_vals)}"
                )

    # Report
    print(f"\nSchema Validation — {dataset_name}")
    print("-" * 40)
    for w in warnings_list:
        print(f"  [WARNING] {w}")
    if errors:
        for e in errors:
            print(f"  [ERROR]   {e}")
        raise ValueError(
            f"Schema validation FAILED for '{dataset_name}'. Fix errors above before proceeding."
        )
    print(f"  [PASSED]  {len(df)} rows × {len(df.columns)} cols — all checks passed.")


# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "datasets" / "raw" / "training.1600000.processed.noemoticon.csv"
OUT_PATH = ROOT / "datasets" / "processed" / "sentiment140_clean.csv"
FIG_PATH = ROOT / "outputs" / "reports"

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
FIG_PATH.mkdir(parents=True, exist_ok=True)

COL_NAMES = ["polarity", "id", "date", "query", "user", "text"]

# ── 1. Load & Stratified Sample ───────────────────────────────────────────────
print("=" * 60)
print("1. LOADING & STRATIFIED SAMPLING (1%)")
print("=" * 60)

df_raw = pd.read_csv(RAW_PATH, header=None, names=COL_NAMES, encoding="latin-1")
validate_schema(df_raw, SCHEMA, "sentiment140.csv")
print(f"Full dataset shape : {df_raw.shape}")
print(f"Polarity distribution:\n{df_raw['polarity'].value_counts().to_string()}")

frames = []
for pol in df_raw["polarity"].unique():
    subset = df_raw[df_raw["polarity"] == pol]
    frames.append(subset.sample(frac=0.01, random_state=42))
df = pd.concat(frames, ignore_index=True)

print(f"\n1% stratified sample shape : {df.shape}")
print(f"Polarity distribution in sample:\n{df['polarity'].value_counts().to_string()}")
print(f"\nDtypes:\n{df.dtypes.to_string()}")
print(f"\nNull counts (non-zero only):\n{df.isnull().sum()[df.isnull().sum() > 0].to_string()}")
print(f"\nDuplicate rows: {df.duplicated().sum()}")
print(f"\nSample (3 rows):\n{df[['polarity', 'date', 'user', 'text']].head(3).to_string()}")

# ── 2. Cleaning ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. CLEANING")
print("=" * 60)

# Remove duplicates
before = len(df)
df.drop_duplicates(inplace=True)
print(f"Removed {before - len(df)} duplicate rows.")

# Drop rows with null or empty text
before = len(df)
df = df[df["text"].notna() & (df["text"].str.strip() != "")].copy()
print(f"Dropped {before - len(df)} rows with null/empty text. Remaining: {len(df)}")

# Drop query column — contains mostly NO_QUERY, no signal
df.drop(columns=["query"], inplace=True)
print("Dropped 'query' column (mostly NO_QUERY — no signal).")

# Parse date — strip timezone abbreviation before parsing
df["date_parsed"] = pd.to_datetime(
    df["date"].str.replace(r"\s+(PDT|PST|EDT|EST)\s+", " ", regex=True),
    format="%a %b %d %H:%M:%S %Y",
    errors="coerce"
)
null_dates = df["date_parsed"].isnull().sum()
print(f"Date parse failures (coerced to NaT): {null_dates}")

# ── 3. Feature Engineering ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. FEATURE ENGINEERING")
print("=" * 60)

# Sentiment label and binary flag
df["sentiment_label"]  = df["polarity"].map({0: "negative", 4: "positive"})
df["sentiment_binary"] = df["polarity"].map({0: 0, 4: 1})

# Text signals — computed on original text before cleaning
df["text_length"]  = df["text"].str.len()
df["word_count"]   = df["text"].str.split().str.len()
df["has_mention"]  = df["text"].str.contains(r"@\w+",         regex=True).astype(int)
df["has_hashtag"]  = df["text"].str.contains(r"#\w+",         regex=True).astype(int)
df["has_url"]      = df["text"].str.contains(r"http\S+|www\S+", regex=True).astype(int)

# Clean text — strip URLs, mentions, extra whitespace (kept separate for RAG use)
def clean_text(raw):
    t = re.sub(r"http\S+|www\S+", "", str(raw))
    t = re.sub(r"@\w+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

df["text_clean"] = df["text"].apply(clean_text)

# Temporal features
df["year"]  = df["date_parsed"].dt.year
df["month"] = df["date_parsed"].dt.month
df["hour"]  = df["date_parsed"].dt.hour

# Text length outlier filter — tweets should be 1–280 chars
before = len(df)
df = df[(df["text_length"] >= 1) & (df["text_length"] <= 280)].copy()
print(f"Removed {before - len(df)} text length outliers.")

print(f"\nSentiment split:\n{df['sentiment_label'].value_counts().to_string()}")
print(f"\nAvg text length  : {df['text_length'].mean():.1f} chars")
print(f"Avg word count   : {df['word_count'].mean():.1f} words")
print(f"Has mention      : {df['has_mention'].mean()*100:.1f}% of tweets")
print(f"Has hashtag      : {df['has_hashtag'].mean()*100:.1f}% of tweets")
print(f"Has URL          : {df['has_url'].mean()*100:.1f}% of tweets")
print(f"Year range       : {df['year'].min()} – {df['year'].max()}")

# ── 4. Key Insights ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. KEY INSIGHTS")
print("=" * 60)

print("\n[Avg text length by sentiment]")
print(df.groupby("sentiment_label")["text_length"].mean().round(1).to_string())

print("\n[Avg word count by sentiment]")
print(df.groupby("sentiment_label")["word_count"].mean().round(2).to_string())

print("\n[Mention rate by sentiment]")
print(df.groupby("sentiment_label")["has_mention"].mean().mul(100).round(1).to_string())

print("\n[Hashtag rate by sentiment]")
print(df.groupby("sentiment_label")["has_hashtag"].mean().mul(100).round(1).to_string())

print("\n[URL rate by sentiment]")
print(df.groupby("sentiment_label")["has_url"].mean().mul(100).round(1).to_string())

print("\n[Tweet volume by year]")
print(df["year"].value_counts().sort_index().to_string())

print("\n[Peak posting hours (top 5)]")
print(df["hour"].value_counts().head(5).sort_index().to_string())

# ── 5. Visualizations ─────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="muted")
SENT_COLORS = {"negative": "coral", "positive": "steelblue"}

fig, axes = plt.subplots(3, 3, figsize=(16, 14))
fig.suptitle("Sentiment140 EDA (1% Stratified Sample)", fontsize=16, fontweight="bold")

# 1. Sentiment distribution
sent_counts = df["sentiment_label"].value_counts()
axes[0, 0].bar(sent_counts.index, sent_counts.values,
               color=[SENT_COLORS[s] for s in sent_counts.index], edgecolor="white")
axes[0, 0].set_title("Sentiment Distribution")
axes[0, 0].set_xlabel("")
axes[0, 0].set_ylabel("Count")
for i, v in enumerate(sent_counts.values):
    axes[0, 0].text(i, v + 50, str(v), ha="center", va="bottom", fontsize=9, fontweight="bold")

# 2. Text length distribution by sentiment
for label, color in SENT_COLORS.items():
    axes[0, 1].hist(df[df["sentiment_label"] == label]["text_length"],
                    bins=40, alpha=0.6, color=color, edgecolor="white", label=label)
axes[0, 1].set_title("Text Length Distribution by Sentiment")
axes[0, 1].set_xlabel("Character Count")
axes[0, 1].set_ylabel("Frequency")
axes[0, 1].legend()

# 3. Word count distribution by sentiment
for label, color in SENT_COLORS.items():
    axes[0, 2].hist(df[df["sentiment_label"] == label]["word_count"],
                    bins=30, alpha=0.6, color=color, edgecolor="white", label=label)
axes[0, 2].set_title("Word Count Distribution by Sentiment")
axes[0, 2].set_xlabel("Word Count")
axes[0, 2].set_ylabel("Frequency")
axes[0, 2].legend()

# 4. Mention, Hashtag, URL rate by sentiment (grouped bar)
feature_rates = df.groupby("sentiment_label")[["has_mention", "has_hashtag", "has_url"]].mean().mul(100)
feature_rates.columns = ["Mention %", "Hashtag %", "URL %"]
feature_rates.plot(kind="bar", ax=axes[1, 0], color=["steelblue", "goldenrod", "coral"],
                   edgecolor="white")
axes[1, 0].set_title("Mention / Hashtag / URL Rate by Sentiment")
axes[1, 0].set_xlabel("")
axes[1, 0].set_ylabel("% of Tweets")
axes[1, 0].tick_params(axis="x", rotation=0)
axes[1, 0].legend(fontsize=8)

# 5. Tweet volume by month
monthly = df.groupby(["year", "month"]).size().reset_index(name="count")
monthly["period"] = monthly["year"].astype(str) + "-" + monthly["month"].astype(str).str.zfill(2)
monthly_sorted = monthly.sort_values(["year", "month"])
axes[1, 1].plot(monthly_sorted["period"], monthly_sorted["count"],
                marker="o", color="mediumpurple", linewidth=2, markersize=5)
axes[1, 1].set_title("Tweet Volume by Month")
axes[1, 1].set_xlabel("Year-Month")
axes[1, 1].set_ylabel("Tweet Count")
axes[1, 1].tick_params(axis="x", rotation=30)

# 6. Hour of day distribution
hour_counts = df["hour"].value_counts().sort_index()
axes[1, 2].bar(hour_counts.index, hour_counts.values, color="teal", edgecolor="white")
axes[1, 2].set_title("Tweet Volume by Hour of Day")
axes[1, 2].set_xlabel("Hour (UTC)")
axes[1, 2].set_ylabel("Count")

# 7. Avg text length by sentiment
avg_len = df.groupby("sentiment_label")["text_length"].mean()
axes[2, 0].bar(avg_len.index, avg_len.values,
               color=[SENT_COLORS[s] for s in avg_len.index], edgecolor="white")
axes[2, 0].set_title("Avg Text Length by Sentiment")
axes[2, 0].set_xlabel("")
axes[2, 0].set_ylabel("Avg Characters")
for i, v in enumerate(avg_len.values):
    axes[2, 0].text(i, v + 0.3, f"{v:.1f}", ha="center", va="bottom", fontsize=9)

# 8. Avg word count by sentiment
avg_wc = df.groupby("sentiment_label")["word_count"].mean()
axes[2, 1].bar(avg_wc.index, avg_wc.values,
               color=[SENT_COLORS[s] for s in avg_wc.index], edgecolor="white")
axes[2, 1].set_title("Avg Word Count by Sentiment")
axes[2, 1].set_xlabel("")
axes[2, 1].set_ylabel("Avg Words")
for i, v in enumerate(avg_wc.values):
    axes[2, 1].text(i, v + 0.05, f"{v:.1f}", ha="center", va="bottom", fontsize=9)

# 9. Sentiment split by year
yearly_sent = df.groupby(["year", "sentiment_label"]).size().unstack(fill_value=0)
yearly_sent_pct = yearly_sent.div(yearly_sent.sum(axis=1), axis=0).mul(100)
yearly_sent_pct.plot(kind="bar", stacked=True, ax=axes[2, 2],
                     color=["coral", "steelblue"], edgecolor="white")
axes[2, 2].set_title("Sentiment Split by Year (%)")
axes[2, 2].set_xlabel("Year")
axes[2, 2].set_ylabel("% of Tweets")
axes[2, 2].tick_params(axis="x", rotation=0)
axes[2, 2].legend(fontsize=8)

plt.tight_layout()
fig_file = FIG_PATH / "eda_sentiment140.png"
plt.savefig(fig_file, dpi=150, bbox_inches="tight")
print(f"\nChart saved → {fig_file}")
plt.show()

# ── 6. Save Cleaned Output ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("6. SAVING CLEANED OUTPUT")
print("=" * 60)

keep_cols = [
    "id", "polarity", "sentiment_label", "sentiment_binary",
    "user", "date", "date_parsed", "year", "month", "hour",
    "text", "text_clean",
    "text_length", "word_count",
    "has_mention", "has_hashtag", "has_url",
]
keep_cols = [c for c in keep_cols if c in df.columns]
df_clean  = df[keep_cols].copy()

df_clean.to_csv(OUT_PATH, index=False)
print(f"Saved {len(df_clean)} rows × {len(df_clean.columns)} cols → {OUT_PATH}")
print(f"Columns: {list(df_clean.columns)}")
