#!/usr/bin/env python3
"""
Independently generated charts for hw02, built ONLY from:
  - specification.md item 15 (chart requirements)
  - fact_transactions.csv (the raw data)
Deliberately NOT written by looking at hw02_eda.py.
"""
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_PATH = "02_Data/raw/fact_transactions.csv"
OUT_DIR = "charts_independent_check"
os.makedirs(OUT_DIR, exist_ok=True)

df = pd.read_csv(DATA_PATH)

mean_amt = df["amount"].mean()
median_amt = df["amount"].median()
print(f"amount mean={mean_amt:.2f} median={median_amt:.2f}")

fig, ax = plt.subplots(figsize=(9, 5.5))
ax.hist(df["amount"].dropna(), bins=50)
ax.axvline(mean_amt, linestyle="--", label=f"Mean = {mean_amt:,.2f}")
ax.axvline(median_amt, linestyle="-", label=f"Median = {median_amt:,.2f}")
ax.set_title("Histogram of Transaction Amount")
ax.set_xlabel("Amount")
ax.set_ylabel("Count")
ax.legend()
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "hist_amount.png"), dpi=150)
plt.close(fig)

type_means = df.groupby("txn_type")["amount"].mean().sort_values(ascending=False)
order = type_means.index.tolist()
data_by_type = [df.loc[df["txn_type"] == t, "amount"].dropna() for t in order]

fig, ax = plt.subplots(figsize=(9, 5.5))
try:
    ax.boxplot(data_by_type, vert=False, tick_labels=order)
except TypeError:
    ax.boxplot(data_by_type, vert=False, labels=order)
ax.set_title("Amount by Transaction Type")
ax.set_xlabel("Amount")
ax.set_ylabel("Transaction Type")
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "box_amount_by_type.png"), dpi=150)
plt.close(fig)

fig, ax = plt.subplots(figsize=(9, 5.5))
for t in df["txn_type"].dropna().unique():
    sub = df[df["txn_type"] == t]
    ax.scatter(sub["shares"], sub["amount"], s=6, alpha=0.4, label=t)
ax.set_title("Shares vs. Amount by Transaction Type")
ax.set_xlabel("Shares")
ax.set_ylabel("Amount")
ax.legend(title="txn_type", markerscale=3)
fig.tight_layout()
fig.savefig(os.path.join(OUT_DIR, "scatter_shares_amount.png"), dpi=150)
plt.close(fig)

print("Independent charts written to:", OUT_DIR)
print()
print("Boxplot group order (by mean desc):", order)
print("Group medians:", df.groupby("txn_type")["amount"].median().round(2).to_dict())
print("Group means:", df.groupby("txn_type")["amount"].mean().round(2).to_dict())
types_with_shares = df.dropna(subset=["shares"])["txn_type"].unique().tolist()
print("txn_types that actually have shares data (appear in scatter):", sorted(types_with_shares))
