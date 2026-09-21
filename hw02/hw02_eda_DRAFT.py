#!/usr/bin/env python3
# =============================================================================
# Script:    hw02_eda.py
# Purpose:   Exploratory Data Analysis (EDA) of financial transaction data
# Dataset:   02_Data/raw/fact_transactions.csv
# Author:    Jenna Genzel
# Course:    MIS3060 - Business Intelligence with AI
# Generated: 2026-09-16
#
# Description:
#   Single-run EDA script that loads the raw transactions dataset, profiles
#   its structure and quality, summarizes key statistics and relationships,
#   flags data-quality issues, generates three charts, and writes a plain
#   text profile report to disk.
# =============================================================================

import io
import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Candidate locations for the raw data file. The assignment spec references
# "data/raw/fact_transactions.csv"; this project's actual folder layout uses
# "02_Data/raw/fact_transactions.csv". Both are checked, relative to the
# script's own folder, so the script runs regardless of the current
# working directory.
CANDIDATE_DATA_PATHS = [
    os.path.join(SCRIPT_DIR, "data", "raw", "fact_transactions.csv"),
    os.path.join(SCRIPT_DIR, "02_Data", "raw", "fact_transactions.csv"),
    os.path.join(SCRIPT_DIR, "..", "data", "raw", "fact_transactions.csv"),
    os.path.join(SCRIPT_DIR, "..", "02_Data", "raw", "fact_transactions.csv"),
    "data/raw/fact_transactions.csv",
    "02_Data/raw/fact_transactions.csv",
]

CHARTS_DIR = os.path.join(SCRIPT_DIR, "charts")
PROFILE_PATH = os.path.join(SCRIPT_DIR, "hw02_profile.txt")
EXPECTED_SHAPE = (298772, 9)


def find_data_path():
    for path in CANDIDATE_DATA_PATHS:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "Could not locate fact_transactions.csv. Checked:\n  "
        + "\n  ".join(CANDIDATE_DATA_PATHS)
    )


def main():
    # A buffer that mirrors everything printed to the console so items 2-13
    # can be saved verbatim to hw02_profile.txt (item 16).
    report_lines = []

    def emit(text=""):
        """Print to console and capture the same line for the text report."""
        print(text)
        report_lines.append(str(text))

    # -------------------------------------------------------------------
    # 1. Load the dataset
    # -------------------------------------------------------------------
    data_path = find_data_path()
    df = pd.read_csv(data_path, parse_dates=["txn_date"])

    print(f"Loaded data from: {data_path}\n")

    # -------------------------------------------------------------------
    # 2. Shape (rows x columns)
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("2. DATASET SHAPE")
    emit("=" * 70)
    emit(f"Rows x Columns: {df.shape[0]} x {df.shape[1]}")
    emit("")

    # -------------------------------------------------------------------
    # 3. Column names and data types
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("3. COLUMN NAMES AND DATA TYPES")
    emit("=" * 70)
    emit(df.dtypes.to_string())
    emit("")

    # -------------------------------------------------------------------
    # 4. Missing values per column
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("4. MISSING VALUES PER COLUMN")
    emit("=" * 70)
    emit(df.isnull().sum().to_string())
    emit("")

    # -------------------------------------------------------------------
    # 5. Descriptive statistics for numeric columns
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("5. DESCRIPTIVE STATISTICS (NUMERIC COLUMNS)")
    emit("=" * 70)
    numeric_df = df.select_dtypes(include="number")
    desc = numeric_df.describe().T
    desc = desc.rename(columns={"50%": "median"})
    desc = desc[["count", "mean", "std", "min", "25%", "median", "75%", "max"]]
    emit(desc.to_string())
    emit("")

    # -------------------------------------------------------------------
    # 6. Value counts and percentages for txn_type
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("6. TXN_TYPE VALUE COUNTS AND PERCENTAGES")
    emit("=" * 70)
    txn_counts = df["txn_type"].value_counts().sort_values(ascending=False)
    txn_pct = (txn_counts / len(df) * 100).round(2)
    txn_summary = pd.DataFrame({"count": txn_counts, "pct": txn_pct})
    emit(txn_summary.to_string())
    emit("")

    # -------------------------------------------------------------------
    # 7. Unique counts of clients, advisors, securities
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("7. UNIQUE ENTITY COUNTS")
    emit("=" * 70)
    emit(f"Unique clients:    {df['client_id'].nunique()}")
    emit(f"Unique advisors:   {df['advisor_id'].nunique()}")
    emit(f"Unique securities: {df['security_id'].nunique()}")
    emit("")

    # -------------------------------------------------------------------
    # 8. Date range of txn_date
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("8. TRANSACTION DATE RANGE")
    emit("=" * 70)
    emit(f"Earliest txn_date: {df['txn_date'].min()}")
    emit(f"Latest txn_date:   {df['txn_date'].max()}")
    emit("")

    # -------------------------------------------------------------------
    # 9. Duplicate rows by txn_id
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("9. DUPLICATE TXN_ID CHECK")
    emit("=" * 70)
    dup_count = df["txn_id"].duplicated().sum()
    emit(f"Duplicate txn_id count: {dup_count}")
    emit("")

    # -------------------------------------------------------------------
    # 10. Mean, median, skewness of amount
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("10. AMOUNT: MEAN, MEDIAN, SKEWNESS")
    emit("=" * 70)
    amount_mean = df["amount"].mean()
    amount_median = df["amount"].median()
    amount_skew = df["amount"].skew()
    emit(f"Mean amount:     {amount_mean:.2f}")
    emit(f"Median amount:   {amount_median:.2f}")
    emit(f"Skewness amount: {amount_skew:.4f}")
    emit("")

    # -------------------------------------------------------------------
    # 11. Group by txn_type: count, mean, median amount (sorted by mean desc)
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("11. AMOUNT BY TXN_TYPE (count, mean, median)")
    emit("=" * 70)
    grouped = (
        df.groupby("txn_type")["amount"]
        .agg(count="count", mean="mean", median="median")
        .round(2)
        .sort_values("mean", ascending=False)
    )
    emit(grouped.to_string())
    emit("")

    # -------------------------------------------------------------------
    # 12. Correlation matrix for shares, price, amount + top 3 correlations
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("12. CORRELATION MATRIX (shares, price, amount)")
    emit("=" * 70)
    corr = df[["shares", "price", "amount"]].corr().round(2)
    emit(corr.to_string())
    emit("")

    # Identify the three strongest correlations, excluding self-correlations
    pairs = []
    cols = corr.columns.tolist()
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append((cols[i], cols[j], corr.iloc[i, j]))
    pairs_sorted = sorted(pairs, key=lambda x: abs(x[2]), reverse=True)[:3]
    emit("Top 3 strongest correlations (by absolute value):")
    for a, b, val in pairs_sorted:
        emit(f"  {a} <-> {b}: {val}")
    emit("")

    # -------------------------------------------------------------------
    # 13. Shares min/max/negative count by txn_type
    # -------------------------------------------------------------------
    emit("=" * 70)
    emit("13. SHARES BY TXN_TYPE (min, max, negative count)")
    emit("=" * 70)
    shares_by_type = df.groupby("txn_type")["shares"].agg(
        min_shares="min",
        max_shares="max",
        negative_count=lambda s: (s < 0).sum(),
    )
    emit(shares_by_type.to_string())
    emit("")

    # -------------------------------------------------------------------
    # 14. Shape validation warning
    # -------------------------------------------------------------------
    print("=" * 70)
    print("14. SHAPE VALIDATION")
    print("=" * 70)
    if df.shape != EXPECTED_SHAPE:
        print(
            f"WARNING: Expected shape {EXPECTED_SHAPE}, "
            f"but found {df.shape}."
        )
    else:
        print(f"Shape check passed: {df.shape} matches expected {EXPECTED_SHAPE}.")
    print()

    # -------------------------------------------------------------------
    # 15. Charts
    # -------------------------------------------------------------------
    os.makedirs(CHARTS_DIR, exist_ok=True)

    # 15a. Histogram of amount with mean/median lines
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(df["amount"].dropna(), bins=60, color="#4C72B0", edgecolor="white")
    ax.axvline(amount_mean, color="#DD8452", linestyle="--", linewidth=2,
               label=f"Mean = {amount_mean:.2f}")
    ax.axvline(amount_median, color="#55A868", linestyle="-", linewidth=2,
               label=f"Median = {amount_median:.2f}")
    ax.set_title("Distribution of Transaction Amount")
    ax.set_xlabel("Amount")
    ax.set_ylabel("Frequency")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS_DIR, "hist_amount.png"), dpi=150)
    plt.close(fig)

    # 15b. Horizontal box plot of amount by txn_type
    fig, ax = plt.subplots(figsize=(10, 6))
    type_order = grouped.index.tolist()
    data_by_type = [
        df.loc[df["txn_type"] == t, "amount"].dropna() for t in type_order
    ]
    try:
        # Matplotlib >= 3.9 renamed 'labels' to 'tick_labels' (and dropped
        # 'labels' entirely in some newer versions).
        ax.boxplot(data_by_type, vert=False, tick_labels=type_order,
                   patch_artist=True,
                   boxprops=dict(facecolor="#4C72B0", alpha=0.6))
    except TypeError:
        # Older Matplotlib versions that don't yet support 'tick_labels'.
        ax.boxplot(data_by_type, vert=False, labels=type_order,
                   patch_artist=True,
                   boxprops=dict(facecolor="#4C72B0", alpha=0.6))
    ax.set_title("Transaction Amount by Type")
    ax.set_xlabel("Amount")
    ax.set_ylabel("Transaction Type")
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS_DIR, "box_amount_by_type.png"), dpi=150)
    plt.close(fig)

    # 15c. Scatter plot of shares vs amount, colored by txn_type
    fig, ax = plt.subplots(figsize=(10, 6))
    types = df["txn_type"].dropna().unique().tolist()
    cmap = plt.get_cmap("tab10")
    for idx, t in enumerate(types):
        subset = df[df["txn_type"] == t]
        ax.scatter(subset["shares"], subset["amount"], s=8, alpha=0.5,
                   color=cmap(idx % 10), label=t)
    ax.set_title("Shares vs. Amount by Transaction Type")
    ax.set_xlabel("Shares")
    ax.set_ylabel("Amount")
    ax.legend(title="Txn Type", markerscale=2)
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS_DIR, "scatter_shares_amount.png"), dpi=150)
    plt.close(fig)

    print(f"Charts saved to: {CHARTS_DIR}")
    print()

    # -------------------------------------------------------------------
    # 16. Save plain-text summary (items 2-13) to hw02_profile.txt
    # -------------------------------------------------------------------
    header = [
        "HW02 EDA PROFILE SUMMARY",
        f"Dataset: {data_path}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    with open(PROFILE_PATH, "w") as f:
        f.write("\n".join(header + report_lines))

    print(f"Text profile summary saved to: {PROFILE_PATH}")


if __name__ == "__main__":
    main()
