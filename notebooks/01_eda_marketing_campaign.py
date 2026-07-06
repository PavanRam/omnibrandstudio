"""
Stage 1 EDA: Marketing Campaign Dataset
Source: rodsaldanha/arketing-campaign (Kaggle) — Customer Personality Analysis
Format: Semicolon-delimited CSV

Dataset note: This is a customer-level dataset, not a channel/impression dataset.
Metrics are adapted as follows:
  - engagement_rate        = accepted_campaigns / 6  (6 total campaigns: Cmp1-5 + Response)
  - dominant_channel       = purchase channel with highest volume per customer
  - campaign_type          = spending tier (low_value / mid_value / high_value)

Output: datasets/processed/campaigns_clean.csv
Charts: outputs/reports/eda_marketing_campaign.png
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
        "ID", "Year_Birth", "Education", "Marital_Status", "Income",
        "Kidhome", "Teenhome", "Dt_Customer", "Recency",
        "MntWines", "MntFruits", "MntMeatProducts", "MntFishProducts",
        "MntSweetProducts", "MntGoldProds", "NumDealsPurchases",
        "NumWebPurchases", "NumCatalogPurchases", "NumStorePurchases",
        "NumWebVisitsMonth", "AcceptedCmp1", "AcceptedCmp2", "AcceptedCmp3",
        "AcceptedCmp4", "AcceptedCmp5", "Response", "Complain",
    ],
    "numeric_columns": [
        "Income", "MntWines", "MntFruits", "MntMeatProducts", "MntFishProducts",
        "MntSweetProducts", "MntGoldProds", "NumDealsPurchases",
        "NumWebPurchases", "NumCatalogPurchases", "NumStorePurchases",
        "NumWebVisitsMonth", "Recency", "Year_Birth", "Kidhome", "Teenhome",
    ],
    "binary_columns": [
        "AcceptedCmp1", "AcceptedCmp2", "AcceptedCmp3",
        "AcceptedCmp4", "AcceptedCmp5", "Response", "Complain",
    ],
    "categorical_columns": {
        "Education":     ["Basic", "2N Cycle", "Graduation", "Master", "Phd", "PhD", "2n Cycle"],
        "Marital_Status": ["Single", "Married", "Divorced", "Widow", "Together",
                           "Alone", "Absurd", "YOLO", "Yolo"],
    },
    "value_ranges": {
        "Kidhome":  (0, 3),
        "Teenhome": (0, 3),
        "Recency":  (0, 365),
    },
    "null_threshold": {
        "Income": 0.05,
    },
    "min_rows": 2000,
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
ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "datasets" / "marketing_campaign.csv"
OUT_PATH = ROOT / "datasets" / "processed" / "campaigns_clean.csv"
FIG_PATH = ROOT / "outputs" / "reports"

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
FIG_PATH.mkdir(parents=True, exist_ok=True)

# ── 1. Load & Inspect ─────────────────────────────────────────────────────────
print("=" * 60)
print("1. LOADING & INSPECTION")
print("=" * 60)

df = pd.read_csv(RAW_PATH, sep=";")
validate_schema(df, SCHEMA, "marketing_campaign.csv")

print(f"Shape        : {df.shape}")
print(f"Columns ({len(df.columns)}): {list(df.columns)}")
print(f"\nDtypes:\n{df.dtypes.to_string()}")
print(f"\nNull counts (non-zero only):\n{df.isnull().sum()[df.isnull().sum() > 0].to_string()}")
print(f"\nDuplicate rows: {df.duplicated().sum()}")
print(f"\nSample (3 rows):\n{df.head(3).to_string()}")

# ── 2. Cleaning ────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("2. CLEANING")
print("=" * 60)

# Remove duplicate rows
before = len(df)
df.drop_duplicates(inplace=True)
print(f"Removed {before - len(df)} duplicate rows.")

# Drop rows where Income is null (key segmentation feature)
before = len(df)
df.dropna(subset=["Income"], inplace=True)
print(f"Dropped {before - len(df)} rows with null Income. Remaining: {len(df)}")

# Convert Dt_Customer to datetime
df["Dt_Customer"] = pd.to_datetime(df["Dt_Customer"])

# Standardize text columns
df["Education"] = df["Education"].str.strip().str.title()
df["Marital_Status"] = df["Marital_Status"].str.strip().str.title()

# Consolidate non-standard Marital_Status values into Single
df["Marital_Status"] = df["Marital_Status"].replace(
    {"Alone": "Single", "Absurd": "Single", "Yolo": "Single"}
)

print(f"Education values   : {sorted(df['Education'].unique())}")
print(f"Marital_Status     : {sorted(df['Marital_Status'].unique())}")

# ── 3. Feature Engineering ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("3. FEATURE ENGINEERING")
print("=" * 60)

REFERENCE_DATE = pd.Timestamp("2024-01-01")

# Age (filter obvious outliers)
df["age"] = REFERENCE_DATE.year - df["Year_Birth"]
outliers_removed = df[(df["age"] < 18) | (df["age"] > 100)].shape[0]
df = df[(df["age"] >= 18) & (df["age"] <= 100)].copy()
print(f"Removed {outliers_removed} age outliers. Age range: {df['age'].min()}–{df['age'].max()}")

# Ordinal encoding for Education
edu_order = {"Basic": 0, "2N Cycle": 1, "Graduation": 2, "Master": 3, "Phd": 4}
df["education_level"] = df["Education"].map(edu_order)

# Total spend across all product categories
spend_cols = ["MntWines", "MntFruits", "MntMeatProducts",
              "MntFishProducts", "MntSweetProducts", "MntGoldProds"]
df["total_spend"] = df[spend_cols].sum(axis=1)

# Purchase channel volumes
channel_map = {
    "web":     "NumWebPurchases",
    "catalog": "NumCatalogPurchases",
    "store":   "NumStorePurchases",
    "deals":   "NumDealsPurchases",
}
df["total_purchases"] = df[list(channel_map.values())].sum(axis=1)

# Dominant purchase channel — analogous to "top channel" in campaign analytics
channel_df = df[list(channel_map.values())].copy()
channel_df.columns = list(channel_map.keys())
df["dominant_channel"] = channel_df.idxmax(axis=1)

# Campaign acceptance columns (Cmp1–5 + final Response)
cmp_cols = ["AcceptedCmp1", "AcceptedCmp2", "AcceptedCmp3",
            "AcceptedCmp4", "AcceptedCmp5", "Response"]
df["campaign_acceptance_count"] = df[cmp_cols].sum(axis=1)

# engagement_rate: fraction of campaigns accepted (0–1 scale)
df["engagement_rate"] = df["campaign_acceptance_count"] / len(cmp_cols)

# campaign_type: spending tier used for content personalization / few-shot selection
df["campaign_type"] = pd.qcut(
    df["total_spend"],
    q=3,
    labels=["low_value", "mid_value", "high_value"]
)

# Customer tenure in days from first purchase
df["tenure_days"] = (REFERENCE_DATE - df["Dt_Customer"]).dt.days

# Household size
df["household_size"] = df["Kidhome"] + df["Teenhome"] + 1

# Dummy encode dominant_channel for downstream clustering
channel_dummies = pd.get_dummies(df["dominant_channel"], prefix="ch")
df = pd.concat([df, channel_dummies], axis=1)

print(f"engagement_rate  : mean={df['engagement_rate'].mean():.3f}, max={df['engagement_rate'].max():.3f}")
print(f"dominant_channel :\n{df['dominant_channel'].value_counts().to_string()}")
print(f"campaign_type    :\n{df['campaign_type'].value_counts().to_string()}")

# ── 4. Key Insights ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. KEY INSIGHTS")
print("=" * 60)

print("\n[Avg engagement rate by dominant channel]")
channel_engage = (
    df.groupby("dominant_channel")["engagement_rate"]
    .mean()
    .sort_values(ascending=False)
)
print(channel_engage.round(4).to_string())

print("\n[Avg total spend by campaign_type]")
print(df.groupby("campaign_type", observed=True)["total_spend"].mean().round(2).to_string())

print("\n[Final campaign response rate by Education]")
print(df.groupby("Education")["Response"].mean().sort_values(ascending=False).round(4).to_string())

print("\n[Top channels — used to select few-shot examples in Stage 3]")
top_channels = df["dominant_channel"].value_counts(normalize=True).mul(100).round(1)
print(top_channels.to_string())

# ── 5. Visualizations ─────────────────────────────────────────────────────────
sns.set_theme(style="whitegrid", palette="muted")
fig, axes = plt.subplots(4, 3, figsize=(16, 19))
fig.suptitle("Marketing Campaign EDA", fontsize=16, fontweight="bold")

# 1. Dominant channel distribution
df["dominant_channel"].value_counts().plot(kind="bar", ax=axes[0, 0], color="steelblue")
axes[0, 0].set_title("Dominant Purchase Channel")
axes[0, 0].tick_params(axis="x", rotation=0)
axes[0, 0].set_xlabel("")
axes[0, 0].set_ylabel("Count")

# 2. Campaign type (spending tier) distribution
df["campaign_type"].value_counts().plot(kind="bar", ax=axes[0, 1], color="coral")
axes[0, 1].set_title("Campaign Type (Spending Tier)")
axes[0, 1].tick_params(axis="x", rotation=0)
axes[0, 1].set_xlabel("")
axes[0, 1].set_ylabel("Count")

# 3. Avg engagement rate by channel
channel_engage.plot(kind="barh", ax=axes[0, 2], color="teal")
axes[0, 2].set_title("Avg Engagement Rate by Channel")
axes[0, 2].set_xlabel("Engagement Rate")

# 4. Engagement rate distribution
axes[1, 0].hist(df["engagement_rate"], bins=15, color="mediumpurple", edgecolor="white")
axes[1, 0].set_title("Engagement Rate Distribution")
axes[1, 0].set_xlabel("Engagement Rate")
axes[1, 0].set_ylabel("Frequency")

# 5. Total spend distribution
axes[1, 1].hist(df["total_spend"], bins=40, color="goldenrod", edgecolor="white")
axes[1, 1].set_title("Total Spend Distribution")
axes[1, 1].set_xlabel("Total Spend")
axes[1, 1].set_ylabel("Frequency")

# 6. Income vs Total Spend
axes[1, 2].scatter(df["Income"], df["total_spend"], alpha=0.3, s=10, color="darkslateblue")
axes[1, 2].set_title("Income vs Total Spend")
axes[1, 2].set_xlabel("Income")
axes[1, 2].set_ylabel("Total Spend")

# 7. Avg total spend by Education
edu_order_labels = ["Basic", "2N Cycle", "Graduation", "Master", "Phd"]
edu_spend = (
    df.groupby("Education")["total_spend"]
    .mean()
    .reindex(edu_order_labels)
    .dropna()
)
edu_spend.plot(kind="bar", ax=axes[2, 0], color="seagreen")
axes[2, 0].set_title("Avg Total Spend by Education")
axes[2, 0].set_xlabel("Education Level")
axes[2, 0].set_ylabel("Avg Total Spend")
axes[2, 0].tick_params(axis="x", rotation=15)

# 8. Acceptance rate per campaign
cmp_means  = df[cmp_cols].mean()
cmp_labels = ["Cmp1", "Cmp2", "Cmp3", "Cmp4", "Cmp5", "Response"]
axes[2, 1].bar(cmp_labels, cmp_means.values, color="steelblue", edgecolor="white")
axes[2, 1].set_title("Acceptance Rate per Campaign")
axes[2, 1].set_xlabel("Campaign")
axes[2, 1].set_ylabel("Acceptance Rate")
for i, v in enumerate(cmp_means.values):
    axes[2, 1].text(i, v + 0.002, f"{v:.3f}", ha="center", va="bottom", fontsize=8)

# 9. Channel preference by age group
df["age_group"] = pd.cut(df["age"], bins=[18, 35, 50, 65, 100],
                         labels=["18-35", "36-50", "51-65", "65+"])
age_channel = (
    df.groupby("age_group", observed=True)["dominant_channel"]
    .value_counts(normalize=True)
    .unstack(fill_value=0)
)
age_channel.plot(kind="bar", stacked=True, ax=axes[2, 2], colormap="tab10")
axes[2, 2].set_title("Channel Preference by Age Group")
axes[2, 2].set_xlabel("Age Group")
axes[2, 2].set_ylabel("Proportion")
axes[2, 2].tick_params(axis="x", rotation=0)
axes[2, 2].legend(fontsize=8, title="Channel")

# 10. Web visits vs web purchases
axes[3, 0].scatter(df["NumWebVisitsMonth"], df["NumWebPurchases"],
                   alpha=0.3, s=10, color="mediumpurple")
axes[3, 0].set_title("Web Visits vs Web Purchases")
axes[3, 0].set_xlabel("Monthly Web Visits")
axes[3, 0].set_ylabel("Web Purchases")

# Hide unused subplots in row 4
axes[3, 1].set_visible(False)
axes[3, 2].set_visible(False)

plt.tight_layout()
fig_file = FIG_PATH / "eda_marketing_campaign.png"
plt.savefig(fig_file, dpi=150, bbox_inches="tight")
print(f"\nChart saved → {fig_file}")
plt.show()

# ── 6. Save Cleaned Output ────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("5. SAVING CLEANED OUTPUT")
print("=" * 60)

keep_cols = [
    "ID", "age", "Education", "education_level", "Marital_Status",
    "Income", "Kidhome", "Teenhome", "household_size",
    "Dt_Customer", "tenure_days", "Recency",
    *spend_cols, "total_spend", "campaign_type",
    *list(channel_map.values()), "total_purchases", "dominant_channel",
    *[c for c in df.columns if c.startswith("ch_")],
    *cmp_cols, "campaign_acceptance_count", "engagement_rate",
    "NumWebVisitsMonth", "Complain",
]
keep_cols = [c for c in keep_cols if c in df.columns]

df_clean = df[keep_cols].copy()
df_clean.to_csv(OUT_PATH, index=False)
print(f"Saved {len(df_clean)} rows × {len(df_clean.columns)} cols → {OUT_PATH}")
print(f"Columns: {list(df_clean.columns)}")
