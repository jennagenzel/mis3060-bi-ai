#!/usr/bin/env python3
"""
scripts/02_clean.py
Cleans the eight raw hw04 tables according to decision_log.md (which was built
from the findings of scripts/01_profile.py).

Rules followed
  * Raw files are only ever READ (as text: dtype=str, keep_default_na=False).
    Their SHA-256 hashes are taken at the start and re-checked at the end.
  * One transformation at a time. Each prints rows affected and a before/after
    check, then asserts the after-state; a failed assert stops the script.
  * Repairs are confirmed by reconciliation (a column recomputed from others,
    or a second table describing the same fact) BEFORE they are applied.
  * Suspicious values that cannot be corrected without inventing data get a
    0/1 flag column instead of a change.
  * Removed rows go to data/audit/quarantine_*.csv and every table proves
    raw rows = clean rows + quarantined rows.

Order of operations (and why)
  1. C1 quarantine duplicate clients FIRST - every later step then works only on
     real clients, so no fix is applied to a row that is about to be removed.
  2. C2 standardize state, then C3 fill risk_profile - both run after C1, so the
     counts and the benchmark -> profile evidence describe real clients only.
  3. S1 expense_ratio_bps - independent of every other table.
  4. P1 convert '%' returns BEFORE P2 flags extreme returns - the 300 '%' values
     cannot be compared with the -75% / +300% bounds until they are decimals.
  5. P3 aum_at_floor BEFORE F1 fee_on_floor_aum - the fee flag is confirmed by
     matching each fee to a snapshot already flagged at the floor; P4 fee_missing
     likewise needs fact_fees, which is never row-filtered.
  6. T1 quarantine orphan transactions BEFORE T2-T7 - repairs and flags are not
     spent on rows that cannot join to a client (one negative-shares row belongs
     to an orphan, so T3 corrects 835, not 836).
  7. T2 security_id convert BEFORE the final validation - the text joins to
     dim_security can only be tested once '45.0' has become '45'.
  8. T5-T7 last - they read the cleaned snapshots, clients and fees.
  9. Validation runs once at the end over the finished tables, then the raw-file
     hashes are re-checked.

Usage (from the hw04 folder, venv active):
    python scripts/02_clean.py

Outputs
    data/clean/<table>.csv              8 cleaned tables (same names and columns + flags)
    data/clean/README_clean.md          relationships, BI column types, flags, limitations
    data/audit/cleaning_log.csv         table, issue, action, rows_affected, note
    data/audit/value_changes.csv        table, key_column, key, column, old_value, new_value
    data/audit/quarantine_*.csv         one file per quarantined set
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent.parent
RAW_DIR = BASE
CLEAN_DIR = BASE / "data" / "clean"
AUDIT_DIR = BASE / "data" / "audit"

TABLES = ["dim_advisor", "dim_benchmark", "dim_client", "dim_date", "dim_security",
          "fact_fees", "fact_portfolio_snapshot", "fact_transactions"]

US_STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
    "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL",
    "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA",
    "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT",
    "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
    "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
    "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN",
    "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

# Thresholds taken from decision_log.md (#9): returns outside these bounds are
# impossible as investment performance.
RETURN_FLAG_LOW, RETURN_FLAG_HIGH = -0.75, 3.0
AUM_FLOOR = 1000.0
MONEY_TOL = 0.01          # one cent: amount = shares x price, fee formula
RATE_TOL = 6e-5           # half a basis point of rounding on a 2-decimal % value

# ---------------------------------------------------------------------------
# audit trail
# ---------------------------------------------------------------------------
LOG: list[dict] = []
CHANGES: list[pd.DataFrame] = []
QUARANTINE: dict[str, pd.DataFrame] = {}      # file suffix -> rows
QUARANTINED_ROWS: dict[str, int] = {t: 0 for t in TABLES}
FLAGS: list[dict] = []                         # table, column, meaning, rows flagged


def log(table, issue, action, rows, note=""):
    LOG.append(dict(table=table, issue=issue, action=action, rows_affected=int(rows), note=note))


def header(code, table, issue, action):
    print(f"\n[{code}] {table} | {issue} -> {action}")


def show(label, text):
    print(f"    {label:<15}{text}")


def passed():
    print("    PASS")


def num(s: pd.Series) -> pd.Series:
    """Explicit text -> float conversion; blanks become NaN, anything else must parse."""
    st = s.str.strip()
    out = pd.to_numeric(st.where(st != ""), errors="coerce")
    return out


def change(table, df, mask, col, new_values: pd.Series):
    """Apply a value change and record old/new per row in value_changes."""
    pk = df.columns[0]
    mask = mask.fillna(False).astype(bool)
    new_values = pd.Series(new_values, index=df.index[mask]) if not isinstance(new_values, pd.Series) \
        else new_values.reindex(df.index[mask])
    CHANGES.append(pd.DataFrame({
        "table": table, "key_column": pk, "key": df.loc[mask, pk].values,
        "column": col, "old_value": df.loc[mask, col].values, "new_value": new_values.values}))
    df.loc[mask, col] = new_values.values


def add_flag(table, df, col, mask, meaning):
    df[col] = np.where(mask.fillna(False).astype(bool), "1", "0")
    FLAGS.append(dict(table=table, column=col, meaning=meaning, rows_flagged=int((df[col] == "1").sum())))


def quarantine(table, df, mask, suffix, reason, extra: dict | None = None):
    """Move rows to a quarantine set (never dropped silently). Returns the kept frame."""
    q = df[mask].copy()
    for k, v in (extra or {}).items():
        q[k] = v
    q["source_table"] = table
    q["quarantine_reason"] = reason
    QUARANTINE[suffix] = q
    QUARANTINED_ROWS[table] += len(q)
    return df[~mask].copy()


def fmt_decimal(x: float) -> str:
    s = f"{x:.6f}".rstrip("0")
    return s + "0" if s.endswith(".") else s


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------
def find_raw(name: str) -> Path:
    exact = RAW_DIR / f"{name}.csv"
    if exact.exists():
        return exact
    matches = sorted(RAW_DIR.glob(f"{name} (*).csv"))
    assert len(matches) == 1, f"expected one raw file for {name}, found {matches}"
    return matches[0]


def load():
    paths = {t: find_raw(t) for t in TABLES}
    hashes = {t: sha256(p) for t, p in paths.items()}
    raw = {t: pd.read_csv(p, dtype=str, keep_default_na=False, encoding="utf-8-sig")
           for t, p in paths.items()}
    print("Raw files (read as text):")
    for t in TABLES:
        print(f"    {paths[t].name:<32}{len(raw[t]):>9,} rows  {len(raw[t].columns):>3} cols")
        if paths[t].name != f"{t}.csv":
            log(t, f"raw file is named '{paths[t].name}'", "leave as is", 0,
                f"raw file untouched; clean output saved as {t}.csv (decision #29)")
    return paths, hashes, raw


# ---------------------------------------------------------------------------
# dim_client
# ---------------------------------------------------------------------------
def clean_dim_client(T, raw):
    c = T["dim_client"]
    fact_clients = set(raw["fact_fees"].client_id) | set(raw["fact_portfolio_snapshot"].client_id) | \
        set(raw["fact_transactions"].client_id)

    # ---- C1 duplicate clients (decision #6) -------------------------------
    header("C1", "dim_client", "same client recorded twice (last_name off by one letter)", "quarantine")
    others = [x for x in c.columns if x not in ("client_id", "last_name")]
    dup = c.duplicated(others, keep=False)
    groups = [g for _, g in c[dup].groupby(others, sort=False)]
    show("before:", f"{len(c):,} rows; {len(groups)} groups identical except client_id/last_name")
    copy_ids, original_of, kinds = [], {}, {"dropped": 0, "added": 0}
    for g in groups:
        assert len(g) == 2, f"expected pairs, got group of {len(g)}: {g.client_id.tolist()}"
        used = g.client_id.isin(fact_clients)
        # reconcile 1: the fact tables use exactly one row of the pair - that one is the original
        assert used.sum() == 1, f"fact usage does not identify the copy for {g.client_id.tolist()}"
        orig, copy = g[used].iloc[0], g[~used].iloc[0]
        # reconcile 2: the two last names differ only by one letter at the end
        if orig.last_name[:-1] == copy.last_name:
            kinds["dropped"] += 1
        elif copy.last_name[:-1] == orig.last_name:
            kinds["added"] += 1
        else:
            raise AssertionError(f"last names differ by more than a final letter: {orig.last_name}/{copy.last_name}")
        copy_ids.append(copy.client_id)
        original_of[copy.client_id] = orig.client_id
    mask = c.client_id.isin(copy_ids)
    c = quarantine("dim_client", c, mask, "dim_client_duplicates",
                   "duplicate of another client_id (last_name differs by one final letter); never used by any fact",
                   extra={"duplicate_of_client_id": c.loc[mask, "client_id"].map(original_of)})
    n = int(mask.sum())
    show("rows affected:", n)
    show("after:", f"{len(c):,} rows; duplicate groups left: {int(c.duplicated(others).sum())}; "
                   f"copies referenced by facts: {len(set(copy_ids) & fact_clients)}")
    assert n == len(groups) and not c.duplicated(others).any()
    assert not set(copy_ids) & fact_clients
    show("evidence:", f"copy's last_name missing final letter: {kinds['dropped']}; extra final letter: "
                      f"{kinds['added']}; original used by facts in every pair")
    log("dim_client", "same client recorded twice; last_name differs by one final letter",
        "quarantine", n, f"copies {min(copy_ids, key=int)}-{max(copy_ids, key=int)} "
                         f"({kinds['dropped']} missing a letter, {kinds['added']} with an extra letter); "
                         f"the original is the only row any fact table uses")
    passed()

    # ---- C2 state names -> USPS codes (decision #7) -----------------------
    header("C2", "dim_client", "full state names mixed with 2-letter codes", "standardize")
    m = c.state.str.len() > 2
    codes_in_use = set(c.state[~m])
    show("before:", f"{int(m.sum())} full names: " + ", ".join(f"{k} x{v}" for k, v in c.state[m].value_counts().items()))
    new = c.state[m].map(US_STATES)
    assert new.notna().all(), f"unmapped state names: {sorted(set(c.state[m][new.isna()]))}"
    # reconcile: every mapped code is already a code used elsewhere in the column
    assert set(new) <= codes_in_use, f"mapping introduces new codes: {set(new) - codes_in_use}"
    change("dim_client", c, m, "state", new)
    show("rows affected:", int(m.sum()))
    show("after:", f"values not 2 upper-case letters: {int((~c.state.str.fullmatch(r'[A-Z]{2}')).sum())}; "
                   f"distinct states {c.state.nunique()}")
    assert c.state.str.fullmatch(r"[A-Z]{2}").all()
    log("dim_client", "state written as full name", "standardize", int(m.sum()),
        "mapped to USPS codes; every code already existed in the column")
    passed()

    # ---- C3 blank risk_profile (decision #8) -------------------------------
    header("C3", "dim_client", "blank risk_profile", "fill (+ flag risk_profile_imputed)")
    snap = raw["fact_portfolio_snapshot"]
    bench_per_client = snap.groupby("client_id").benchmark_id.agg(lambda s: set(s))
    assert (bench_per_client.map(len) == 1).all(), "a client changes benchmark - mapping not fixed"
    bench = bench_per_client.map(lambda s: next(iter(s)))
    blank = c.risk_profile.str.strip() == ""
    show("before:", f"{int(blank.sum())} blank risk_profile")
    known = c[~blank].assign(b=c.client_id.map(bench)).dropna(subset=["b"])
    profiles_per_bench = known.groupby("b").risk_profile.agg(lambda s: sorted(set(s)))
    show("evidence:", "; ".join(f"benchmark {b} -> {v}" for b, v in profiles_per_bench.items()))
    fill = c.loc[blank, "client_id"].map(bench).map(
        lambda b: profiles_per_bench[b][0] if b in profiles_per_bench.index and len(profiles_per_bench[b]) == 1 else None)
    assert fill.notna().all(), f"risk_profile not inferable for {c.loc[blank & fill.reindex(c.index).isna(), 'client_id'].tolist()}"
    change("dim_client", c, blank, "risk_profile", fill)
    add_flag("dim_client", c, "risk_profile_imputed", blank,
             "risk_profile was blank and was filled from the client's benchmark (only one profile uses that benchmark)")
    # reconcile after: each benchmark still maps to the same profile(s) as before
    after_map = c.assign(b=c.client_id.map(bench)).dropna(subset=["b"]).groupby("b").risk_profile.agg(lambda s: sorted(set(s)))
    show("rows affected:", int(blank.sum()))
    show("after:", f"blank risk_profile: {int((c.risk_profile.str.strip() == '').sum())}; filled values: "
                   + ", ".join(f"{k} x{v}" for k, v in fill.value_counts().items()))
    assert (c.risk_profile.str.strip() != "").all()
    assert after_map.to_dict() == profiles_per_bench.to_dict(), "fill changed the benchmark -> profile mapping"
    log("dim_client", "blank risk_profile", "fill", int(blank.sum()),
        "filled from fact_portfolio_snapshot.benchmark_id; " +
        "; ".join(f"benchmark {b} used only by {v[0]}" for b, v in profiles_per_bench.items() if len(v) == 1)
        + "; flagged risk_profile_imputed=1")
    passed()
    T["dim_client"] = c


# ---------------------------------------------------------------------------
# dim_security
# ---------------------------------------------------------------------------
def clean_dim_security(T):
    s = T["dim_security"]
    header("S1", "dim_security", "expense_ratio_bps stored as float text ('17.0')", "convert")
    m = s.expense_ratio_bps.str.fullmatch(r"\d+\.0+")
    show("before:", f"{int(m.sum())} values like '17.0'; blanks {int((s.expense_ratio_bps == '').sum())}")
    new = s.expense_ratio_bps[m].str.replace(r"\.0+$", "", regex=True)
    assert (num(s.expense_ratio_bps[m]) == num(new)).all(), "conversion would change a value"
    change("dim_security", s, m, "expense_ratio_bps", new)
    filled = s.expense_ratio_bps != ""
    show("rows affected:", int(m.sum()))
    non_int = int((filled & ~s.expense_ratio_bps.str.fullmatch(r"\d+")).sum())
    blank_is_stock = bool((~filled == (s.is_etf == "False")).all())
    show("after:", f"non-integer values: {non_int}; blank only for non-ETFs: {blank_is_stock}")
    assert s.expense_ratio_bps[filled].str.fullmatch(r"\d+").all()
    assert (~filled == (s.is_etf == "False")).all(), "blank expense ratio is not exactly the non-ETFs"
    log("dim_security", "expense_ratio_bps stored as float text", "convert", int(m.sum()),
        "'17.0' -> '17'; numeric value unchanged; blanks (individual stocks) left as is")
    passed()


# ---------------------------------------------------------------------------
# fact_transactions
# ---------------------------------------------------------------------------
def clean_fact_transactions(T, raw):
    t = T["fact_transactions"]
    clients = set(T["dim_client"].client_id)
    copies = set(QUARANTINE["dim_client_duplicates"].client_id)

    # ---- T1 orphan client_id (decision #3) ---------------------------------
    header("T1", "fact_transactions", "client_id not in dim_client", "quarantine")
    m = ~t.client_id.isin(clients)
    show("before:", f"{len(t):,} rows; {int(m.sum())} rows / {t.client_id[m].nunique()} client_ids unmatched")
    # reconcile: orphans are not the quarantined duplicate copies, and no other fact table knows them
    assert not set(t.client_id[m]) & copies
    other = set(raw["fact_fees"].client_id) | set(raw["fact_portfolio_snapshot"].client_id)
    assert not set(t.client_id[m]) & other, "orphan client appears in another fact table"
    n = int(m.sum())
    ids = t.client_id[m].astype(int)
    t = quarantine("fact_transactions", t, m, "fact_transactions_orphan_clients",
                   "client_id not found in dim_client (and not in fact_fees or fact_portfolio_snapshot)")
    show("rows affected:", n)
    show("after:", f"{len(t):,} rows; unmatched client_id: {int((~t.client_id.isin(clients)).sum())}")
    assert t.client_id.isin(clients).all()
    log("fact_transactions", "client_id not in dim_client", "quarantine", n,
        f"{n} client_ids {ids.min()}-{ids.max()}, one row each; none appear in other fact tables")
    passed()

    # ---- T2 security_id float text (decision #4) ---------------------------
    header("T2", "fact_transactions", "security_id stored as float text ('45.0')", "convert")
    sec_ids = set(T["dim_security"].security_id)
    filled = t.security_id != ""
    m = filled & t.security_id.str.fullmatch(r"\d+\.0+")
    show("before:", f"{int(m.sum()):,} of {int(filled.sum()):,} ids like '45.0'; raw text join matches "
                    f"{int(t.security_id[filled].isin(sec_ids).sum()):,}")
    new = t.security_id[m].str.replace(r"\.0+$", "", regex=True)
    assert (num(t.security_id[m]) == num(new)).all()
    change("fact_transactions", t, m, "security_id", new)
    show("rows affected:", int(m.sum()))
    show("after:", f"text join to dim_security matches {int(t.security_id[filled].isin(sec_ids).sum()):,} "
                   f"of {int(filled.sum()):,}")
    assert t.security_id[filled].str.fullmatch(r"\d+").all() and t.security_id[filled].isin(sec_ids).all()
    log("fact_transactions", "security_id stored as float text", "convert", int(m.sum()),
        "'45.0' -> '45'; text join to dim_security now matches 100% (was 0%)")
    passed()

    # ---- T3 negative shares on Buy (decision #2) ---------------------------
    header("T3", "fact_transactions", "negative shares on Buy rows", "convert (+ flag shares_sign_corrected)")
    sh, pr, am = num(t.shares), num(t.price), num(t.amount)
    m = (t.txn_type == "Buy") & (sh < 0)
    ok_signed = (am - sh * pr).abs() <= MONEY_TOL
    ok_abs = (am - sh.abs() * pr).abs() <= MONEY_TOL
    show("before:", f"{int(m.sum())} Buy rows with shares < 0; amount = shares x price on "
                    f"{int(ok_signed[m].sum())}; amount = |shares| x price on {int(ok_abs[m].sum())}")
    # reconcile BEFORE fixing: the amount proves the sign is the only error
    assert ok_abs[m].all(), "abs(shares) does not reconcile to amount - sign flip would be a guess"
    change("fact_transactions", t, m, "shares", t.shares[m].str.lstrip("-"))
    add_flag("fact_transactions", t, "shares_sign_corrected", m,
             "shares was negative on a Buy; sign removed because amount = abs(shares) x price")
    sh = num(t.shares)
    trade = t.txn_type.isin(["Buy", "Sell"])
    recon = ((am - sh * pr).abs() <= MONEY_TOL)[trade]
    show("rows affected:", int(m.sum()))
    show("after:", f"negative shares: {int((sh < 0).sum())}; Buy/Sell rows with amount = shares x price: "
                   f"{int(recon.sum()):,} of {int(trade.sum()):,}")
    assert not (sh < 0).any() and recon.all()
    log("fact_transactions", "negative shares on Buy rows", "convert", int(m.sum()),
        "abs(shares); confirmed by amount = |shares| x price on every row; flagged shares_sign_corrected=1")
    passed()

    # ---- T4 dividends equal the full position value (decision #12) ---------
    header("T4", "fact_transactions", "dividend amount equals shares x price (full position value)",
           "flag dividend_is_position_value")
    div = t.txn_type == "Dividend"
    eq = ((am - sh * pr).abs() <= MONEY_TOL) & div
    show("before:", f"{int(div.sum()):,} Dividend rows; amount = shares x price on {int(eq.sum()):,}; "
                    f"median dividend {am[div].median():,.2f}")
    add_flag("fact_transactions", t, "dividend_is_position_value", eq,
             "Dividend amount equals the whole position's market value, not a cash payout; exclude from income totals")
    show("rows affected:", int(eq.sum()))
    show("after:", f"flagged {int((t.dividend_is_position_value == '1').sum()):,}; flagged non-dividend rows: "
                   f"{int(((t.dividend_is_position_value == '1') & ~div).sum())}")
    assert ((t.dividend_is_position_value == "1") == eq).all() and not ((t.dividend_is_position_value == "1") & ~div).any()
    log("fact_transactions", "dividend amount equals full position value", "flag", int(eq.sum()),
        "true payout cannot be derived (no yield data); amount left unchanged")
    passed()

    # ---- T5 activity after account close (decision #13) --------------------
    header("T5", "fact_transactions", "transaction after the client's last snapshot", "flag txn_after_account_close")
    snap = T["fact_portfolio_snapshot"]
    last = snap.groupby("client_id").snapshot_date.max().str[:7]
    tm = t.txn_date.str[:7]
    m = tm > t.client_id.map(last)
    active = T["dim_client"].set_index("client_id").is_active
    show("before:", f"{int(m.sum()):,} rows from {t.client_id[m].nunique()} clients dated after their last snapshot month")
    # reconcile: every one of these clients is marked inactive in dim_client
    assert (t.client_id[m].map(active) == "False").all(), "an ACTIVE client has post-snapshot activity"
    add_flag("fact_transactions", t, "txn_after_account_close", m,
             "dated after the client's last monthly snapshot; client is_active=False")
    show("rows affected:", int(m.sum()))
    show("after:", f"flagged {int((t.txn_after_account_close == '1').sum()):,}; all for is_active=False clients")
    assert int((t.txn_after_account_close == "1").sum()) == int(m.sum())
    log("fact_transactions", "activity after the account's last snapshot", "flag", int(m.sum()),
        f"{t.client_id[m].nunique()} clients, all is_active=False in dim_client")
    passed()

    # ---- T6 weekend / non-trading dates (decision #14) ---------------------
    header("T6", "fact_transactions", "transaction dated on a non-trading day", "flag on_non_trading_day")
    cal = T["dim_date"].set_index("date")
    assert t.txn_date.isin(cal.index).all(), "txn_date missing from dim_date"
    m = t.txn_date.map(cal.is_trading_day) == "0"
    dow = pd.to_datetime(t.txn_date[m]).dt.dayofweek
    show("before:", f"{int(m.sum()):,} rows ({m.mean():.1%}) on days with is_trading_day=0")
    assert (dow >= 5).all(), "a non-trading day is not a weekend - calendar assumption broken"
    add_flag("fact_transactions", t, "on_non_trading_day", m,
             "txn_date falls on a day dim_date marks as non-trading (all are Saturdays/Sundays)")
    show("rows affected:", int(m.sum()))
    show("after:", f"flagged {int((t.on_non_trading_day == '1').sum()):,}; all Saturday/Sunday")
    assert int((t.on_non_trading_day == "1").sum()) == int(m.sum())
    log("fact_transactions", "transaction dated on a weekend", "flag", int(m.sum()),
        "correct date unknown, so dates are not moved")
    passed()

    # ---- T7 advisory-fee transactions vs fact_fees (decision #16) ----------
    header("T7", "fact_transactions", "Advisory Fee transactions disagree with fact_fees",
           "flag advisory_fee_unreconciled")
    fees = T["fact_fees"]
    af = t.txn_type == "Advisory Fee"
    k_t = t.client_id + "|" + t.txn_date.str[:4]
    k_f = fees.client_id + "|" + fees.fee_date.str[:4]
    tot_t = am[af].groupby(k_t[af]).sum()
    tot_f = num(fees.amount).groupby(k_f).sum()
    j = pd.concat([tot_t.rename("txn"), tot_f.rename("fees")], axis=1).fillna(0)
    agree = np.isclose(j.txn, j.fees, rtol=0.01)
    good_keys = set(j.index[agree])
    m = af & ~k_t.isin(good_keys)
    yearly = pd.concat([am[af].groupby(t.txn_date.str[:4][af]).sum(),
                        num(fees.amount).groupby(fees.fee_date.str[:4]).sum()], axis=1)
    show("before:", f"{int(af.sum()):,} Advisory Fee rows; client-years agreeing within 1%: "
                    f"{int(agree.sum())} of {len(j):,}")
    show("by year:", "; ".join(f"{y}: {a:,.0f} vs {b:,.0f}" for y, (a, b) in yearly.iterrows()))
    add_flag("fact_transactions", t, "advisory_fee_unreconciled", m,
             "Advisory Fee row whose client-year total does not match fact_fees within 1%; use fact_fees for fee revenue")
    show("rows affected:", int(m.sum()))
    show("after:", f"flagged {int((t.advisory_fee_unreconciled == '1').sum()):,}; flagged non-fee rows: "
                   f"{int(((t.advisory_fee_unreconciled == '1') & ~af).sum())}")
    assert not ((t.advisory_fee_unreconciled == "1") & ~af).any()
    log("fact_transactions", "Advisory Fee transactions disagree with fact_fees", "flag", int(m.sum()),
        f"client-year totals agree within 1% for only {int(agree.sum())} of {len(j)}; fact_fees is the source of truth")
    passed()
    T["fact_transactions"] = t


# ---------------------------------------------------------------------------
# fact_portfolio_snapshot
# ---------------------------------------------------------------------------
def clean_fact_portfolio_snapshot(T):
    s = T["fact_portfolio_snapshot"]
    b, a = num(s.benchmark_return_ytd), num(s.active_alpha_ytd)

    # ---- P1 percent strings (decision #1) ---------------------------------
    header("P1", "fact_portfolio_snapshot", "return_ytd written as percent text ('9.28%')", "convert")
    m = s.return_ytd.str.contains("%", regex=False)
    pct = num(s.return_ytd[m].str.replace("%", "", regex=False))
    show("before:", f"{int(m.sum())} values with '%'; unparseable as numbers: {int(num(s.return_ytd).isna().sum())}")
    # reconcile BEFORE fixing: return = benchmark + alpha only holds after dividing by 100
    fits_div = ((pct / 100) - (b[m] + a[m])).abs() <= RATE_TOL
    fits_raw = (pct - (b[m] + a[m])).abs() <= RATE_TOL
    show("evidence:", f"return = benchmark + alpha holds on {int(fits_div.sum())}/{int(m.sum())} after /100 "
                      f"and on {int(fits_raw.sum())} as written")
    assert fits_div.all(), "dividing by 100 does not reconcile - conversion would be a guess"
    change("fact_portfolio_snapshot", s, m, "return_ytd", (pct / 100).map(fmt_decimal))
    r = num(s.return_ytd)
    show("rows affected:", int(m.sum()))
    show("after:", f"'%' values: {int(s.return_ytd.str.contains('%', regex=False).sum())}; unparseable: "
                   f"{int(r.isna().sum())}; return = benchmark + alpha on "
                   f"{int(((r - (a + b)).abs() <= RATE_TOL).sum()):,} of {len(s):,}")
    assert r.notna().all() and ((r - (a + b)).abs() <= RATE_TOL).all()
    log("fact_portfolio_snapshot", "return_ytd written as percent text", "convert", int(m.sum()),
        "'9.28%' -> 0.0928; confirmed by return = benchmark + alpha on every converted row")
    passed()

    # ---- P2 flow-distorted returns (decision #9) ---------------------------
    header("P2", "fact_portfolio_snapshot", "extreme return_ytd caused by deposits/withdrawals",
           "flag return_flow_distorted")
    aum = num(s.aum)
    m = (r < RETURN_FLAG_LOW) | (r > RETURN_FLAG_HIGH)
    dec = s[s.month == "12"].set_index(["client_id", "year"]).aum.map(float)
    base = pd.Series([dec.get((cid, str(int(y) - 1)), np.nan) for cid, y in zip(s.client_id, s.year)], index=s.index)
    est = aum / base - 1
    has_base = base.notna()
    match = (est - r).abs() <= 1e-4 + 1e-4 * r.abs()
    show("before:", f"{int((r < RETURN_FLAG_LOW).sum())} below {RETURN_FLAG_LOW:+.0%}, "
                    f"{int((r > RETURN_FLAG_HIGH).sum())} above {RETURN_FLAG_HIGH:+.0%}")
    show("evidence:", f"return_ytd = aum / prior-December aum - 1 on {int(match[has_base].sum()):,} of "
                      f"{int(has_base.sum()):,} rows with a prior December (flagged rows: "
                      f"{int(match[m & has_base].sum())} of {int((m & has_base).sum())})")
    assert match[m & has_base].all(), "a flagged return is NOT explained by the AUM change"
    add_flag("fact_portfolio_snapshot", s, "return_flow_distorted", m,
             f"return_ytd < {RETURN_FLAG_LOW} or > {RETURN_FLAG_HIGH}; the field is AUM change incl. deposits/"
             "withdrawals, so these values are not investment performance (also distorts active_alpha_ytd)")
    show("rows affected:", int(m.sum()))
    show("after:", f"flagged {int((s.return_flow_distorted == '1').sum()):,}")
    assert int((s.return_flow_distorted == "1").sum()) == int(m.sum())
    log("fact_portfolio_snapshot", "extreme return_ytd driven by cash flows", "flag", int(m.sum()),
        "return_ytd = aum / prior-Dec aum - 1 on 100% of rows with a base; true time-weighted return cannot be rebuilt")
    passed()

    # ---- P3 $1,000 AUM floor (decision #10) --------------------------------
    header("P3", "fact_portfolio_snapshot", f"aum at the ${AUM_FLOOR:,.0f} floor", "flag aum_at_floor")
    m = aum == AUM_FLOOR
    first = s.snapshot_date == s.groupby("client_id").snapshot_date.transform("min")
    show("before:", f"{int(m.sum())} rows ({s.client_id[m].nunique()} clients) with aum = {AUM_FLOOR:,.2f}; "
                    f"of these a client's first month: {int((m & first).sum())}")
    assert not (m & first).any(), "a floor value is a first month - it may be a placeholder, not a floor"
    add_flag("fact_portfolio_snapshot", s, "aum_at_floor", m,
             f"aum equals the ${AUM_FLOOR:,.0f} minimum-balance floor; true balance unknown")
    show("rows affected:", int(m.sum()))
    show("after:", f"flagged {int((s.aum_at_floor == '1').sum())}")
    assert int((s.aum_at_floor == "1").sum()) == int(m.sum())
    log("fact_portfolio_snapshot", f"aum at ${AUM_FLOOR:,.0f} floor", "flag", int(m.sum()),
        "never a client's first month and later balances build on it -> floor, not missing data")
    passed()

    # ---- P4 snapshot months with no fee (decision #15) ---------------------
    header("P4", "fact_portfolio_snapshot", "snapshot month with no fee charged", "flag fee_missing")
    fees = T["fact_fees"]
    k_s = s.client_id + "|" + s.snapshot_date.str[:7]
    k_f = fees.client_id + "|" + fees.fee_date.str[:7]
    m = ~k_s.isin(set(k_f))
    show("before:", f"{int(m.sum()):,} snapshot months without a fee row; fee rows without a snapshot: "
                    f"{int((~k_f.isin(set(k_s))).sum())}")
    # reconcile: fees are one per client-month and a subset of snapshots
    assert not k_f.duplicated().any() and k_f.isin(set(k_s)).all()
    assert int(m.sum()) == len(s) - len(fees)
    add_flag("fact_portfolio_snapshot", s, "fee_missing", m,
             "no fact_fees row for this client and month (waiver or billing gap - fee rate unknown)")
    show("rows affected:", int(m.sum()))
    show("after:", f"flagged {int((s.fee_missing == '1').sum()):,} = snapshots {len(s):,} - fees {len(fees):,}")
    assert int((s.fee_missing == "1").sum()) == len(s) - len(fees)
    log("fact_portfolio_snapshot", "snapshot month with no fee row", "flag", int(m.sum()),
        "fee cannot be rebuilt because bps varies; flagged only")
    passed()
    T["fact_portfolio_snapshot"] = s


# ---------------------------------------------------------------------------
# fact_fees
# ---------------------------------------------------------------------------
def clean_fact_fees(T):
    f = T["fact_fees"]
    s = T["fact_portfolio_snapshot"]
    basis, bps, amt = num(f.aum_basis), num(f.bps_charged), num(f.amount)

    header("F0", "fact_fees", "reconciliation checks (no change)", "verify")
    formula = (amt - basis * bps / 120000).abs() <= MONEY_TOL
    snap_aum = (s.client_id + "|" + s.snapshot_date.str[:7])
    snap_aum = pd.Series(num(s.aum).values, index=snap_aum.values)
    fee_key = f.client_id + "|" + f.fee_date.str[:7]
    same = np.isclose(basis.values, fee_key.map(snap_aum).values, atol=0.005)
    show("checks:", f"amount = aum_basis x bps / 120000 on {int(formula.sum()):,}/{len(f):,}; "
                    f"aum_basis = snapshot aum on {int(same.sum()):,}/{len(f):,}")
    assert formula.all() and same.all()
    log("fact_fees", "fee formula and aum_basis vs snapshot aum", "verify", 0,
        "both hold on 100% of rows - no change needed")
    passed()

    header("F1", "fact_fees", f"fee charged on the ${AUM_FLOOR:,.0f} floor balance", "flag fee_on_floor_aum")
    m = basis == AUM_FLOOR
    floor_keys = set((s.client_id + "|" + s.snapshot_date.str[:7])[s.aum_at_floor == "1"])
    show("before:", f"{int(m.sum())} fees on aum_basis {AUM_FLOOR:,.2f} (amounts "
                    f"{amt[m].min():.2f}-{amt[m].max():.2f}); matching floor snapshots: "
                    f"{int(fee_key[m].isin(floor_keys).sum())}")
    assert fee_key[m].isin(floor_keys).all(), "a floor fee has no floor snapshot"
    add_flag("fact_fees", f, "fee_on_floor_aum", m,
             f"fee was charged on the ${AUM_FLOOR:,.0f} floor balance (see snapshot aum_at_floor)")
    show("rows affected:", int(m.sum()))
    show("after:", f"flagged {int((f.fee_on_floor_aum == '1').sum())}")
    assert int((f.fee_on_floor_aum == "1").sum()) == int(m.sum())
    log("fact_fees", f"fee charged on ${AUM_FLOOR:,.0f} floor", "flag", int(m.sum()),
        f"every one matches a snapshot flagged aum_at_floor; total {amt[m].sum():,.2f}")
    passed()


# ---------------------------------------------------------------------------
# tables with no changes + leave-as-is decisions
# ---------------------------------------------------------------------------
def untouched(T, raw):
    header("U1", "dim_advisor, dim_benchmark, dim_date", "no defects requiring change", "leave as is")
    for name in ("dim_advisor", "dim_benchmark", "dim_date"):
        assert T[name].equals(raw[name]), f"{name} changed unexpectedly"
    none_count = int((T["dim_advisor"].certifications == "None").sum())
    show("checks:", f"tables identical to raw; certifications 'None' kept as text: {none_count}")
    assert none_count == int((raw["dim_advisor"].certifications == "None").sum())
    passed()
    for table, issue, note in [
        ("dim_advisor", "certifications = 'None'", "real value meaning no certification; kept as text (decision #26)"),
        ("dim_date", "is_trading_day ignores market holidays", "no holiday calendar in the data (decision #27)"),
        ("dim_benchmark", "benchmark 6 never used", "reference row kept (decision #28)"),
        ("fact_transactions", "blank security_id/shares/price on cash and fee rows", "legitimate structure (decision #17)"),
        ("fact_portfolio_snapshot", "return_ytd in scientific notation", "valid number format (decision #18)"),
        ("fact_portfolio_snapshot", "return_ytd = 0.0", "correct: AUM 1000 -> 1000 (decision #19)"),
        ("dim_client", "zip_code leading zeros", "kept as text (decision #20)"),
        ("dim_client", "initial_aum outliers", "normal for UHNW tier (decision #21)"),
        ("dim_client", "fact dated in the month before client_since day", "monthly stamps on the 1st (decision #22)"),
        ("dim_security", "blank expense_ratio_bps / sector", "stocks have no expense ratio, funds no sector (decision #23)"),
        ("dim_security", "repeated security names", "different tickers; ticker is the identifier (decision #24)"),
        ("dim_security", "asset_class differs from benchmark asset_class", "consistent mapping (decision #25)"),
    ]:
        log(table, issue, "leave as is", 0, note)


# ---------------------------------------------------------------------------
# final validation
# ---------------------------------------------------------------------------
def validate(T, raw, paths, hashes):
    print("\n[V] final validation")
    rows = []
    for t in TABLES:
        r, c, q = len(raw[t]), len(T[t]), QUARANTINED_ROWS[t]
        ok = r == c + q
        rows.append((t, r, c, q))
        print(f"    {t:<26} raw {r:>8,} = clean {c:>8,} + quarantined {q:>4,}  {'OK' if ok else 'FAIL'}")
        assert ok, f"row reconciliation failed for {t}"
        log(t, "row reconciliation", "verify", 0, f"raw {r} = clean {c} + quarantined {q}")
        # same columns, in the same order, then flags
        assert list(T[t].columns[:len(raw[t].columns)]) == list(raw[t].columns), f"{t}: columns changed"
        extra = list(T[t].columns[len(raw[t].columns):])
        assert all(re.fullmatch(r"[a-z_]+", x) and set(T[t][x]) <= {"0", "1"} for x in extra), f"{t}: bad flag column"
        pk = T[t].columns[0]
        assert T[t][pk].is_unique and (T[t][pk] != "").all(), f"{t}: primary key not unique"

    fk = [("dim_client", "advisor_id", "dim_advisor"), ("dim_security", "benchmark_id", "dim_benchmark"),
          ("fact_fees", "client_id", "dim_client"), ("fact_fees", "advisor_id", "dim_advisor"),
          ("fact_portfolio_snapshot", "client_id", "dim_client"),
          ("fact_portfolio_snapshot", "advisor_id", "dim_advisor"),
          ("fact_portfolio_snapshot", "benchmark_id", "dim_benchmark"),
          ("fact_transactions", "client_id", "dim_client"), ("fact_transactions", "advisor_id", "dim_advisor"),
          ("fact_transactions", "security_id", "dim_security")]
    for t, col, d in fk:
        vals = T[t][col][T[t][col] != ""]
        miss = int((~vals.isin(set(T[d][col]))).sum())
        assert miss == 0, f"{t}.{col}: {miss} values do not join (as text) to {d}"
    for t, col in [("fact_fees", "fee_date"), ("fact_portfolio_snapshot", "snapshot_date"),
                   ("fact_transactions", "txn_date")]:
        assert T[t][col].isin(set(T["dim_date"].date)).all(), f"{t}.{col} not in dim_date"
    print("    all foreign keys and dates join as TEXT to their dimension: OK")
    log("all", "foreign keys after cleaning", "verify", 0, "every FK and fact date joins as text to its dimension")

    for t, p in paths.items():
        assert sha256(p) == hashes[t], f"RAW FILE CHANGED: {p.name}"
    print("    raw files unchanged (SHA-256 identical before and after): OK")
    log("all", "raw files unchanged", "verify", 0, "SHA-256 of all 8 raw files identical before and after")
    return rows


# ---------------------------------------------------------------------------
# outputs
# ---------------------------------------------------------------------------
BI_TYPES = {
    "dim_advisor": {"advisor_id": "Whole number (key)", "years_experience": "Whole number",
                    "aum_target_mm": "Whole number ($ millions)",
                    "certifications": "Text - turn OFF 'None'/blank-as-null conversion"},
    "dim_benchmark": {"benchmark_id": "Whole number (key)"},
    "dim_client": {"client_id": "Whole number (key)", "age": "Whole number",
                   "zip_code": "TEXT - never number (leading zeros)", "initial_aum": "Decimal (currency)",
                   "client_since": "Date (YYYY-MM-DD)", "advisor_id": "Whole number (key)",
                   "is_active": "True/False", "risk_profile_imputed": "Whole number 0/1"},
    "dim_date": {"date_id": "Whole number", "date": "Date (YYYY-MM-DD) - join key for fact dates",
                 "year/quarter/month/week_of_year": "Whole number",
                 "is_month_end/is_quarter_end/is_year_end/is_trading_day": "Whole number 0/1"},
    "dim_security": {"security_id": "Whole number (key)", "benchmark_id": "Whole number (key)",
                     "is_etf": "True/False", "expense_ratio_bps": "Whole number (blank = not a fund)"},
    "fact_fees": {"fee_id": "Whole number (key)", "client_id/advisor_id": "Whole number (key)",
                  "fee_date": "Date (YYYY-MM-DD)", "aum_basis/amount": "Decimal (currency)",
                  "bps_charged": "Decimal", "fee_on_floor_aum": "Whole number 0/1"},
    "fact_portfolio_snapshot": {"snapshot_id": "Whole number (key)",
                                "client_id/advisor_id/benchmark_id": "Whole number (key)",
                                "snapshot_date": "Date (YYYY-MM-DD)", "year/month": "Whole number",
                                "aum": "Decimal (currency)",
                                "return_ytd/benchmark_return_ytd/active_alpha_ytd/cash_pct":
                                    "Decimal fraction (0.05 = 5%); a few use scientific notation (9.9e-05)",
                                "flag columns": "Whole number 0/1"},
    "fact_transactions": {"txn_id": "Whole number (key)", "client_id/advisor_id": "Whole number (key)",
                          "security_id": "Whole number (key; blank on cash/fee rows)",
                          "txn_date": "Date (YYYY-MM-DD)", "shares/price/amount": "Decimal (blank shares/price on cash/fee rows)",
                          "flag columns": "Whole number 0/1"},
}

LIMITATIONS = [
    ("return_ytd and active_alpha_ytd are AUM change, not investment performance",
     "return_ytd = aum / prior-December aum - 1, so deposits and withdrawals count as gains/losses. A time-weighted "
     "return cannot be rebuilt because transaction amounts do not reconcile to AUM. Extreme rows are flagged "
     "(return_flow_distorted); all rows are affected to some degree, so do not present this field as performance."),
    ("Dividend amounts are position values, not payouts",
     "Every Dividend amount equals shares x price. There is no yield data to derive the real payout, so amounts are "
     "unchanged and flagged (dividend_is_position_value). Exclude them from income or cash-flow totals."),
    ("Advisory Fee transactions do not match fact_fees",
     "Totals differ every year and per client-year they agree for about 1% of pairs. There is no way to tell which is "
     "right; fact_fees is treated as the source of truth for fee revenue and the transactions are flagged."),
    ("$1,000 AUM floor",
     "AUM sits at exactly $1,000 after large withdrawals and later balances build on it. The true balance is unknown, "
     "so values are flagged (aum_at_floor, fee_on_floor_aum), not filled."),
    ("Snapshot months without a fee",
     "About 5% of client-months have no fee row. The rate varies, so the missing fee cannot be rebuilt (fee_missing)."),
    ("Transactions on weekends",
     "About 28% of rows of every type fall on Saturday/Sunday. The real date is unknown, so dates are not moved "
     "(on_non_trading_day). Monthly reporting is unaffected."),
    ("Activity after an account closed",
     "Transactions continue after the last snapshot for inactive clients. They may be final liquidations, so they are "
     "kept and flagged (txn_after_account_close)."),
    ("Imputed risk profiles",
     "75 blank risk profiles were filled as Balanced because their benchmark is used only by Balanced clients. If the "
     "firm assigns that benchmark by default, these labels could be wrong; filter on risk_profile_imputed."),
    ("is_trading_day means 'weekday'",
     "Market holidays (e.g. Dec 25) are marked as trading days. There is no holiday calendar in the data to correct it."),
    ("Benchmark 6 (MSCI Emerging Markets) is unused",
     "Kept as reference data; no security or snapshot points to it."),
]


def write_outputs(T, recon_rows):
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    for t in TABLES:
        T[t].to_csv(CLEAN_DIR / f"{t}.csv", index=False)
    pd.DataFrame(LOG, columns=["table", "issue", "action", "rows_affected", "note"]) \
        .to_csv(AUDIT_DIR / "cleaning_log.csv", index=False)
    vc = pd.concat(CHANGES, ignore_index=True) if CHANGES else pd.DataFrame(
        columns=["table", "key_column", "key", "column", "old_value", "new_value"])
    vc.to_csv(AUDIT_DIR / "value_changes.csv", index=False)
    for suffix, q in QUARANTINE.items():
        q.to_csv(AUDIT_DIR / f"quarantine_{suffix}.csv", index=False)

    md = ["# Clean data — README", "",
          "Produced by `scripts/02_clean.py` from the raw files in `hw04/` (raw files are never modified). "
          "Decisions follow `decision_log.md`. Every change is listed in `data/audit/value_changes.csv` and every "
          "step in `data/audit/cleaning_log.csv`.", "",
          "## Row counts", "", "| Table | Raw | Clean | Quarantined |", "|---|---:|---:|---:|"]
    md += [f"| {t} | {r:,} | {c:,} | {q:,} |" for t, r, c, q in recon_rows]
    md += ["", "Quarantine files: " + ", ".join(f"`data/audit/quarantine_{s}.csv` ({len(q)} rows)"
                                                for s, q in QUARANTINE.items()), "",
           "## Relationships (star schema)", "",
           "| From (many) | To (one) | Key |", "|---|---|---|",
           "| fact_fees | dim_client | client_id |", "| fact_fees | dim_advisor | advisor_id |",
           "| fact_fees | dim_date | fee_date → date |",
           "| fact_portfolio_snapshot | dim_client | client_id |",
           "| fact_portfolio_snapshot | dim_advisor | advisor_id |",
           "| fact_portfolio_snapshot | dim_benchmark | benchmark_id |",
           "| fact_portfolio_snapshot | dim_date | snapshot_date → date |",
           "| fact_transactions | dim_client | client_id |", "| fact_transactions | dim_advisor | advisor_id |",
           "| fact_transactions | dim_security | security_id (blank on cash/fee rows) |",
           "| fact_transactions | dim_date | txn_date → date |",
           "| dim_client | dim_advisor | advisor_id (client's assigned advisor) |",
           "| dim_security | dim_benchmark | benchmark_id |", "",
           "Grain: fact_fees and fact_portfolio_snapshot = one row per client per month (dated the 1st); "
           "fact_transactions = one row per event. Join dates on `dim_date.date`, not `date_id`.", "",
           "## Column types for a BI tool", "",
           "Import every file as text first, then set these types. Columns not listed are text.", "",
           "| Table | Column(s) | Type |", "|---|---|---|"]
    for t, cols in BI_TYPES.items():
        md += [f"| {t} | {c} | {ty} |" for c, ty in cols.items()]
    md += ["", "## Flag columns added (0 = no, 1 = yes)", "",
           "| Table | Column | Rows = 1 | Meaning |", "|---|---|---:|---|"]
    md += [f"| {f['table']} | `{f['column']}` | {f['rows_flagged']:,} | {f['meaning']} |" for f in FLAGS]
    md += ["", "## Known limitations (not fixed, with reasons)", ""]
    md += [f"{i}. **{title}.** {why}" for i, (title, why) in enumerate(LIMITATIONS, 1)]
    md += [""]
    (CLEAN_DIR / "README_clean.md").write_text("\n".join(md), encoding="utf-8")

    print(f"\nWrote 8 clean tables + README_clean.md to {CLEAN_DIR}")
    print(f"Wrote cleaning_log.csv ({len(LOG)} rows), value_changes.csv ({len(vc):,} rows) and "
          f"{len(QUARANTINE)} quarantine file(s) to {AUDIT_DIR}")


# ---------------------------------------------------------------------------
def main():
    paths, hashes, raw = load()
    T = {t: df.copy() for t, df in raw.items()}       # work on copies only
    clean_dim_client(T, raw)
    clean_dim_security(T)
    clean_fact_portfolio_snapshot(T)                    # before fees/transactions: they read its flags
    clean_fact_fees(T)
    clean_fact_transactions(T, raw)
    untouched(T, raw)
    recon = validate(T, raw, paths, hashes)
    write_outputs(T, recon)
    print("\nAll steps passed.")


if __name__ == "__main__":
    main()
