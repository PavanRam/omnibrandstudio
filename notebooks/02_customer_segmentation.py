"""
Stage 2: Customer Segmentation & Persona Building
Inputs:
  - datasets/processed/campaigns_clean.csv   (Stage 1 output — already cleaned)
  - datasets/raw/personality_analysis.csv    (Customer Personality Analysis — Kaggle)

Steps:
  1. Clean personality_analysis.csv (nulls, duplicates, outliers, standardization)
  2. Save personality_clean.csv
  3. Merge with campaigns_clean on ID (outer join — expand customer base)
  4. K-Means clustering on behavioural + demographic features
  5. Optimal k via Elbow + Silhouette analysis
  6. Cluster profiling and persona assignment

Outputs:
  - datasets/processed/personality_clean.csv
  - datasets/processed/customer_segments.csv
  - outputs/reports/customer_segmentation.png
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
import warnings

warnings.filterwarnings("ignore")

# ── Schemas & Validation ───────────────────────────────────────────────────────
PERSONALITY_SCHEMA = {
    "expected_columns": [
        "ID", "Year_Birth", "Education", "Marital_Status", "Income",
        "Kidhome", "Teenhome", "Dt_Customer", "Recency",
        "MntWines", "MntFruits", "MntMeatProducts", "MntFishProducts",
        "MntSweetProducts", "MntGoldProds", "NumDealsPurchases",
        "NumWebPurchases", "NumCatalogPurchases", "NumStorePurchases",
        "NumWebVisitsMonth", "AcceptedCmp1", "AcceptedCmp2", "AcceptedCmp3",
        "AcceptedCmp4", "AcceptedCmp5", "Response", "Complain",
        "Z_CostContact", "Z_Revenue",
    ],
    "numeric_columns": [
        "Income", "MntWines", "MntFruits", "MntMeatProducts", "MntFishProducts",
        "MntSweetProducts", "MntGoldProds", "NumDealsPurchases",
        "NumWebPurchases", "NumCatalogPurchases", "NumStorePurchases",
        "NumWebVisitsMonth", "Recency", "Year_Birth", "Kidhome", "Teenhome",
        "Z_CostContact", "Z_Revenue",
    ],
    "binary_columns": [
        "AcceptedCmp1", "AcceptedCmp2", "AcceptedCmp3",
        "AcceptedCmp4", "AcceptedCmp5", "Response", "Complain",
    ],
    "categorical_columns": {
        "Education":      ["Basic", "2N Cycle", "Graduation", "Master", "Phd", "PhD", "2n Cycle"],
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

CAMPAIGNS_SCHEMA = {
    "expected_columns": [
        "ID", "age", "Education", "education_level", "Marital_Status",
        "Income", "Kidhome", "Teenhome", "household_size",
        "Dt_Customer", "tenure_days", "Recency",
        "MntWines", "MntFruits", "MntMeatProducts", "MntFishProducts",
        "MntSweetProducts", "MntGoldProds", "total_spend", "campaign_type",
        "NumWebPurchases", "NumCatalogPurchases", "NumStorePurchases",
        "NumDealsPurchases", "total_purchases", "dominant_channel",
        "AcceptedCmp1", "AcceptedCmp2", "AcceptedCmp3",
        "AcceptedCmp4", "AcceptedCmp5", "Response",
        "campaign_acceptance_count", "engagement_rate",
        "NumWebVisitsMonth", "Complain",
    ],
    "numeric_columns": [
        "age", "Income", "total_spend", "engagement_rate",
        "tenure_days", "total_purchases", "Recency",
        "education_level", "household_size",
    ],
    "value_ranges": {
        "age":             (18, 100),
        "engagement_rate": (0.0, 1.0),
        "education_level": (0, 4),
    },
    "null_threshold": {},
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
ROOT             = Path(__file__).resolve().parent.parent
CAMPAIGNS_PATH   = ROOT / "datasets" / "processed" / "campaigns_clean.csv"
PERSONALITY_PATH = ROOT / "datasets" / "raw" / "personality_analysis.csv"
PERSONALITY_OUT  = ROOT / "datasets" / "processed" / "personality_clean.csv"
SEGMENTS_OUT     = ROOT / "datasets" / "processed" / "customer_segments.csv"
FIG_PATH         = ROOT / "outputs" / "reports"
FIG_PATH.mkdir(parents=True, exist_ok=True)

REFERENCE_DATE = pd.Timestamp("2024-01-01")

# ══════════════════════════════════════════════════════════════════════════════
# 1. CLEAN PERSONALITY_ANALYSIS.CSV
# ══════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("1. CLEANING PERSONALITY_ANALYSIS.CSV")
print("=" * 60)

raw = pd.read_csv(PERSONALITY_PATH, sep="\t")
validate_schema(raw, PERSONALITY_SCHEMA, "personality_analysis.csv")
print(f"Raw shape        : {raw.shape}")
print(f"Columns          : {list(raw.columns)}")
print(f"Null counts:\n{raw.isnull().sum()[raw.isnull().sum() > 0].to_string()}")

# ── 1a. Drop constant columns — Z_CostContact=3, Z_Revenue=11 for every row ──
raw.drop(columns=["Z_CostContact", "Z_Revenue"], inplace=True)
print(f"\nDropped constant columns Z_CostContact, Z_Revenue.")

# ── 1b. Remove fully duplicate rows (same ID, same data) ─────────────────────
before = len(raw)
raw.drop_duplicates(inplace=True)
print(f"Removed {before - len(raw)} fully duplicate rows.")

# ── 1c. Remove records where all data columns are identical but ID differs ────
# (e.g. ID=3033 and ID=4119 have identical birth year, spend, purchase history)
data_cols = [c for c in raw.columns if c != "ID"]
before = len(raw)
raw = raw.drop_duplicates(subset=data_cols, keep="first").copy()
print(f"Removed {before - len(raw)} duplicate records with different IDs but identical data.")

# ── 1d. Drop rows where Income is null (key segmentation feature) ─────────────
before = len(raw)
raw.dropna(subset=["Income"], inplace=True)
print(f"Dropped {before - len(raw)} rows with null Income. Remaining: {len(raw)}")

# ── 1e. Parse Dt_Customer — format is DD-MM-YYYY ──────────────────────────────
raw["Dt_Customer"] = pd.to_datetime(raw["Dt_Customer"], dayfirst=True)

# ── 1f. Standardize Education ─────────────────────────────────────────────────
raw["Education"] = raw["Education"].str.strip().str.title()
# "2N Cycle" comes in as "2N Cycle" after title() from "2n Cycle"
# title() turns "2n Cycle" → "2N Cycle" correctly. Verify:
raw["Education"] = raw["Education"].replace("2N Cycle", "2N Cycle")  # explicit safety
print(f"\nEducation values : {sorted(raw['Education'].unique())}")

# ── 1g. Standardize Marital_Status ────────────────────────────────────────────
raw["Marital_Status"] = raw["Marital_Status"].str.strip().str.title()
raw["Marital_Status"] = raw["Marital_Status"].replace(
    {"Alone": "Single", "Absurd": "Single", "Yolo": "Single"}
)
print(f"Marital_Status   : {sorted(raw['Marital_Status'].unique())}")

# ── 1h. Age — filter obvious outliers (Year_Birth 1900, 1893, etc.) ───────────
raw["age"] = REFERENCE_DATE.year - raw["Year_Birth"]
outliers = raw[(raw["age"] < 18) | (raw["age"] > 100)].shape[0]
raw = raw[(raw["age"] >= 18) & (raw["age"] <= 100)].copy()
print(f"Removed {outliers} age outliers. Age range: {raw['age'].min()}–{raw['age'].max()}")

# ── 1i. Feature Engineering (same as Stage 1) ────────────────────────────────
edu_order = {"Basic": 0, "2N Cycle": 1, "Graduation": 2, "Master": 3, "Phd": 4}
raw["education_level"] = raw["Education"].map(edu_order)

spend_cols   = ["MntWines", "MntFruits", "MntMeatProducts",
                "MntFishProducts", "MntSweetProducts", "MntGoldProds"]
raw["total_spend"] = raw[spend_cols].sum(axis=1)

channel_map = {
    "web":     "NumWebPurchases",
    "catalog": "NumCatalogPurchases",
    "store":   "NumStorePurchases",
    "deals":   "NumDealsPurchases",
}
raw["total_purchases"] = raw[list(channel_map.values())].sum(axis=1)

channel_df = raw[list(channel_map.values())].copy()
channel_df.columns = list(channel_map.keys())
raw["dominant_channel"] = channel_df.idxmax(axis=1)

cmp_cols = ["AcceptedCmp1", "AcceptedCmp2", "AcceptedCmp3",
            "AcceptedCmp4", "AcceptedCmp5", "Response"]
raw["campaign_acceptance_count"] = raw[cmp_cols].sum(axis=1)
raw["engagement_rate"]           = raw["campaign_acceptance_count"] / len(cmp_cols)

raw["campaign_type"] = pd.qcut(
    raw["total_spend"], q=3,
    labels=["low_value", "mid_value", "high_value"]
)

raw["tenure_days"]    = (REFERENCE_DATE - raw["Dt_Customer"]).dt.days
raw["household_size"] = raw["Kidhome"] + raw["Teenhome"] + 1

channel_dummies = pd.get_dummies(raw["dominant_channel"], prefix="ch")
raw = pd.concat([raw, channel_dummies], axis=1)

# ── 1j. Select final columns matching campaigns_clean ────────────────────────
keep_cols = [
    "ID", "age", "Education", "education_level", "Marital_Status",
    "Income", "Kidhome", "Teenhome", "household_size",
    "Dt_Customer", "tenure_days", "Recency",
    *spend_cols, "total_spend", "campaign_type",
    *list(channel_map.values()), "total_purchases", "dominant_channel",
    *[c for c in raw.columns if c.startswith("ch_")],
    *cmp_cols, "campaign_acceptance_count", "engagement_rate",
    "NumWebVisitsMonth", "Complain",
]
keep_cols    = [c for c in keep_cols if c in raw.columns]
personality_clean = raw[keep_cols].copy()

personality_clean.to_csv(PERSONALITY_OUT, index=False)
print(f"\nCleaned personality_analysis → {PERSONALITY_OUT}")
print(f"Shape: {personality_clean.shape}")
print(f"Columns: {list(personality_clean.columns)}")

# ══════════════════════════════════════════════════════════════════════════════
# 2. LOAD CAMPAIGNS_CLEAN & MERGE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("2. MERGING WITH CAMPAIGNS_CLEAN")
print("=" * 60)

campaigns = pd.read_csv(CAMPAIGNS_PATH)
validate_schema(campaigns, CAMPAIGNS_SCHEMA, "campaigns_clean.csv")
print(f"campaigns_clean  : {campaigns.shape}")
print(f"personality_clean: {personality_clean.shape}")

# Outer merge on ID — campaigns_clean values take priority (already validated).
# Rows only in personality_clean are appended with their own values.
common_ids    = set(campaigns["ID"]) & set(personality_clean["ID"])
only_in_pers  = set(personality_clean["ID"]) - set(campaigns["ID"])
only_in_camp  = set(campaigns["ID"]) - set(personality_clean["ID"])
print(f"IDs in both      : {len(common_ids)}")
print(f"Only in personality_clean : {len(only_in_pers)}")
print(f"Only in campaigns_clean   : {len(only_in_camp)}")

# Keep campaigns_clean as the base; add any extra rows from personality_clean
extra_rows = personality_clean[personality_clean["ID"].isin(only_in_pers)].copy()

# Align dtypes — campaign_type is categorical in campaigns, object in extra_rows
extra_rows["campaign_type"] = extra_rows["campaign_type"].astype(str)
campaigns["campaign_type"]  = campaigns["campaign_type"].astype(str)

# Boolean ch_* columns in campaigns_clean need to match int in extra_rows
for col in [c for c in campaigns.columns if c.startswith("ch_")]:
    if col in extra_rows.columns:
        extra_rows[col] = extra_rows[col].astype(int)
        campaigns[col]  = campaigns[col].astype(int)

df = pd.concat([campaigns, extra_rows], ignore_index=True)
print(f"\nMerged dataset   : {df.shape}")
print(f"Unique customers : {df['ID'].nunique()}")

# ══════════════════════════════════════════════════════════════════════════════
# 3. FEATURE SELECTION FOR CLUSTERING
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("3. FEATURE SELECTION FOR CLUSTERING")
print("=" * 60)

CLUSTER_FEATURES = [
    "Income",             # wealth indicator
    "total_spend",        # total spend across all product categories
    "engagement_rate",    # fraction of campaigns accepted (0–1)
    "age",                # demographic
    "education_level",    # ordinal: 0=Basic … 4=PhD
    "household_size",     # household size (kids + teens + 1)
    "tenure_days",        # days since first purchase (loyalty proxy)
    "Recency",            # days since last purchase (lower = recently active)
    "NumWebVisitsMonth",  # monthly website visits (digital engagement proxy)
    "ch_catalog",         # dominant channel dummies
    "ch_deals",
    "ch_store",
    "ch_web",
]

X = df[CLUSTER_FEATURES].copy()

for col in ["ch_catalog", "ch_deals", "ch_store", "ch_web"]:
    X[col] = X[col].astype(float)

print(f"Features ({len(CLUSTER_FEATURES)}): {CLUSTER_FEATURES}")
print(f"Total nulls before drop: {X.isnull().sum().sum()}")

X     = X.dropna()
df_cl = df.loc[X.index].copy()
print(f"Rows after dropping nulls: {len(X)}")

# ══════════════════════════════════════════════════════════════════════════════
# 4. SCALING
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("4. FEATURE SCALING (StandardScaler)")
print("=" * 60)

scaler   = StandardScaler()
X_scaled = scaler.fit_transform(X)
print("All features normalized to mean=0, std=1")

# ══════════════════════════════════════════════════════════════════════════════
# 5. OPTIMAL K — ELBOW + SILHOUETTE
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("5. OPTIMAL K SELECTION (k = 2 … 8)")
print("=" * 60)

K_RANGE    = range(2, 9)
inertias   = []
sil_scores = []

for k in K_RANGE:
    km     = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X_scaled)
    inertias.append(km.inertia_)
    sil = silhouette_score(X_scaled, labels)
    sil_scores.append(sil)
    print(f"  k={k}  inertia={km.inertia_:>12.0f}  silhouette={sil:.4f}")

best_k = list(K_RANGE)[sil_scores.index(max(sil_scores))]
print(f"\n→ Best k by silhouette score: {best_k}")

# ══════════════════════════════════════════════════════════════════════════════
# 6. FIT K-MEANS
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print(f"6. FITTING K-MEANS  k={best_k}")
print("=" * 60)

kmeans           = KMeans(n_clusters=best_k, random_state=42, n_init=10)
df_cl["cluster"] = kmeans.fit_predict(X_scaled)

print("Cluster distribution:")
print(df_cl["cluster"].value_counts().sort_index().to_string())

# ══════════════════════════════════════════════════════════════════════════════
# 7. CLUSTER PROFILING
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("7. CLUSTER PROFILING")
print("=" * 60)

NUM_COLS = [
    "Income", "total_spend", "engagement_rate", "age",
    "education_level", "household_size", "tenure_days",
    "Recency", "NumWebVisitsMonth",
    "ch_catalog", "ch_deals", "ch_store", "ch_web",
]

profile = df_cl.groupby("cluster")[NUM_COLS].mean().round(3)
print("\nMean feature values per cluster:")
print(profile.to_string())

print("\nDominant channel mode per cluster:")
print(df_cl.groupby("cluster")["dominant_channel"]
      .agg(lambda x: x.value_counts().index[0]).to_string())

print("\nCampaign type mode per cluster:")
print(df_cl.groupby("cluster")["campaign_type"]
      .agg(lambda x: x.value_counts().index[0]).to_string())

# ══════════════════════════════════════════════════════════════════════════════
# 8. PERSONA ASSIGNMENT
# ══════════════════════════════════════════════════════════════════════════════
income_rank = profile["Income"].rank().astype(int)
spend_rank  = profile["total_spend"].rank().astype(int)
engage_rank = profile["engagement_rate"].rank().astype(int)

TOP = best_k
BOT = 1

def assign_persona(c):
    ir, sr, er = income_rank[c], spend_rank[c], engage_rank[c]
    mid = TOP / 2
    # Each condition uses the single strongest signal for that cluster.
    # Order matters — engagement is checked first as it is the rarest trait.
    if er == TOP:
        return "Highly Engaged Campaign Responder"   # C4: highest engagement + catalog
    elif ir == TOP:
        return "High-Income Store Spender"            # C0: highest income, store dominant
    elif sr == BOT:
        return "Budget-Conscious Low Spender"         # C1: lowest spend, store dominant
    elif ir == BOT:
        return "Deal-Seeking Value Hunter"            # C3: lowest income, deals dominant
    elif ir > mid and sr > mid:
        return "Web-Savvy Mid-Tier Buyer"             # C2: web dominant, mid income+spend
    else:
        return "Mid-Range Occasional Buyer"

persona_map      = {c: assign_persona(c) for c in range(best_k)}
df_cl["persona"] = df_cl["cluster"].map(persona_map)

print("\n" + "=" * 60)
print("8. PERSONA ASSIGNMENTS")
print("=" * 60)
for c, name in persona_map.items():
    n = (df_cl["cluster"] == c).sum()
    print(f"  Cluster {c} → '{name}'  (n={n})")

print("\n── PERSONA SUMMARY " + "─" * 41)
for c in range(best_k):
    sub = df_cl[df_cl["cluster"] == c]
    print(f"\nCluster {c} | {persona_map[c]} | n={len(sub)}")
    print(f"  Income          : ${sub['Income'].mean():>8.0f}")
    print(f"  Total Spend     : ${sub['total_spend'].mean():>8.0f}")
    print(f"  Engagement Rate :  {sub['engagement_rate'].mean():.3f}")
    print(f"  Avg Age         :  {sub['age'].mean():.1f} yrs")
    print(f"  Education Level :  {sub['education_level'].mean():.2f}  (0=Basic … 4=PhD)")
    print(f"  Dominant Channel:  {sub['dominant_channel'].mode()[0]}")
    print(f"  Campaign Type   :  {sub['campaign_type'].mode()[0]}")

# ══════════════════════════════════════════════════════════════════════════════
# 9. VISUALIZATIONS
# ══════════════════════════════════════════════════════════════════════════════
sns.set_theme(style="whitegrid", palette="muted")
COLORS = sns.color_palette("tab10", best_k)

fig, axes = plt.subplots(3, 3, figsize=(18, 16))
fig.suptitle("Customer Segmentation — Stage 2", fontsize=16, fontweight="bold")

# Plot 1 — Elbow curve
axes[0, 0].plot(list(K_RANGE), inertias, marker="o", color="steelblue", linewidth=2)
axes[0, 0].axvline(best_k, color="red", linestyle="--", label=f"Optimal k={best_k}")
axes[0, 0].set_title("Elbow Curve")
axes[0, 0].set_xlabel("Number of Clusters (k)")
axes[0, 0].set_ylabel("Inertia")
axes[0, 0].legend()

# Plot 2 — Silhouette scores
axes[0, 1].plot(list(K_RANGE), sil_scores, marker="s", color="darkorange", linewidth=2)
axes[0, 1].axvline(best_k, color="red", linestyle="--", label=f"Optimal k={best_k}")
axes[0, 1].set_title("Silhouette Score vs k")
axes[0, 1].set_xlabel("Number of Clusters (k)")
axes[0, 1].set_ylabel("Silhouette Score")
axes[0, 1].legend()

# Plot 3 — Cluster size distribution
cluster_sizes = df_cl["cluster"].value_counts().sort_index()
short_labels  = [f"C{c}\n{persona_map[c].split()[0]}" for c in cluster_sizes.index]
axes[0, 2].bar(short_labels, cluster_sizes.values, color=COLORS)
for i, val in enumerate(cluster_sizes.values):
    axes[0, 2].text(i, val + 8, str(val), ha="center", va="bottom",
                    fontsize=9, fontweight="bold")
axes[0, 2].set_title("Cluster Size Distribution")
axes[0, 2].set_xlabel("Cluster")
axes[0, 2].set_ylabel("Number of Customers")
axes[0, 2].tick_params(axis="x", rotation=20)
plt.setp(axes[0, 2].get_xticklabels(), ha="right")

# Plot 4 — PCA 2D scatter
pca   = PCA(n_components=2, random_state=42)
X_pca = pca.fit_transform(X_scaled)
for c in range(best_k):
    mask = df_cl["cluster"].values == c
    axes[1, 0].scatter(
        X_pca[mask, 0], X_pca[mask, 1],
        alpha=0.4, s=15, color=COLORS[c],
        label=f"C{c}: {persona_map[c]}"
    )
var_exp = pca.explained_variance_ratio_.sum() * 100
axes[1, 0].set_title(f"PCA 2D Projection ({var_exp:.1f}% variance explained)")
axes[1, 0].set_xlabel("PC1")
axes[1, 0].set_ylabel("PC2")
axes[1, 0].legend(fontsize=7)

# Plot 5 — Avg Income (left axis) & Avg Total Spend (right axis) — dual scale
# Root cause of old chart: income (~$50k) and spend (~$500) shared one axis,
# making spend bars invisible. Fix: separate y-axes + value labels on every bar.
ax5      = axes[1, 1]
ax5_twin = ax5.twinx()

x = np.arange(best_k)
w = 0.35
income_vals = [profile.loc[c, "Income"]      for c in range(best_k)]
spend_vals  = [profile.loc[c, "total_spend"] for c in range(best_k)]

bars_inc   = ax5.bar(x - w/2, income_vals, width=w,
                     label="Avg Income ($)",      color="steelblue", alpha=0.85)
bars_spend = ax5_twin.bar(x + w/2, spend_vals, width=w,
                           label="Avg Total Spend ($)", color="coral",    alpha=0.85)

# Value labels — income bars (left axis)
for bar in bars_inc:
    ax5.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
             f'${bar.get_height():,.0f}',
             ha="center", va="bottom", fontsize=7,
             color="steelblue", fontweight="bold")

# Value labels — spend bars (right axis)
for bar in bars_spend:
    ax5_twin.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                  f'${bar.get_height():,.0f}',
                  ha="center", va="bottom", fontsize=7,
                  color="coral", fontweight="bold")

ax5.set_title("Avg Income & Total Spend by Cluster")
ax5.set_xlabel("Cluster")
ax5.set_ylabel("Avg Income ($)",       color="steelblue")
ax5_twin.set_ylabel("Avg Total Spend ($)", color="coral")
ax5.set_xticks(x)
ax5.set_xticklabels([f"C{c}" for c in range(best_k)])
ax5.tick_params(axis="y", labelcolor="steelblue")
ax5_twin.tick_params(axis="y", labelcolor="coral")
h1, l1 = ax5.get_legend_handles_labels()
h2, l2 = ax5_twin.get_legend_handles_labels()
ax5.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")

# Plot 6 — Dominant channel mix by cluster (stacked bar with % labels)
CH_COLS   = ["ch_catalog", "ch_deals", "ch_store", "ch_web"]
CH_NAMES  = ["Catalog",    "Deals",    "Store",    "Web"]
CH_COLORS = ["teal", "goldenrod", "steelblue", "mediumpurple"]
bottom    = np.zeros(best_k)
x_labels  = [f"C{c}" for c in range(best_k)]
for col, name, color in zip(CH_COLS, CH_NAMES, CH_COLORS):
    vals = [profile.loc[c, col] for c in range(best_k)]
    bars = axes[1, 2].bar(x_labels, vals, bottom=bottom, label=name, color=color)
    # Percentage label inside each segment that is wide enough to read (> 5%)
    for i, (bar, val) in enumerate(zip(bars, vals)):
        if val > 0.05:
            axes[1, 2].text(
                bar.get_x() + bar.get_width() / 2,
                bottom[i] + val / 2,
                f"{val*100:.0f}%",
                ha="center", va="center",
                fontsize=7, color="white", fontweight="bold"
            )
    bottom += np.array(vals)
axes[1, 2].set_title("Dominant Channel Mix by Cluster")
axes[1, 2].set_xlabel("Cluster")
axes[1, 2].set_ylabel("Proportion of Customers")
axes[1, 2].legend(fontsize=8)

# Plot 7 — Spend category mix by persona (radar chart)
spend_labels = ["Wines", "Fruits", "Meat", "Fish", "Sweets", "Gold"]
radar_data   = df_cl.groupby("cluster")[spend_cols].mean()
radar_norm   = radar_data.div(radar_data.max())

N      = len(spend_labels)
angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
angles += angles[:1]

axes[2, 0].remove()
ax_radar = fig.add_subplot(3, 3, 7, polar=True)

for c in range(best_k):
    vals = radar_norm.loc[c].tolist() + [radar_norm.loc[c].tolist()[0]]
    ax_radar.plot(angles, vals, color=COLORS[c], linewidth=1.5,
                  label=f"C{c}: {persona_map[c].split()[0]}")
    ax_radar.fill(angles, vals, color=COLORS[c], alpha=0.1)

ax_radar.set_xticks(angles[:-1])
ax_radar.set_xticklabels(spend_labels, fontsize=8)
ax_radar.set_title("Spend Category Mix by Persona", pad=15, fontsize=11)
ax_radar.legend(fontsize=7, loc="upper right", bbox_to_anchor=(1.35, 1.15))

# Plot 8 — Campaign acceptance heatmap by persona
heatmap_data = df_cl.groupby("persona")[cmp_cols].mean()
heatmap_data.columns = ["Cmp1", "Cmp2", "Cmp3", "Cmp4", "Cmp5", "Response"]
sns.heatmap(heatmap_data, annot=True, fmt=".2f", cmap="YlOrRd",
            ax=axes[2, 1], linewidths=0.5, cbar_kws={"shrink": 0.8})
axes[2, 1].set_title("Campaign Acceptance Rate by Persona")
axes[2, 1].set_xlabel("Campaign")
axes[2, 1].set_ylabel("")
axes[2, 1].tick_params(axis="y", rotation=0, labelsize=7)

axes[2, 2].set_visible(False)

plt.tight_layout()
fig_file = FIG_PATH / "customer_segmentation.png"
plt.savefig(fig_file, dpi=150, bbox_inches="tight")
print(f"\nChart saved → {fig_file}")
plt.show()

# ══════════════════════════════════════════════════════════════════════════════
# 10. SAVE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("10. SAVING OUTPUTS")
print("=" * 60)

df_cl.to_csv(SEGMENTS_OUT, index=False)
print(f"Saved {len(df_cl)} rows × {len(df_cl.columns)} cols → {SEGMENTS_OUT}")
print(f"New columns added: cluster, persona")
