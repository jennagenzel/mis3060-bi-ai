"""
HW5 key and grain checks for the Wildcat Capital star schema.

Part A: every primary key is unique and never blank
Part A: every foreign key matches its target table
        (security_id may be blank only on cash transactions)
Part A: fact dates match dim_date[date]
Part B: each fact table's grain is unique

Run from the hw05 folder (with .venv activated):
    python checks_keys.py
"""

from pathlib import Path
import sys

import pandas as pd

DATA = Path(__file__).resolve().parent

TABLES = [
    "dim_advisor", "dim_benchmark", "dim_client", "dim_date", "dim_security",
    "fact_fees", "fact_portfolio_snapshot", "fact_transactions",
]

# Read every column as text so IDs, dates and zip codes stay exactly as in the CSV,
# and blank cells stay as empty strings (not NaN).
t = {
    name: pd.read_csv(DATA / f"{name}.csv", dtype=str, keep_default_na=False)
    for name in TABLES
}

results = []  # (part, check, passed, detail)


def check(part, name, passed, detail=""):
    results.append((part, name, bool(passed), detail))
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))


# ---------------------------------------------------------------------------
# Row counts (match the handout before checking anything else)
# ---------------------------------------------------------------------------
print("\nRow counts vs. handout")
HANDOUT = {
    "dim_advisor": 25, "dim_benchmark": 8, "dim_client": 2500, "dim_date": 1827,
    "dim_security": 500, "fact_fees": 122197, "fact_portfolio_snapshot": 129547,
    "fact_transactions": 298572,
}
for name, expected in HANDOUT.items():
    actual = len(t[name])
    check("A", f"{name} has {expected:,} rows", actual == expected, f"found {actual:,}")


# ---------------------------------------------------------------------------
# Part A: primary keys are unique and never blank
# ---------------------------------------------------------------------------
print("\nPart A: primary keys are unique and never blank")
PRIMARY_KEYS = {
    "dim_advisor": "advisor_id",
    "dim_benchmark": "benchmark_id",
    "dim_client": "client_id",
    "dim_date": "date_id",
    "dim_security": "security_id",
    "fact_fees": "fee_id",
    "fact_portfolio_snapshot": "snapshot_id",
    "fact_transactions": "txn_id",
}
for table, pk in PRIMARY_KEYS.items():
    col = t[table][pk]
    blanks = (col == "").sum()
    dupes = col.duplicated().sum()
    check("A", f"{table}[{pk}] is unique and never blank",
          blanks == 0 and dupes == 0, f"{blanks} blank, {dupes} duplicate")

# dim_date[date] is the column the facts join to, so it must also be unique.
col = t["dim_date"]["date"]
check("A", "dim_date[date] is unique and never blank",
      (col == "").sum() == 0 and not col.duplicated().any(),
      f"{(col == '').sum()} blank, {col.duplicated().sum()} duplicate")


# ---------------------------------------------------------------------------
# Part A: foreign keys match their target table
# ---------------------------------------------------------------------------
print("\nPart A: foreign keys match their target table")
FOREIGN_KEYS = [
    # (from table, column, to table, column)
    ("dim_client", "advisor_id", "dim_advisor", "advisor_id"),
    ("dim_security", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_fees", "client_id", "dim_client", "client_id"),
    ("fact_fees", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "client_id", "dim_client", "client_id"),
    ("fact_portfolio_snapshot", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_portfolio_snapshot", "benchmark_id", "dim_benchmark", "benchmark_id"),
    ("fact_transactions", "client_id", "dim_client", "client_id"),
    ("fact_transactions", "advisor_id", "dim_advisor", "advisor_id"),
    ("fact_transactions", "security_id", "dim_security", "security_id"),
]
CASH_TYPES = {"Deposit", "Withdrawal", "Advisory Fee"}

for src, fk, tgt, pk in FOREIGN_KEYS:
    values = t[src][fk]
    valid = set(t[tgt][pk])
    blank = values == ""
    orphans = (~blank & ~values.isin(valid)).sum()

    if (src, fk) == ("fact_transactions", "security_id"):
        # Blanks are allowed, but only on cash transactions.
        txn_type = t[src]["txn_type"]
        is_cash = txn_type.isin(CASH_TYPES)
        blank_on_trades = (blank & ~is_cash).sum()
        filled_on_cash = (~blank & is_cash).sum()
        check("A", f"{src}[{fk}] -> {tgt}[{pk}] (non-blank values)", orphans == 0,
              f"{orphans} orphans")
        check("A", "security_id is blank only on Deposit/Withdrawal/Advisory Fee rows",
              blank_on_trades == 0,
              f"{blank.sum():,} blank, {blank_on_trades} on Buy/Sell/Dividend rows")
        check("A", "no Deposit/Withdrawal/Advisory Fee row has a security_id",
              filled_on_cash == 0,
              f"{filled_on_cash} cash rows have a security_id")
    else:
        check("A", f"{src}[{fk}] -> {tgt}[{pk}]",
              blank.sum() == 0 and orphans == 0,
              f"{blank.sum()} blank, {orphans} orphans")


# ---------------------------------------------------------------------------
# Part A: fact dates match dim_date[date], not dim_date[date_id]
# ---------------------------------------------------------------------------
print("\nPart A: fact dates match dim_date[date]")
FACT_DATES = [
    ("fact_fees", "fee_date"),
    ("fact_portfolio_snapshot", "snapshot_date"),
    ("fact_transactions", "txn_date"),
]
calendar_dates = set(t["dim_date"]["date"])
date_ids = set(t["dim_date"]["date_id"])
for table, col in FACT_DATES:
    values = t[table][col]
    blanks = (values == "").sum()
    unmatched = (~values.isin(calendar_dates)).sum()
    matches_id = values.isin(date_ids).sum()
    check("A", f"{table}[{col}] -> dim_date[date]",
          blanks == 0 and unmatched == 0,
          f"{blanks} blank, {unmatched} unmatched")
    check("A", f"{table}[{col}] does NOT match dim_date[date_id]",
          matches_id == 0, f"{matches_id} values look like a date_id")


# ---------------------------------------------------------------------------
# Part B: grain is unique
# ---------------------------------------------------------------------------
print("\nPart B: grain is unique")
GRAINS = [
    ("fact_fees", ["client_id", "fee_date"],
     "one row per client per month"),
    ("fact_portfolio_snapshot", ["client_id", "snapshot_date"],
     "one row per client per month"),
    ("fact_transactions", ["txn_id"],
     "one row per transaction"),
]
for table, cols, label in GRAINS:
    dupes = t[table].duplicated(subset=cols).sum()
    check("B", f"{table}: {label} ({', '.join(cols)})", dupes == 0,
          f"{dupes} duplicate rows")

# Fees and snapshots are monthly: every date is the 1st of a month.
for table, col in [("fact_fees", "fee_date"), ("fact_portfolio_snapshot", "snapshot_date")]:
    not_first = (~t[table][col].str.endswith("-01")).sum()
    check("B", f"{table}[{col}] is always the 1st of a month",
          not_first == 0, f"{not_first} dates are not the 1st")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
passed = sum(r[2] for r in results)
failed = len(results) - passed
print(f"\nSummary: {passed} passed, {failed} failed")
if failed:
    print("Failed checks:")
    for part, name, ok, detail in results:
        if not ok:
            print(f"  Part {part}: {name} ({detail})")
sys.exit(1 if failed else 0)
