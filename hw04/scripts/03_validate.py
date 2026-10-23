#!/usr/bin/env python3
"""
scripts/03_validate.py
Validates the eight hw04 tables at two stages - RAW (hw04/*.csv) and CLEAN
(data/clean/*.csv) - and writes reports/data_quality_scorecard.csv.

Contents
  1. check_referential_integrity(fact_df, fact_key, dim_df, dim_key)
     ONE reusable function (kept for Assignment 5; a copy is written to
     scripts/check_referential_integrity.md). Applied to every relationship:
     10 ID-based foreign keys + 3 fact dates -> dim_date.date, discovered from
     the column names rather than typed in by hand.
  2. Rule-based checks for every column with a natural business bound
     (valid ranges, allowed code lists, sign rules, cross-column rules).
  3. Cross-table reconciliations (recomputed value vs stored value).
  4. IQR outlier flags on numeric columns with no natural upper bound.
     A flagged outlier is NOT necessarily wrong: it is only statistically
     unusual, and in this data most are legitimate large accounts (e.g.
     ultra-high-net-worth clients) that need a business check, not a fix.

Scorecard metrics (one row per table per stage)
  pct_completeness      non-blank cells / cells in required columns (columns
                        that are legitimately blank by design - e.g. security_id
                        on cash rows - are judged by a rule instead)
  pct_key_uniqueness    rows whose primary key AND business key are unique
  pct_type_validity     non-blank cells that parse as the column's declared type
  pct_rule_pass         rule + reconciliation evaluations that pass
  pct_referential_match foreign-key values (incl. dates) that exist in the parent
                        table; blank for tables with no foreign keys

Every file is read as text (dtype=str, keep_default_na=False) and converted on
purpose. Nothing is modified; the only outputs are the scorecard and the .md copy.

Usage (from hw04, venv active):
    python scripts/03_validate.py
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE / "data" / "clean"
REPORT = BASE / "reports" / "data_quality_scorecard.csv"
FUNC_COPY = BASE / "scripts" / "check_referential_integrity.md"
TABLES = ["dim_advisor", "dim_benchmark", "dim_client", "dim_date", "dim_security",
          "fact_fees", "fact_portfolio_snapshot", "fact_transactions"]


# =============================================================================
# 1. Reusable referential-integrity check  (keep for Assignment 5)
# =============================================================================
def check_referential_integrity(fact_df, fact_key, dim_df, dim_key):
    """Check that every value of fact_df[fact_key] exists in dim_df[dim_key].

    Keys are compared exactly as stored text after trimming spaces - the same
    way a BI tool joins - so '45.0' does NOT match '45'. Read both tables with
    dtype=str, keep_default_na=False.

    Returns a dict:
        match_rate           share of NON-blank keys found in the dimension (0-1)
        orphan_rows          DataFrame of fact rows whose non-blank key is missing
        distinct_orphan_keys sorted list of the missing key values
        null_key_rate        share of fact rows whose key is blank (0-1)
        n_rows, n_non_null, n_orphan_rows   counts behind the rates
    """
    fk = fact_df[fact_key].astype(str).str.strip()
    pk = set(dim_df[dim_key].astype(str).str.strip())
    is_null = fk.isin(["", "nan", "NaN", "None", "NULL", "null"])
    non_null = ~is_null
    orphan = non_null & ~fk.isin(pk)
    n, n_nn = len(fk), int(non_null.sum())
    keys = fk[orphan].unique().tolist()
    try:
        keys = sorted(keys, key=float)
    except ValueError:
        keys = sorted(keys)
    return {
        "match_rate": (n_nn - int(orphan.sum())) / n_nn if n_nn else 1.0,
        "orphan_rows": fact_df[orphan],
        "distinct_orphan_keys": keys,
        "null_key_rate": int(is_null.sum()) / n if n else 0.0,
        "n_rows": n,
        "n_non_null": n_nn,
        "n_orphan_rows": int(orphan.sum()),
    }


# =============================================================================
# Schema: declared type per column (what a BI tool should use)
# =============================================================================
SCHEMA = {
    "dim_advisor": dict(advisor_id="int", first_name="text", last_name="text", region="text",
                        years_experience="int", aum_target_mm="int", certifications="text"),
    "dim_benchmark": dict(benchmark_id="int", name="text", asset_class="text", ticker_proxy="text"),
    "dim_client": dict(client_id="int", first_name="text", last_name="text", age="int", city="text",
                       state="text", zip_code="zip", risk_profile="text", client_tier="text",
                       primary_account_type="text", initial_aum="dec", client_since="date",
                       advisor_id="int", is_active="bool"),
    "dim_date": dict(date_id="int", date="date", year="int", quarter="int", month="int",
                     month_name="text", week_of_year="int", day_of_week="text", is_month_end="flag",
                     is_quarter_end="flag", is_year_end="flag", is_trading_day="flag"),
    "dim_security": dict(security_id="int", ticker="text", name="text", asset_class="text",
                         sector="text", benchmark_id="int", is_etf="bool", expense_ratio_bps="int"),
    "fact_fees": dict(fee_id="int", client_id="int", advisor_id="int", fee_date="date",
                      fee_type="text", aum_basis="dec", bps_charged="dec", amount="dec"),
    "fact_portfolio_snapshot": dict(snapshot_id="int", client_id="int", advisor_id="int",
                                    benchmark_id="int", snapshot_date="date", year="int", month="int",
                                    aum="dec", return_ytd="dec", benchmark_return_ytd="dec",
                                    active_alpha_ytd="dec", cash_pct="dec", account_type="text"),
    "fact_transactions": dict(txn_id="int", client_id="int", advisor_id="int", security_id="int",
                              txn_date="date", txn_type="text", shares="dec", price="dec", amount="dec"),
}
# blank by design (judged by conditional rules, not by completeness)
OPTIONAL = {("dim_security", "sector"), ("dim_security", "expense_ratio_bps"),
            ("fact_transactions", "security_id"), ("fact_transactions", "shares"),
            ("fact_transactions", "price")}
BUSINESS_KEY = {
    "dim_advisor": ["first_name", "last_name", "region"],
    "dim_benchmark": ["ticker_proxy"],
    "dim_client": ["first_name", "age", "city", "zip_code", "initial_aum", "client_since", "advisor_id"],
    "dim_date": ["date"],
    "dim_security": ["ticker"],
    "fact_fees": ["client_id", "fee_date"],
    "fact_portfolio_snapshot": ["client_id", "snapshot_date"],
    "fact_transactions": [],          # events: several per client per day are legitimate
}

TYPE_RX = {
    "int": r"-?\d+",
    "dec": r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?",
    "date": r"\d{4}-\d{2}-\d{2}",
    "bool": r"True|False",
    "flag": r"[01]",
    "zip": r"\d{5}",
}

US_CODES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
               "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
GICS = {"Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy", "Financials",
        "Healthcare", "Industrials", "Materials", "Real Estate", "Technology", "Utilities"}
TRADE_TYPES = {"Buy", "Sell", "Dividend"}
CASH_TYPES = {"Deposit", "Withdrawal", "Advisory Fee"}


# =============================================================================
# helpers
# =============================================================================
def read_text(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def load_stage(stage: str) -> dict[str, pd.DataFrame]:
    out = {}
    for t in TABLES:
        if stage == "raw":
            p = BASE / f"{t}.csv"
            if not p.exists():
                p = sorted(BASE.glob(f"{t} (*).csv"))[0]
        else:
            p = CLEAN_DIR / f"{t}.csv"
        out[t] = read_text(p)
    return out


def declared_types(t: str, df: pd.DataFrame) -> dict:
    types = dict(SCHEMA[t])
    for c in df.columns:
        if c not in types:          # flag columns added by 02_clean.py
            types[c] = "flag"
    return types


def type_ok(s: pd.Series, typ: str) -> pd.Series:
    st = s.str.strip()
    if typ == "text":
        return pd.Series(True, index=s.index)
    ok = st.str.fullmatch(TYPE_RX[typ])
    if typ == "date":
        ok &= pd.to_datetime(st.where(ok), format="%Y-%m-%d", errors="coerce").notna()
    return ok


def num(s: pd.Series) -> pd.Series:
    """Strict numeric conversion: anything that is not a plain number -> NaN."""
    st = s.str.strip()
    ok = st.str.fullmatch(TYPE_RX["dec"])
    return pd.to_numeric(st.where(ok), errors="coerce")


def dates(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s.str.strip(), format="%Y-%m-%d", errors="coerce")


# =============================================================================
# 2. Rule-based checks (natural business bounds)
# Each rule returns (applicable_mask, pass_mask). A value that cannot be parsed
# where a number/date is required counts as a FAIL - it cannot meet the bound.
# =============================================================================
def r_range(col, lo=None, hi=None, integer=False, when=None):
    def f(T, df):
        s = df[col].str.strip()
        app = s.ne("") & (when(T, df) if when else True)
        v = num(df[col])
        ok = v.notna()
        if integer:
            ok &= s.str.fullmatch(r"-?\d+")
        if lo is not None:
            ok &= v >= lo
        if hi is not None:
            ok &= v <= hi
        return app, ok
    bounds = f"[{lo if lo is not None else '-inf'}, {hi if hi is not None else 'inf'}]"
    return (col, f"{col} {'integer ' if integer else ''}in {bounds}", f)


def r_allowed(col, values, blank_ok=False):
    def f(T, df):
        s = df[col].str.strip()
        app = pd.Series(True, index=df.index) if not blank_ok else s.ne("")
        return app, s.isin(values)
    return (col, f"{col} in allowed list ({len(values)} values)", f)


def r_pattern(col, rx, label):
    def f(T, df):
        s = df[col].str.strip()
        return s.ne(""), s.str.fullmatch(rx)
    return (col, f"{col} {label}", f)


def r_custom(col, label, fn):
    return (col, label, fn)


def snapshot_parts(T, df):
    d = dates(df.snapshot_date)
    return d


RULES = {
    "dim_advisor": [
        r_range("years_experience", 0, 60, integer=True),
        r_range("aum_target_mm", 1, 10000, integer=True),
        r_allowed("region", {"Northeast", "Southeast", "Mid-Atlantic", "Midwest", "West", "Southwest"}),
        r_custom("certifications", "certifications are CFA/CFP/CIMA lists or 'None'",
                 lambda T, df: (pd.Series(True, index=df.index),
                                df.certifications.map(lambda v: v == "None" or
                                                      set(x.strip() for x in v.split(",")) <= {"CFA", "CFP", "CIMA"}))),
    ],
    "dim_benchmark": [
        r_allowed("asset_class", {"Equity", "Fixed Income", "Multi-Asset", "International", "Small Cap",
                                  "Emerging", "Cash"}),
        r_pattern("ticker_proxy", r"[A-Z0-9_]{2,12}", "is an upper-case ticker/code"),
    ],
    "dim_client": [
        r_range("age", 18, 110, integer=True),
        r_allowed("state", US_CODES),
        r_pattern("zip_code", r"\d{5}", "is 5 digits (leading zeros kept)"),
        r_allowed("risk_profile", {"Conservative", "Moderately Conservative", "Balanced",
                                   "Moderately Aggressive", "Aggressive"}),
        r_allowed("client_tier", {"Retail", "HNW", "UHNW"}),
        r_allowed("primary_account_type", {"Taxable", "IRA", "Roth IRA", "Trust", "529"}),
        r_range("initial_aum", 0.01),
        r_custom("client_since", "client_since is a valid date on or before 2024-12-31",
                 lambda T, df: (pd.Series(True, index=df.index),
                                dates(df.client_since).le(pd.Timestamp("2024-12-31")))),
        r_allowed("is_active", {"True", "False"}),
        r_custom("client_tier", "client_tier matches initial_aum band (Retail <500k, HNW 500k-5M, UHNW >=5M)",
                 lambda T, df: (pd.Series(True, index=df.index),
                                pd.Series(np.select([num(df.initial_aum) < 5e5, num(df.initial_aum) < 5e6,
                                                     num(df.initial_aum) >= 5e6], ["Retail", "HNW", "UHNW"], ""),
                                          index=df.index).eq(df.client_tier))),
    ],
    "dim_date": [
        r_range("year", 2020, 2024, integer=True),
        r_range("quarter", 1, 4, integer=True),
        r_range("month", 1, 12, integer=True),
        r_range("week_of_year", 1, 53, integer=True),
        r_allowed("day_of_week", {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}),
        r_custom("date", "year/quarter/month/month_name/day_of_week agree with date",
                 lambda T, df: (pd.Series(True, index=df.index),
                                (dates(df.date).dt.year.astype("Int64").astype(str) == df.year)
                                & (dates(df.date).dt.quarter.astype("Int64").astype(str) == df.quarter)
                                & (dates(df.date).dt.month.astype("Int64").astype(str) == df.month)
                                & (dates(df.date).dt.month_name() == df.month_name)
                                & (dates(df.date).dt.day_name() == df.day_of_week))),
        r_custom("is_month_end", "month/quarter/year-end flags agree with date",
                 lambda T, df: (pd.Series(True, index=df.index),
                                (dates(df.date).dt.is_month_end.astype(int).astype(str) == df.is_month_end)
                                & (dates(df.date).dt.is_quarter_end.astype(int).astype(str) == df.is_quarter_end)
                                & (dates(df.date).dt.is_year_end.astype(int).astype(str) == df.is_year_end))),
        r_custom("is_trading_day", "weekends are never trading days",
                 lambda T, df: (dates(df.date).dt.dayofweek >= 5, df.is_trading_day == "0")),
    ],
    "dim_security": [
        r_pattern("ticker", r"[A-Z]{1,5}", "is 1-5 upper-case letters"),
        r_allowed("asset_class", {"Equity", "Fixed Income", "Alternative", "Cash Equivalent"}),
        r_allowed("is_etf", {"True", "False"}),
        r_range("expense_ratio_bps", 0, 300, integer=True, when=lambda T, df: df.is_etf == "True"),
        r_custom("expense_ratio_bps", "expense_ratio_bps blank exactly when not an ETF",
                 lambda T, df: (pd.Series(True, index=df.index),
                                (df.expense_ratio_bps.str.strip() == "") == (df.is_etf == "False"))),
        r_custom("sector", "sector is a GICS sector for stocks and blank for funds",
                 lambda T, df: (pd.Series(True, index=df.index),
                                np.where(df.is_etf == "False", df.sector.isin(GICS), df.sector == ""))),
    ],
    "fact_fees": [
        r_allowed("fee_type", {"Management", "Advisory", "Custodial", "Performance"}),
        r_range("aum_basis", 0.01),
        r_range("bps_charged", 0, 300),
        r_range("amount", 0),
        r_custom("fee_date", "fee_date is the 1st of a month",
                 lambda T, df: (pd.Series(True, index=df.index), dates(df.fee_date).dt.day.eq(1))),
    ],
    "fact_portfolio_snapshot": [
        r_range("aum", 0),
        r_range("return_ytd", -1),
        r_range("benchmark_return_ytd", -1),
        r_range("cash_pct", 0, 1),
        r_range("year", 2020, 2024, integer=True),
        r_range("month", 1, 12, integer=True),
        r_allowed("account_type", {"Taxable", "IRA", "Roth IRA", "Trust", "529"}),
        r_custom("snapshot_date", "snapshot_date is the 1st and matches year/month",
                 lambda T, df: (pd.Series(True, index=df.index),
                                dates(df.snapshot_date).dt.day.eq(1)
                                & (dates(df.snapshot_date).dt.year.astype("Int64").astype(str) == df.year)
                                & (dates(df.snapshot_date).dt.month.astype("Int64").astype(str) == df.month))),
    ],
    "fact_transactions": [
        r_allowed("txn_type", TRADE_TYPES | CASH_TYPES),
        r_range("amount", 0.01),
        r_range("shares", 0.0001, when=lambda T, df: df.txn_type.isin(TRADE_TYPES)),
        r_range("price", 0.01, when=lambda T, df: df.txn_type.isin(TRADE_TYPES)),
        r_custom("security_id", "security_id/shares/price filled for trades and blank for cash/fee rows",
                 lambda T, df: (pd.Series(True, index=df.index),
                                ((df.security_id != "") & (df.shares != "") & (df.price != ""))
                                == df.txn_type.isin(TRADE_TYPES))),
    ],
}


# =============================================================================
# 3. Cross-table reconciliations: recomputed / second-source value vs stored
# Each returns (table charged, applicable_mask, pass_mask, description).
# =============================================================================
def rec_fee_formula(T):
    f = T["fact_fees"]
    recomputed = num(f.aum_basis) * num(f.bps_charged) / 120000
    return ("fact_fees", pd.Series(True, index=f.index), (recomputed - num(f.amount)).abs() <= 0.01,
            "fee amount recomputed = aum_basis x bps_charged / 120000 vs stored amount (1 cent)")


def rec_fee_basis_vs_snapshot(T):
    f, s = T["fact_fees"], T["fact_portfolio_snapshot"]
    aum = pd.Series(num(s.aum).values, index=(s.client_id + "|" + s.snapshot_date.str[:7]).values)
    aum = aum[~aum.index.duplicated()]
    other = (f.client_id + "|" + f.fee_date.str[:7]).map(aum)
    app = other.notna()
    return ("fact_fees", app, (num(f.aum_basis) - other).abs() <= 0.005,
            "fact_fees.aum_basis vs fact_portfolio_snapshot.aum for the same client and month")


def rec_trade_amount(T):
    t = T["fact_transactions"]
    app = t.txn_type.isin(["Buy", "Sell"])
    recomputed = num(t.shares) * num(t.price)
    return ("fact_transactions", app, (recomputed - num(t.amount)).abs() <= 0.01,
            "Buy/Sell amount recomputed = shares x price vs stored amount (1 cent)")


def rec_return_identity(T):
    s = T["fact_portfolio_snapshot"]
    recomputed = num(s.benchmark_return_ytd) + num(s.active_alpha_ytd)
    return ("fact_portfolio_snapshot", pd.Series(True, index=s.index),
            (recomputed - num(s.return_ytd)).abs() <= 6e-5,
            "return_ytd recomputed = benchmark_return_ytd + active_alpha_ytd vs stored")


def rec_advisor_matches_client(T):
    c = T["dim_client"].drop_duplicates("client_id").set_index("client_id").advisor_id
    rows = []
    for name in ("fact_fees", "fact_portfolio_snapshot", "fact_transactions"):
        df = T[name]
        exp = df.client_id.map(c)
        rows.append((name, exp.notna(), exp == df.advisor_id,
                     f"{name}.advisor_id vs dim_client.advisor_id for the same client"))
    return rows


def rec_account_type(T):
    s = T["fact_portfolio_snapshot"]
    c = T["dim_client"].drop_duplicates("client_id").set_index("client_id").primary_account_type
    exp = s.client_id.map(c)
    return ("fact_portfolio_snapshot", exp.notna(), exp == s.account_type,
            "snapshot account_type vs dim_client.primary_account_type")


def rec_advisory_fees(T):
    t, f = T["fact_transactions"], T["fact_fees"]
    af = t.txn_type == "Advisory Fee"
    kt = t.client_id + "|" + t.txn_date.str[:4]
    kf = f.client_id + "|" + f.fee_date.str[:4]
    tot_t = num(t.amount)[af].groupby(kt[af]).sum()
    tot_f = num(f.amount).groupby(kf).sum()
    ok_keys = set(tot_t.index[np.isclose(tot_t.values, tot_f.reindex(tot_t.index).fillna(0).values, rtol=0.01)])
    return ("fact_transactions", af, kt.isin(ok_keys),
            "Advisory Fee transactions vs fact_fees, client-year totals within 1%")


RECONCILIATIONS = [rec_fee_formula, rec_fee_basis_vs_snapshot, rec_trade_amount, rec_return_identity,
                   rec_advisor_matches_client, rec_account_type, rec_advisory_fees]

# =============================================================================
# 4. IQR outliers on numeric columns with no natural upper bound
# =============================================================================
IQR_COLUMNS = [("dim_client", "initial_aum"), ("fact_portfolio_snapshot", "aum"),
               ("fact_fees", "amount"), ("fact_transactions", "amount")]
IQR_SENTENCE = ("Flagged does not mean wrong: an IQR outlier is only far from the middle of the "
                "distribution, and in wealth data most are real large accounts (see how they sit inside "
                "client_tier), so each one needs a business check rather than a correction.")


def iqr_flags(T, stage):
    print(f"\n  IQR outliers (1.5 x IQR) - {stage}")
    c = T["dim_client"].drop_duplicates("client_id").set_index("client_id").client_tier
    for t, col in IQR_COLUMNS:
        v = num(T[t][col])
        q1, q3 = v.quantile([0.25, 0.75])
        lo, hi = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        out = (v < lo) | (v > hi)
        tiers = ""
        if "client_id" in T[t].columns or t == "dim_client":
            key = T[t].client_id
            tiers = "; by tier: " + ", ".join(f"{k} {n:,}" for k, n in key[out].map(c).value_counts().items())
        print(f"    {t}.{col}: {int(out.sum()):,} of {int(v.notna().sum()):,} flagged "
              f"(outside {lo:,.2f} .. {hi:,.2f}){tiers}")
    print(f"    {IQR_SENTENCE}")


# =============================================================================
# relationship discovery
# =============================================================================
def discover_relationships(T):
    pk = {t: T[t].columns[0] for t in TABLES}
    owner = {v: k for k, v in pk.items()}
    rels = []
    for t in TABLES:
        for col in T[t].columns:
            if col.endswith("_id") and col != pk[t] and col in owner and owner[col] != t:
                rels.append((t, col, owner[col], col))
    id_rels = list(rels)
    date_rels = [(t, col, "dim_date", "date") for t in TABLES if t.startswith("fact_")
                 for col, typ in SCHEMA[t].items() if typ == "date"]
    assert len(id_rels) == 10, f"expected 10 ID relationships, found {len(id_rels)}: {id_rels}"
    assert len(date_rels) == 3, f"expected 3 date relationships, found {len(date_rels)}"
    return id_rels, date_rels


# =============================================================================
# scoring
# =============================================================================
def score_stage(T, stage):
    print("\n" + "=" * 100 + f"\nSTAGE: {stage.upper()}\n" + "=" * 100)
    id_rels, date_rels = discover_relationships(T)

    # ---- referential integrity
    print(f"\n  Referential integrity ({len(id_rels)} ID + {len(date_rels)} date relationships, text join)")
    print(f"    {'relationship':<62}{'match':>9}{'orphans':>9}{'keys':>7}{'null':>8}")
    ri = {t: [0, 0] for t in TABLES}          # non-null keys, matched keys
    for t, col, d, dcol in id_rels + date_rels:
        r = check_referential_integrity(T[t], col, T[d], dcol)
        ri[t][0] += r["n_non_null"]
        ri[t][1] += r["n_non_null"] - r["n_orphan_rows"]
        ex = ", ".join(r["distinct_orphan_keys"][:3])
        print(f"    {t + '.' + col + ' -> ' + d + '.' + dcol:<62}{r['match_rate']:>8.1%}"
              f"{r['n_orphan_rows']:>9,}{len(r['distinct_orphan_keys']):>7,}{r['null_key_rate']:>8.1%}"
              + (f"   e.g. {ex}" if ex else ""))

    # ---- rules
    rule_tot = {t: [0, 0] for t in TABLES}
    failures = []
    for t in TABLES:
        for col, label, fn in RULES[t]:
            if col not in T[t].columns:
                continue
            app, ok = fn(T, T[t])
            app = pd.Series(app, index=T[t].index).fillna(False).astype(bool)
            ok = pd.Series(ok, index=T[t].index).fillna(False).astype(bool)
            n_app, n_ok = int(app.sum()), int((app & ok).sum())
            rule_tot[t][0] += n_app
            rule_tot[t][1] += n_ok
            if n_ok < n_app:
                failures.append((t, label, n_app - n_ok, n_app))

    # ---- reconciliations
    print("\n  Cross-table reconciliations")
    for rec in RECONCILIATIONS:
        res = rec(T)
        for tname, app, ok, label in (res if isinstance(res, list) else [res]):
            app = app.fillna(False).astype(bool)
            ok = ok.fillna(False).astype(bool)
            n_app, n_ok = int(app.sum()), int((app & ok).sum())
            rule_tot[tname][0] += n_app
            rule_tot[tname][1] += n_ok
            print(f"    {n_ok / n_app if n_app else 1:>7.2%}  {n_ok:>9,} / {n_app:<9,} {label}")

    print("\n  Rule failures")
    if not failures:
        print("    none")
    for t, label, bad, n_app in failures:
        print(f"    {t:<25} {bad:>8,} of {n_app:<9,} fail: {label}")

    iqr_flags(T, stage)

    # ---- scorecard rows
    rows = []
    for t in TABLES:
        df = T[t]
        types = declared_types(t, df)
        req = [c for c in df.columns if (t, c) not in OPTIONAL]
        cells = df[req].apply(lambda s: s.str.strip() != "")
        completeness = cells.values.mean()
        pk = df.columns[0]
        uniq = ~df[pk].duplicated(keep=False)
        bk = BUSINESS_KEY[t]
        if bk:
            uniq &= ~df[bk].apply(lambda s: s.str.strip().str.casefold()).duplicated(keep=False)
        valid = n_cells = 0
        for c in df.columns:
            nb = df[c].str.strip() != ""
            valid += int((type_ok(df[c], types[c]) & nb).sum())
            n_cells += int(nb.sum())
        rows.append(dict(
            table=t, stage=stage, rows=len(df),
            pct_completeness=round(100 * completeness, 3),
            pct_key_uniqueness=round(100 * uniq.mean(), 3),
            pct_type_validity=round(100 * valid / n_cells, 3) if n_cells else 100.0,
            pct_rule_pass=round(100 * rule_tot[t][1] / rule_tot[t][0], 3) if rule_tot[t][0] else 100.0,
            pct_referential_match=round(100 * ri[t][1] / ri[t][0], 3) if ri[t][0] else np.nan,
        ))
    return rows


def save_function_copy():
    src = inspect.getsource(check_referential_integrity)
    FUNC_COPY.write_text(
        "# Reusable function: `check_referential_integrity`\n\n"
        "From `hw04/scripts/03_validate.py` (Assignment 4) - saved for reuse in Assignment 5.\n\n"
        "## Code\n\n```python\nimport pandas as pd\n\n\n" + src + "```\n\n"
        "## Example\n\n```python\n"
        "fact = pd.read_csv('fact_fees.csv', dtype=str, keep_default_na=False)\n"
        "dim = pd.read_csv('dim_client.csv', dtype=str, keep_default_na=False)\n"
        "r = check_referential_integrity(fact, 'client_id', dim, 'client_id')\n"
        "print(f\"match {r['match_rate']:.1%}, orphans {r['n_orphan_rows']}, \"\n"
        "      f\"keys {r['distinct_orphan_keys'][:5]}, null {r['null_key_rate']:.1%}\")\n"
        "r['orphan_rows'].to_csv('orphans.csv', index=False)   # inspect the failing rows\n"
        "```\n\n"
        "## Notes\n\n"
        "- Keys are compared as trimmed text, the way a BI tool joins; `'45.0'` does not match `'45'`.\n"
        "- `match_rate` is computed over non-blank keys; blanks are reported separately as `null_key_rate`.\n"
        "- For a date relationship pass the date columns, e.g. "
        "`check_referential_integrity(fees, 'fee_date', dim_date, 'date')`.\n",
        encoding="utf-8")


def main():
    rows = []
    for stage in ("raw", "clean"):
        rows += score_stage(load_stage(stage), stage)
    card = pd.DataFrame(rows)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    card.to_csv(REPORT, index=False)
    save_function_copy()

    print("\n" + "=" * 100 + "\nDATA QUALITY SCORECARD (%)\n" + "=" * 100)
    view = card.pivot(index="table", columns="stage",
                      values=["pct_completeness", "pct_key_uniqueness", "pct_type_validity",
                              "pct_rule_pass", "pct_referential_match"])
    metrics = ["pct_completeness", "pct_key_uniqueness", "pct_type_validity", "pct_rule_pass",
               "pct_referential_match"]
    view = view[[(m, st) for m in metrics for st in ("raw", "clean")]]
    view.columns = [f"{m.replace('pct_', '').split('_')[0][:8]}|{st}" for m, st in view.columns]
    print(view.reindex(TABLES).round(2).to_string(na_rep="n/a"))
    print(f"\nWrote {REPORT}")
    print(f"Wrote {FUNC_COPY}")


if __name__ == "__main__":
    main()
