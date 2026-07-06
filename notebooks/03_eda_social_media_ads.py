"""
Stage 3 EDA: Social Media Advertising Dataset
Source: jsonk11/social-media-advertising-dataset (Kaggle)
Format: Comma-delimited CSV, 300,001 rows

Sampling strategy: 3% stratified by Channel_Used (~9,000 rows)
Stratification ensures all platforms are proportionally represented.

Engineered features:
  - duration_days       = numeric extraction from Duration (e.g. "15 Days" → 15)
  - acquisition_cost    = Acquisition_Cost with $ stripped, cast to float
  - gender              = extracted from Target_Audience ("Men 35-44" → "Men")
  - age_group           = extracted from Target_Audience ("Men 35-44" → "35-44")
  - ctr                 = Clicks / Impressions (click-through rate)
  - cost_per_click      = acquisition_cost / Clicks
  - engagement_tier     = low / mid / high based on Engagement_Score quartiles

Output: datasets/processed/social_media_ads_clean.csv
Charts: outputs/reports/eda_social_media_ads.png
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import warnings

warnings.filterwarnings("ignore")

# ── Schema & Validation ────────────────────────────────────────────────────────
SCHEMA = {
    "expected_columns": [
        "Campaign_ID", "Target_Audience", "Campaign_Goal", "Duration",
        "Channel_Used", "Conversion_Rate", "Acquisition_Cost", "ROI",
        "Location", "Language", "Clicks", "Impressions",
        "Engagement_Score", "Customer_Segment", "Date", "Company",
    ],
    "numeric_columns": [
        "Conversion_Rate", "ROI", "Clicks", "Impressions", "Engagement_Score",
    ],
    "categorical_columns": {
        "Channel_Used":  ["Facebook", "Instagram", "Pinterest", "Twitter"],
        "Campaign_Goal": ["Product Launch", "Market Expansion",
                          "Increase Sales", "Brand Awareness"],
        "Language":      ["English", "French", "Spanish"],
    },
    "value_ranges": {
        "Conversion_Rate":  (0.0, 1.0),
        "Engagement_Score": (1, 10),
        "Clicks":           (0, None),
        "Impressions":      (0, None),
    },
    "null_threshold": {},
    "min_rows": 100000,
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
RAW_PATH = ROOT / "datasets" / "raw" / "Social_Media_Advertising.csv"
OUT_PATH = ROOT / "datasets" / "processed" / "social_media_ads_clean.csv"
FIG_PATH = ROOT / "outputs" / "reports"

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
FIG_PATH.mkdir(parents=True, exist_ok=True)

# ── 1. Load & Stratified Sample ───────────────────────────────────────────────
print("=" * 60)
print("1. LOADING & STRATIFIED SAMPLING (3%)")
print("=" * 60)

df_raw = pd.read_csv(RAW_PATH)
validate_schema(df_raw, SCHEMA, "Social_Media_Advertising.csv")
print(f"Full dataset shape : {df_raw.shape}")
print(f"Columns ({len(df_raw.columns)}): {list(df_raw.columns)}")

frames = []
for ch in df_raw["Channel_Used"].unique():
    subset = df_raw[df_raw["Channel_Used"] == ch]
    frames.append(subset.sample(frac=0.03, random_state=42))
df = pd.concat(frames, ignore_index=True)
print(f"\n3% stratified sample shape : {df.shape}")
print(f"Channel distribution in sample:\n{df['Channel_Used'].value_counts().to_string()}")
print(f"\nDtypes:\n{df.dtypes.to_string()}")
print(f"\nNull counts (non-zero only):\n{df.isnull().sum()[df.isnull().sum() > 0].to_string()}")
print(f"\nDuplicate rows: {df.duplicated().sum()}")
print(f"\nSample (3 rows):\n{df.head(3).to_string()}")

# ── 2. Cleaning ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. CLEANING")
print("=" * 60)

# Remove duplicates
before = len(df)
df.drop_duplicates(inplace=True)
print(f"Removed {before - len(df)} duplicate rows.")

# Strip $ and convert Acquisition_Cost to float
df["acquisition_cost"] = (
    df["Acquisition_Cost"]
    .str.replace("$", "", regex=False)
    .str.strip()
    .astype(float)
)
print(f"Acquisition_Cost converted to float. Range: ${df['acquisition_cost'].min():.2f} – ${df['acquisition_cost'].max():.2f}")

# Extract numeric duration
df["duration_days"] = df["Duration"].str.extract(r"(\d+)").astype(int)
print(f"Duration values (days): {sorted(df['duration_days'].unique())}")

# Parse Date
df["Date"] = pd.to_datetime(df["Date"])

# Standardize text columns
df["Channel_Used"]      = df["Channel_Used"].str.strip()
df["Campaign_Goal"]     = df["Campaign_Goal"].str.strip()
df["Customer_Segment"]  = df["Customer_Segment"].str.strip()
df["Language"]          = df["Language"].str.strip()
df["Location"]          = df["Location"].str.strip()

# Drop rows where Impressions = 0 to avoid division by zero in CTR
before = len(df)
df = df[df["Impressions"] > 0].copy()
print(f"Dropped {before - len(df)} rows with zero Impressions.")

print(f"\nChannels       : {sorted(df['Channel_Used'].unique())}")
print(f"Campaign Goals : {sorted(df['Campaign_Goal'].unique())}")
print(f"Segments       : {sorted(df['Customer_Segment'].unique())}")
print(f"Languages      : {sorted(df['Language'].unique())}")

# ── 3. Feature Engineering ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. FEATURE ENGINEERING")
print("=" * 60)

# Parse gender and age_group from Target_Audience
df["gender"]    = df["Target_Audience"].str.extract(r"^(Men|Women)")
df["age_group"] = df["Target_Audience"].str.extract(r"(\d+-\d+|\d+\+)")

# CTR: Clicks / Impressions
df["ctr"] = df["Clicks"] / df["Impressions"]

# Cost per click
df["cost_per_click"] = df["acquisition_cost"] / df["Clicks"].replace(0, np.nan)

# Engagement tier
df["engagement_tier"] = pd.qcut(
    df["Engagement_Score"],
    q=3,
    labels=["low", "mid", "high"],
    duplicates="drop"
)

# ROI outlier filter — cap extreme values beyond 3 std deviations
roi_mean, roi_std = df["ROI"].mean(), df["ROI"].std()
before = len(df)
df = df[df["ROI"].between(roi_mean - 3 * roi_std, roi_mean + 3 * roi_std)].copy()
print(f"Removed {before - len(df)} ROI outliers. ROI range: {df['ROI'].min():.2f} – {df['ROI'].max():.2f}")

print(f"\nCTR              : mean={df['ctr'].mean():.4f}, max={df['ctr'].max():.4f}")
print(f"Cost per click   : mean=${df['cost_per_click'].mean():.2f}")
print(f"Engagement tiers :\n{df['engagement_tier'].value_counts().to_string()}")
print(f"Gender split     :\n{df['gender'].value_counts().to_string()}")
print(f"Age groups       :\n{df['age_group'].value_counts().to_string()}")

# ── 4. Key Insights ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. KEY INSIGHTS")
print("=" * 60)

print("\n[Avg ROI by Channel]")
print(df.groupby("Channel_Used")["ROI"].mean().sort_values(ascending=False).round(3).to_string())

print("\n[Avg Engagement Score by Channel]")
print(df.groupby("Channel_Used")["Engagement_Score"].mean().sort_values(ascending=False).round(3).to_string())

print("\n[Avg Conversion Rate by Campaign Goal]")
print(df.groupby("Campaign_Goal")["Conversion_Rate"].mean().sort_values(ascending=False).round(4).to_string())

print("\n[Avg CTR by Age Group]")
print(df.groupby("age_group")["ctr"].mean().sort_values(ascending=False).round(4).to_string())

print("\n[Top Customer Segments by Avg ROI]")
print(df.groupby("Customer_Segment")["ROI"].mean().sort_values(ascending=False).round(3).to_string())

print("\n[Language distribution — used for localization planning in Stage 5]")
print(df["Language"].value_counts(normalize=True).mul(100).round(1).to_string())

# ── 5. Visualizations ─────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="muted")
fig, axes = plt.subplots(3, 3, figsize=(16, 14))
fig.suptitle("Social Media Advertising EDA (3% Stratified Sample)", fontsize=16, fontweight="bold")

# 1. Campaign count by channel
channel_counts = df["Channel_Used"].value_counts()
channel_counts.plot(kind="bar", ax=axes[0, 0], color="steelblue", edgecolor="white")
axes[0, 0].set_title("Campaign Count by Channel")
axes[0, 0].set_xlabel("")
axes[0, 0].set_ylabel("Count")
axes[0, 0].tick_params(axis="x", rotation=20)

# 2. Avg ROI by channel
roi_by_channel = df.groupby("Channel_Used")["ROI"].mean().sort_values(ascending=False)
roi_by_channel.plot(kind="bar", ax=axes[0, 1], color="coral", edgecolor="white")
axes[0, 1].set_title("Avg ROI by Channel")
axes[0, 1].set_xlabel("")
axes[0, 1].set_ylabel("Avg ROI")
axes[0, 1].tick_params(axis="x", rotation=20)

# 3. Avg Engagement Score by channel
eng_by_channel = df.groupby("Channel_Used")["Engagement_Score"].mean().sort_values(ascending=False)
eng_by_channel.plot(kind="barh", ax=axes[0, 2], color="teal")
axes[0, 2].set_title("Avg Engagement Score by Channel")
axes[0, 2].set_xlabel("Avg Engagement Score")

# 4. Conversion Rate by Campaign Goal
conv_by_goal = df.groupby("Campaign_Goal")["Conversion_Rate"].mean().sort_values(ascending=False)
conv_by_goal.plot(kind="bar", ax=axes[1, 0], color="goldenrod", edgecolor="white")
axes[1, 0].set_title("Avg Conversion Rate by Campaign Goal")
axes[1, 0].set_xlabel("")
axes[1, 0].set_ylabel("Avg Conversion Rate")
axes[1, 0].tick_params(axis="x", rotation=20)

# 5. Customer Segment distribution
seg_counts = df["Customer_Segment"].value_counts()
seg_counts.plot(kind="bar", ax=axes[1, 1], color="mediumpurple", edgecolor="white")
axes[1, 1].set_title("Customer Segment Distribution")
axes[1, 1].set_xlabel("")
axes[1, 1].set_ylabel("Count")
axes[1, 1].tick_params(axis="x", rotation=20)

# 6. CTR distribution
axes[1, 2].hist(df["ctr"], bins=40, color="seagreen", edgecolor="white")
axes[1, 2].set_title("CTR Distribution")
axes[1, 2].set_xlabel("Click-Through Rate")
axes[1, 2].set_ylabel("Frequency")

# 7. Avg ROI by Customer Segment
roi_by_seg = df.groupby("Customer_Segment")["ROI"].mean().sort_values(ascending=False)
roi_by_seg.plot(kind="bar", ax=axes[2, 0], color="darkorange", edgecolor="white")
axes[2, 0].set_title("Avg ROI by Customer Segment")
axes[2, 0].set_xlabel("")
axes[2, 0].set_ylabel("Avg ROI")
axes[2, 0].tick_params(axis="x", rotation=20)

# 8. Language distribution — localization planning signal
lang_counts = df["Language"].value_counts()
lang_counts.plot(kind="bar", ax=axes[2, 1], color="steelblue", edgecolor="white")
axes[2, 1].set_title("Campaign Language Distribution")
axes[2, 1].set_xlabel("")
axes[2, 1].set_ylabel("Count")
axes[2, 1].tick_params(axis="x", rotation=20)

# 9. Avg CTR by Age Group
ctr_by_age = df.groupby("age_group")["ctr"].mean().sort_values(ascending=False)
ctr_by_age.plot(kind="bar", ax=axes[2, 2], color="crimson", edgecolor="white")
axes[2, 2].set_title("Avg CTR by Age Group")
axes[2, 2].set_xlabel("Age Group")
axes[2, 2].set_ylabel("Avg CTR")
axes[2, 2].tick_params(axis="x", rotation=0)

plt.tight_layout()
fig_file = FIG_PATH / "eda_social_media_ads.png"
plt.savefig(fig_file, dpi=150, bbox_inches="tight")
print(f"\nChart saved → {fig_file}")
plt.show()

# ── 6. Save Cleaned Output ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("6. SAVING CLEANED OUTPUT")
print("=" * 60)

keep_cols = [
    "Campaign_ID", "Channel_Used", "Campaign_Goal", "Customer_Segment",
    "Target_Audience", "gender", "age_group",
    "Duration", "duration_days", "Date",
    "Clicks", "Impressions", "ctr",
    "Conversion_Rate", "Engagement_Score", "engagement_tier",
    "acquisition_cost", "cost_per_click", "ROI",
    "Location", "Language", "Company",
]
keep_cols  = [c for c in keep_cols if c in df.columns]
df_clean   = df[keep_cols].copy()

df_clean.to_csv(OUT_PATH, index=False)
print(f"Saved {len(df_clean)} rows × {len(df_clean.columns)} cols → {OUT_PATH}")
print(f"Columns: {list(df_clean.columns)}")
