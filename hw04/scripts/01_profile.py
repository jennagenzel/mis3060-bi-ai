#!/usr/bin/env python3
"""
scripts/01_profile.py
Generic raw-data profiler and data-quality checker for the CSV files in hw04.

Nothing in this script is written for a specific table. Column types, primary
keys, foreign keys, allowed values, ranges and business rules are all inferred
from the data: value shapes, common column-name conventions (``*_id``,
``*_pct``, ``year``, ``age`` ...) and the relationships between files. The same
code runs on any of the 8 tables, or on a new CSV dropped into the folder.

Rule followed throughout: every file is read as text
(dtype=str, keep_default_na=False) and each column is converted on purpose.

Usage (from the hw04 folder, venv active):
    python scripts/01_profile.py                        # every CSV in hw04
    python scripts/01_profile.py dim_client fact_fees   # only these tables
        (all CSVs are still loaded so FK and cross-table checks can run)

Outputs (in hw04/reports/):
    profile_raw.csv      one row per table x column
    dq_summary_raw.csv   one row per finding, tagged ERROR / WARN / INFO

Revision 2 (after independent verification of the v1 findings):
  - new: rate column that is just the % change of a balance (returns incl. flows)
  - new: income rows (dividend/interest...) that equal the full position value
  - new: same money recorded in two fact tables with different totals
  - new: dimension blanks that can be inferred from a fact attribute
  - new: events after an entity's periodic history, tied to dimension flags
  - new: near-duplicate rows explained by truncation / never-referenced copies
  - fixed: 0 no longer reported as a placeholder; repeated round values are
    classed as "minimum floor" vs "placeholder"
  - fixed: monthly period stamps no longer compared to the trading calendar;
    event dates that ignore the calendar are WARN, with a per-category breakdown
  - fixed: event-vs-history reported once (against the main periodic table)
  - fixed: rare-value check no longer double-reports format minorities;
    mixed-format detail lists the offending values
  - fixed: orphan key range sorted numerically; dead code removed
  - fixed: float-text keys are ERROR only where they break a join (group 3)
  - fixed: implausible rates use a robust z-score instead of guessed ranges;
    outliers are judged within category segments when that explains them
  - faster: single-table runs only do cross-table work involving that table
"""
from __future__ import annotations

import argparse
import difflib
import itertools
import re
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE_DIR / "reports"

# --------------------------------------------------------------------------
# Value-level helpers
# --------------------------------------------------------------------------
NULL_TOKENS = {"none", "null", "nan", "n/a", "na", "nil", "missing", "-", "--",
               "?", "#n/a", "(null)", "undefined"}
BOOL_MAP = {"true": 1, "false": 0, "yes": 1, "no": 0, "y": 1, "n": 0,
            "t": 1, "f": 0, "1": 1, "0": 0}

FORMATS = [(n, re.compile(rx)) for n, rx in [
    ("int",           r"[+-]?\d+"),
    ("int_as_float",  r"[+-]?\d+\.0+"),
    ("decimal",       r"[+-]?(?:\d+\.\d*|\.\d+)"),
    ("scientific",    r"[+-]?\d+(?:\.\d+)?[eE][+-]?\d+"),
    ("thousands_sep", r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"),
    ("currency",      r"[+-]?\$\s?[\d,]*\.?\d+|\(\$?[\d,]*\.?\d+\)"),
    ("percent",       r"[+-]?\d*\.?\d+\s?%"),
    ("iso_date",      r"\d{4}-\d{2}-\d{2}"),
    ("iso_datetime",  r"\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?"),
    ("slash_date",    r"\d{1,2}/\d{1,2}/\d{2,4}"),
    ("text_date",     r"[A-Za-z]{3,9}\.? \d{1,2},? \d{4}|\d{1,2} [A-Za-z]{3,9} \d{4}"),
    ("bool_word",     r"(?i:true|false|yes|no)"),
    ("code",          r"[A-Z0-9][A-Z0-9_]*"),
    ("word",          r"[A-Za-z][A-Za-z'.&/ -]*"),
]]
NUMERIC_FORMATS = {"int", "int_as_float", "decimal", "scientific",
                   "thousands_sep", "currency", "percent"}
CLEAN_NUMBER_FORMATS = {"int", "int_as_float", "decimal", "scientific"}
DATE_FORMATS = {"iso_date": "%Y-%m-%d", "iso_datetime": None,
                "slash_date": "%m/%d/%Y", "text_date": None}
NULL_CLASSES = {"blank", "null_token"}
INT_RX = re.compile(r"[+-]?\d+")
TOKEN_RX = re.compile(r"[A-Za-z]+|\d+")
NONPRINT_RX = r"[\x00-\x08\x0b-\x1f\x7f\xa0\t\r\n]"
DATE_PART_RX = re.compile(r"^(year|quarter|month|day|week|week_of_year|day_of_month|"
                          r"day_of_week|month_name|day_name)$")

# Conventional ranges, matched on column NAME (not on table)
RANGE_RULES = [
    # regex, hard_min, hard_max, soft_min, soft_max, note
    # first matching rule wins, so unit suffixes and compound names come first
    (r"(^|_)bps($|_)", 0, 10000, 0, 300, "basis points"),
    (r"(^|_)day_of_week$", 0, 7, None, None, "day of week"),
    (r"(^|_)week(_of_year)?$", 1, 53, None, None, "week number"),
    (r"(^|_)(day|day_of_month)$", 1, 31, None, None, "day of month"),
    (r"(^|_)(pct|percent|ratio|share)($|_)", 0, 1, None, None, "fraction (0-1)"),
    (r"(^|_)age$", 0, 120, 18, 100, "age in years"),
    (r"^(fiscal_|calendar_)?year$", 1900, 2100, None, None, "calendar year"),
    (r"^month$|_month$", 1, 12, None, None, "month number"),
    (r"(^|_)quarter$", 1, 4, None, None, "quarter number"),
    (r"(^|_)return($|_)", -1, None, None, None, "return as a decimal (>= -100%)"),
    (r"(years?_experience|tenure)", 0, 70, None, None, "years"),
    (r"(aum|amount|price|shares|balance|basis|value|cost|quantity|qty|target)",
     0, None, None, None, "money / quantity"),
]


# Tunable thresholds. These are statistical conventions, not business rules.
RULE_HOLD_SHARE = 0.95     # share of rows a discovered rule must satisfy
MAD_Z_IMPLAUSIBLE = 6      # robust z-score beyond which a rate is implausible
IQR_EXTREME = 5            # Tukey fence multiplier for extreme outliers (INFO)
INCOME_RX = re.compile(r"divid|interest|income|coupon|distribution", re.I)


def classify(v: str) -> str:
    """Format class of one stripped value."""
    if v == "":
        return "blank"
    if v.lower() in NULL_TOKENS:
        return "null_token"
    for name, rx in FORMATS:
        if rx.fullmatch(v):
            return name
    return "mixed_text"


def shape(v: str) -> str:
    """Generalised value shape: digits -> 9, letter runs -> A / Aa+ / a+."""
    if v == "":
        return "<blank>"

    def rep(m):
        t = m.group(0)
        if t.isdigit():
            return "9" * len(t) if len(t) <= 10 else "9{%d}" % len(t)
        if t.isupper():
            return "A" * len(t) if len(t) <= 5 else "A+"
        if t.islower():
            return "a+"
        if t[0].isupper() and t[1:].islower():
            return "Aa+"
        return "Xx+"
    return TOKEN_RX.sub(rep, v)


def singular(w: str) -> str:
    if w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def norm_key(s: pd.Series) -> pd.Series:
    """Canonical text for a key: ' 45.0 ' -> '45'; non-numeric keys stripped."""
    st = s.str.strip()
    num = pd.to_numeric(st, errors="coerce")
    ok = num.notna() & np.isfinite(num) & ((num % 1) == 0)
    out = st.copy()
    out[ok] = num[ok].astype("int64").astype(str)
    return out


def fmt_examples(vals, k=5):
    out = []
    for v in list(vals)[:k]:
        out.append(repr(v) if isinstance(v, str) else str(v))
    return "; ".join(out)


def decimals_of(s: pd.Series) -> int:
    d = s.str.strip().str.extract(r"\.(\d+)$")[0].str.len()
    return int(d.mode().iloc[0]) if d.notna().any() else 0


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------
FINDINGS: list[dict] = []
FORMULAS: list[dict] = []          # rules discovered by arithmetic_checks
REFS: dict[str, set] = {}          # dimension -> key values used by any FK
GROUPS = {0: "0 File", 1: "1 Column", 2: "2 Single-table",
          3: "3 Referential", 4: "4 Cross-table"}


def add(sev, group, check, table, column, n, total, detail, examples="",
        involves=None):
    FINDINGS.append(dict(
        severity=sev, group=GROUPS[group], check=check, table=table,
        column=column, rows_affected=int(n), table_rows=int(total),
        pct_rows=round(100.0 * n / total, 3) if total else None,
        detail=detail, examples=examples,
        _involves=set(involves or [table])))


# --------------------------------------------------------------------------
# Table model and inference
# --------------------------------------------------------------------------
class Table:
    def __init__(self, name, path, df):
        self.name, self.path, self.df, self.n = name, path, df, len(df)
        self.cols: dict[str, dict] = {}
        self.pk = None
        self.fks: dict[str, tuple[str, str]] = {}   # col -> (table, pk col)
        self.date_fks: list[str] = []               # date cols checked vs date dim
        self.role = "standalone"


def read_csv_as_text(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False,
                               encoding=enc)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"cannot decode {path}")


def infer_type(col, fmt, uniq, n_nonnull):
    name = col.lower()
    if n_nonnull == 0:
        return "empty"

    def share(keys):
        return sum(fmt.get(k, 0) for k in keys) / n_nonnull

    lower = {u.lower() for u in uniq}
    if share(DATE_FORMATS) >= 0.8:
        return "date"
    if lower and lower <= set(BOOL_MAP) - {"0", "1"}:
        return "boolean"
    if share(NUMERIC_FORMATS) >= 0.8:
        if lower <= {"0", "1"} and len(lower) == 2:
            return "boolean"
        if name == "id" or name.endswith("_id") or name.endswith("_key"):
            return "key"
        ints = [u for u in uniq if INT_RX.fullmatch(u)]
        lead0 = sum(1 for u in ints if len(u) > 1 and u[0] == "0")
        if re.search(r"zip|postal|phone|ssn|fips|routing", name) or \
                (ints and lead0 / len(ints) >= 0.01):
            return "code"
        if share({"int", "int_as_float"}) >= 0.98:
            return "integer"
        return "number"
    if len(uniq) <= 50 and len(uniq) <= max(2, 0.2 * n_nonnull):
        return "category"
    if share({"code"}) >= 0.9:
        return "code"
    return "text"


def parse_column(s: pd.Series, typ: str, fmt: dict, nonnull: pd.Series):
    """Convert on purpose. Returns (parsed values or None, fail mask)."""
    st = s.str.strip()
    parsed, fail = None, pd.Series(False, index=s.index)
    if typ in ("key", "integer", "number"):
        num = pd.to_numeric(st.where(nonnull), errors="coerce")
        num = num.where(np.isfinite(num))
        fail = nonnull & num.isna()
        if typ in ("key", "integer"):
            fail |= nonnull & num.notna() & ((num % 1) != 0)
        parsed = num
    elif typ == "date":
        dfmts = {k: v for k, v in fmt.items() if k in DATE_FORMATS}
        dom = max(dfmts, key=dfmts.get)
        parsed = pd.to_datetime(st.where(nonnull), format=DATE_FORMATS[dom],
                                errors="coerce")
        fail = nonnull & parsed.isna()
    elif typ == "boolean":
        parsed = st.str.lower().map(BOOL_MAP).astype(float)
        fail = nonnull & parsed.isna()
    elif typ == "code":
        nn = st[nonnull]
        if len(nn):
            cls = nn.map(classify)
            dom_cls = cls.mode().iloc[0]
            if dom_cls == "int":
                dom_len = nn.str.len().mode().iloc[0]
                ok = nn.str.fullmatch(r"\d+") & nn.str.len().eq(dom_len)
            else:
                ok = cls.eq(dom_cls)
            fail.loc[nn.index] = ~ok
    return parsed, fail


def analyze_table(t: Table):
    df = t.df
    for c in df.columns:
        s = df[c]
        vc = s.value_counts()
        raw = vc.index.to_series(index=vc.index)
        stripped = raw.str.strip()
        cls = stripped.map(classify)
        shp = raw.map(shape)
        fmt = vc.groupby(cls.values).sum().to_dict()
        shapes = vc.groupby(shp.values).sum().sort_values(ascending=False)
        n_blank = int(fmt.get("blank", 0))
        n_tok = int(fmt.get("null_token", 0))
        nonnull_vals = stripped[~cls.isin(list(NULL_CLASSES))]
        uniq = set(nonnull_vals)
        n_nonnull = t.n - n_blank - n_tok
        typ = infer_type(c, fmt, uniq, n_nonnull)
        st = s.str.strip()
        nonnull = ~(st.eq("") | st.str.lower().isin(NULL_TOKENS))
        parsed, fail = parse_column(s, typ, fmt, nonnull)
        t.cols[c] = dict(
            type=typ, fmt=fmt, shapes=shapes, vc=vc, n_blank=n_blank,
            n_token=n_tok, n_nonnull=n_nonnull, uniq=uniq,
            n_distinct=len(uniq), nonnull=nonnull, parsed=parsed, fail=fail,
            stripped=st, tokens=sorted({v for v in stripped[cls == "null_token"]}),
        )


def detect_pk(t: Table):
    toks = {singular(x) for x in re.split(r"[_\W]+", t.name.lower())
            if x and x not in {"dim", "fact", "tbl", "table", "raw", "stg"}}
    keys = [c for c in t.df.columns if t.cols[c]["type"] == "key"]

    def ratio(c):
        return norm_key(t.df[c]).nunique() / max(t.n, 1)
    for c in keys:
        stem = c.lower()[:-3] if c.lower().endswith("_id") else c.lower()
        if singular(stem) in toks and ratio(c) >= 0.9:
            return c
    if keys and t.df.columns[0] == keys[0] and ratio(keys[0]) >= 0.9:
        return keys[0]
    for c in keys:
        if ratio(c) >= 0.98:
            return c
    return None


def build_model(tables: dict[str, Table]):
    for t in tables.values():
        analyze_table(t)
        t.pk = detect_pk(t)
    pk_index = {t.pk: t.name for t in tables.values() if t.pk}
    for t in tables.values():
        for c, m in t.cols.items():
            if m["type"] == "key" and c != t.pk and c in pk_index \
                    and pk_index[c] != t.name:
                t.fks[c] = (pk_index[c], c)
    # date dimension: a unique, gap-free daily date column
    date_dim = None
    for t in tables.values():
        for c, m in t.cols.items():
            if m["type"] != "date":
                continue
            d = m["parsed"].dropna()
            if len(d) >= 300 and d.is_unique and \
                    (d.max() - d.min()).days + 1 == len(d):
                date_dim = (t.name, c)
    referenced = {d for t in tables.values() for d, _ in t.fks.values()}
    if date_dim:
        referenced.add(date_dim[0])
    for t in tables.values():
        if t.name in referenced:
            t.role = "dimension"
        elif t.fks:
            t.role = "fact"
        if t.role == "fact" and date_dim:
            t.date_fks = [c for c, m in t.cols.items() if m["type"] == "date"]
    return date_dim


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------
def mixed_format(typ, m):
    nn = {k: v for k, v in m["fmt"].items() if k not in NULL_CLASSES}
    if not nn:
        return False, ""
    if typ in ("integer", "key", "date"):
        bad = nn if len(nn) > 1 else {}
    elif typ == "number":
        bad = {k: v for k, v in nn.items() if k not in CLEAN_NUMBER_FORMATS}
        if len(bad) == len(nn) and len(bad) == 1:
            bad = {}
    elif typ == "boolean":
        spell = sorted(m["uniq"])
        return (len(spell) > 2, "spellings: " + ", ".join(spell)) if len(spell) > 2 else (False, "")
    elif typ in ("category", "code"):
        shp = m["shapes"].drop("<blank>", errors="ignore")
        tot = shp.sum()
        if tot and shp.iloc[0] / tot >= 0.9 and len(shp) > 1:
            dom = shp.index[0]
            mv = [(k, v) for k, v in m["vc"].items() if k.strip() and shape(k) != dom]
            return True, (f"dominant shape '{dom}' ({shp.iloc[0]/tot:.1%}); minority values: "
                          + ", ".join(f"'{k}' x{v}" for k, v in mv[:10]))
        return False, ""
    else:
        return False, ""
    if not bad:
        return False, ""
    return True, ", ".join(f"{k} x{v}" for k, v in sorted(nn.items(), key=lambda x: -x[1]))


def profile_rows(t: Table):
    rows = []
    for c in t.df.columns:
        m = t.cols[c]
        s, st = t.df[c], m["stripped"]
        n = t.n
        ws_edge = int(((s != st) & (st != "")).sum())
        ws_only = int(((s != "") & (st == "")).sum())
        ws_inner = int(st.str.contains("  ", regex=False).sum())
        nonprint = int(s.str.contains(NONPRINT_RX, regex=True).sum())
        shapes = m["shapes"]
        top_shapes = "; ".join(f"{k} ({v/n:.1%})" for k, v in shapes.head(3).items())
        topv = "; ".join(f"{k!r} x{v}" for k, v in m["vc"].head(5).items())
        mixed, mixed_desc = mixed_format(m["type"], m)
        nfail = int(m["fail"].sum())
        fail_ex = fmt_examples(st[m["fail"]].drop_duplicates())
        mn = mx = mean = median = ""
        p = m["parsed"]
        if p is not None and m["type"] in ("key", "integer", "number") and p.notna().any():
            mn, mx = p.min(), p.max()
            mean, median = round(p.mean(), 6), p.median()
        elif p is not None and m["type"] == "date" and p.notna().any():
            mn, mx = p.min().date().isoformat(), p.max().date().isoformat()
        lens = st[m["nonnull"]].str.len()
        rows.append(dict(
            table=t.name, column=c, inferred_type=m["type"],
            key_role=("PK" if c == t.pk else
                      f"FK -> {t.fks[c][0]}.{t.fks[c][1]}" if c in t.fks else ""),
            rows=n,
            null_blank_count=m["n_blank"] + m["n_token"],
            null_blank_pct=round(100 * (m["n_blank"] + m["n_token"]) / n, 3) if n else 0,
            blank_count=m["n_blank"], null_token_count=m["n_token"],
            null_tokens_seen=", ".join(m["tokens"]),
            distinct_count=m["n_distinct"],
            distinct_pct=round(100 * m["n_distinct"] / n, 3) if n else 0,
            distinct_after_normalising=len({u.casefold() for u in m["uniq"]}),
            top_values=topv, dominant_shapes=top_shapes, n_shapes=len(shapes),
            format_classes=", ".join(f"{k} x{v}" for k, v in
                                     sorted(m["fmt"].items(), key=lambda x: -x[1])),
            mixed_formats=mixed, mixed_format_detail=mixed_desc,
            parse_fail_count=nfail,
            parse_fail_pct=round(100 * nfail / m["n_nonnull"], 3) if m["n_nonnull"] else 0,
            parse_fail_examples=fail_ex,
            whitespace_edge_count=ws_edge, whitespace_only_count=ws_only,
            whitespace_inner_double_count=ws_inner, nonprintable_count=nonprint,
            min=mn, max=mx, mean=mean, median=median,
            len_min=int(lens.min()) if len(lens) else "",
            len_max=int(lens.max()) if len(lens) else "",
        ))
    return rows


# --------------------------------------------------------------------------
# Group 1: column-level checks
# --------------------------------------------------------------------------
def column_checks(t: Table, as_of):
    n = t.n
    for c in t.df.columns:
        m = t.cols[c]
        typ, s, st = m["type"], t.df[c], m["stripped"]
        nulls = m["n_blank"] + m["n_token"]
        is_fk = c in t.fks

        # ---- type / parsing
        nfail = int(m["fail"].sum())
        if nfail:
            fails = st[m["fail"]]
            classes = fails.map(classify).value_counts()
            sev = "WARN" if typ == "code" else "ERROR"
            add(sev, 1, "type: value fails to parse as expected type", t.name, c,
                nfail, n, f"expected {typ}; failing formats: " +
                ", ".join(f"{k} x{v}" for k, v in classes.items()),
                fmt_examples(fails.drop_duplicates()))
        if typ in ("key", "integer") and m["fmt"].get("int_as_float"):
            k = m["fmt"]["int_as_float"]
            add("INFO", 1, "type: integer stored as float text", t.name, c, k, n,
                "values like '45.0' are intact once cast to integer"
                + ("; as a foreign key this breaks text joins - see group 3" if is_fk else ""),
                fmt_examples([v for v in m["uniq"] if v.endswith(".0")]))
        mixed, desc = mixed_format(typ, m)
        if mixed:
            add("WARN", 1, "type: mixed formats in one column", t.name, c,
                m["n_nonnull"], n, desc)
        if typ == "empty":
            add("WARN", 1, "type: column is entirely blank", t.name, c, n, n, "")

        # ---- completeness
        if nulls:
            share = nulls / n
            if c == t.pk:
                add("ERROR", 1, "key: primary key is blank", t.name, c, nulls, n, "")
            elif share <= 0.05:
                add("ERROR" if is_fk else "WARN", 1,
                    "completeness: sporadic blanks in a mostly-filled column",
                    t.name, c, nulls, n, f"{share:.2%} blank" +
                    ("; foreign key - these rows drop out of inner joins" if is_fk else ""))
            else:
                add("INFO", 1, "completeness: column has blanks", t.name, c,
                    nulls, n, f"{share:.2%} blank (see group-2 conditional checks)")
        if m["n_token"]:
            sev = "INFO" if typ in ("category", "text") else "WARN"
            add(sev, 1, "completeness: literal null token used as a value",
                t.name, c, m["n_token"], n,
                f"tokens {m['tokens']} - default pd.read_csv would turn these into NaN",
                fmt_examples(m["tokens"]))

        # ---- whitespace / hygiene
        edge = int(((s != st) & (st != "")).sum())
        if edge:
            add("WARN", 1, "whitespace: leading/trailing spaces", t.name, c, edge, n,
                "breaks equality, grouping and joins",
                fmt_examples(s[(s != st) & (st != "")].drop_duplicates()))
        ws_only = int(((s != "") & (st == "")).sum())
        if ws_only:
            add("WARN", 1, "whitespace: whitespace-only cell", t.name, c, ws_only, n,
                "looks filled but is blank")
        inner = int(st.str.contains("  ", regex=False).sum())
        if inner:
            add("WARN", 1, "whitespace: repeated inner spaces", t.name, c, inner, n, "",
                fmt_examples(st[st.str.contains("  ", regex=False)].drop_duplicates()))
        npr = int(s.str.contains(NONPRINT_RX, regex=True).sum())
        if npr:
            add("WARN", 1, "whitespace: tab/newline/non-breaking space", t.name, c, npr, n, "")

        # ---- allowed values (inferred domain for categoricals / booleans)
        if typ in ("category", "boolean", "code") and m["n_distinct"] > 1:
            groups = {}
            for u in m["uniq"]:
                groups.setdefault(re.sub(r"\s+", " ", u).casefold(), []).append(u)
            variants = [v for v in groups.values() if len(v) > 1]
            if variants:
                cnt = int(st.isin([x for v in variants for x in v]).sum())
                add("WARN", 1, "allowed values: case/spacing variants of one value",
                    t.name, c, cnt, n, "; ".join(" / ".join(v) for v in variants[:5]))
        if typ == "category" and n >= 1000:
            vc = st[m["nonnull"]].value_counts()
            rare = vc[vc <= max(2, 0.001 * n)]
            dom_shape = m["shapes"].drop("<blank>", errors="ignore").index[0]
            # values in a minority FORMAT are already reported as mixed formats
            rare = rare[[shape(v) == dom_shape for v in rare.index]]
            if len(rare) and len(rare) < len(vc):
                common = list(vc[vc > max(2, 0.001 * n)].index)
                notes = []
                for r in rare.index[:5]:
                    near = difflib.get_close_matches(r, common, n=1, cutoff=0.7)
                    notes.append(f"'{r}'" + (f" ~ '{near[0]}'" if near else ""))
                add("WARN", 1, "allowed values: rare value outside the usual domain",
                    t.name, c, int(rare.sum()), n, "; ".join(notes))
        if typ == "category":
            add("INFO", 1, "allowed values: observed domain", t.name, c,
                m["n_nonnull"], n,
                f"{m['n_distinct']} values: " + ", ".join(sorted(m["uniq"])[:25]))

        # ---- ranges
        p = m["parsed"]
        if typ in ("integer", "number") and p is not None and p.notna().any():
            for rx, hmin, hmax, smin, smax, note in RANGE_RULES:
                if not re.search(rx, c.lower()):
                    continue
                if hmin is not None or hmax is not None:
                    bad = (p < hmin if hmin is not None else False) | \
                          (p > hmax if hmax is not None else False)
                    bad = bad & p.notna()
                    if bad.any():
                        sev = "WARN" if note == "money / quantity" else "ERROR"
                        add(sev, 1, "range: outside valid range", t.name, c,
                            int(bad.sum()), n,
                            f"{note}: expected [{hmin}, {hmax if hmax is not None else 'inf'}]",
                            fmt_examples(st[bad].drop_duplicates()))
                if smin is not None or smax is not None:
                    soft = (p < smin if smin is not None else False) | \
                           (p > smax if smax is not None else False)
                    soft = soft & p.notna()
                    if hmin is not None:
                        soft &= p >= hmin
                    if hmax is not None:
                        soft &= p <= hmax
                    if soft.any():
                        add("WARN", 1, "range: implausible value", t.name, c,
                            int(soft.sum()), n,
                            f"{note}: plausible range [{smin}, {smax}]",
                            fmt_examples(st[soft].drop_duplicates()))
                break
            # implausible rates: robust z-score (median / MAD) instead of guessed ranges
            if typ == "number" and p.notna().sum() >= 100:
                med = p.median()
                if abs(med) <= 1 and p.abs().quantile(0.95) <= 5:
                    mad = 1.4826 * (p - med).abs().median()
                    if mad > 0:
                        lo, hi = med - MAD_Z_IMPLAUSIBLE * mad, med + MAD_Z_IMPLAUSIBLE * mad
                        imp = (p < lo) | (p > hi)
                        if imp.any():
                            add("WARN", 1, "range: implausible rate (robust z-score)",
                                t.name, c, int(imp.sum()), n,
                                f"rate-like column (median {med:.4g}); {int((p < lo).sum())} below "
                                f"{lo:.3g} and {int((p > hi).sum())} above {hi:.3g} "
                                f"(more than {MAD_Z_IMPLAUSIBLE} robust SDs from the median)",
                                fmt_examples(st[imp].drop_duplicates()))
            # statistical outliers + repeated round values on continuous columns
            if typ == "number" and m["n_distinct"] > 50:
                q1, q3 = p.quantile([0.25, 0.75])
                iqr = q3 - q1
                if iqr > 0:
                    out = (p < q1 - IQR_EXTREME * iqr) | (p > q3 + IQR_EXTREME * iqr)
                    best = None
                    for g, mg in t.cols.items():
                        if mg["type"] != "category" or not (2 <= mg["n_distinct"] <= 20) \
                                or mg["n_nonnull"] < 0.8 * n:
                            continue
                        gv = mg["stripped"]
                        qs = p.groupby(gv).quantile([0.25, 0.75]).unstack()
                        glo, ghi = gv.map(qs[0.25]), gv.map(qs[0.75])
                        o2 = (p < glo - IQR_EXTREME * (ghi - glo)) | (p > ghi + IQR_EXTREME * (ghi - glo))
                        if best is None or o2.sum() < best[1].sum():
                            best = (g, o2)
                    if out.any() and best is not None and best[1].sum() <= 0.5 * out.sum():
                        g, o2 = best
                        if o2.any():
                            add("INFO", 1, f"range: extreme outliers within {g} segments",
                                t.name, c, int(o2.sum()), n,
                                f"beyond {IQR_EXTREME} x IQR of their own {g} ({int(out.sum())} "
                                f"overall outliers drop to {int(o2.sum())} once {g} is considered)",
                                fmt_examples(st[o2].drop_duplicates()))
                        else:
                            add("INFO", 1, "range: outliers explained by segment", t.name, c,
                                int(out.sum()), n,
                                f"all {int(out.sum())} values beyond {IQR_EXTREME} x IQR are normal "
                                f"within their {g} - expected skew, not errors")
                    elif out.any():
                        add("INFO", 1, f"range: extreme outliers (beyond {IQR_EXTREME} x IQR)",
                            t.name, c, int(out.sum()), n,
                            f"Q1={q1:g}, Q3={q3:g}",
                            fmt_examples(st[out].drop_duplicates()))
                vc = p.value_counts()
                if len(vc) > 50:
                    thresh = max(10, 50 * vc.median())
                    # 0 is a natural value (no change, no balance), never a sentinel
                    sent = vc[(vc >= thresh) & ((vc.index % 1) == 0) & (vc.index != 0)]
                    for val, cnt in sent.head(3).items():
                        kind, why = sentinel_kind(t, c, p, val)
                        add("WARN", 1, f"range: repeated round value ({kind})",
                            t.name, c, int(cnt), n,
                            f"{val:g} repeats {cnt} times where a typical value repeats "
                            f"{vc.median():g} time(s); {why}", str(val))

        # ---- dates
        if typ == "date" and p is not None and p.notna().any():
            fut = p > as_of
            if fut.any():
                add("WARN", 1, "range: date after the data's as-of date", t.name, c,
                    int(fut.sum()), n, f"as-of {as_of.date()}",
                    fmt_examples(st[fut].drop_duplicates()))
            old = p < pd.Timestamp("1900-01-01")
            if old.any():
                add("ERROR", 1, "range: date before 1900", t.name, c, int(old.sum()), n, "")
            d1 = (p.dt.day == 1)
            share1 = d1[p.notna()].mean()
            if 0.95 <= share1 < 1:
                bad = p.notna() & ~d1
                add("WARN", 1, "type: date grain - not first of month", t.name, c,
                    int(bad.sum()), n, f"{share1:.2%} of dates are the 1st",
                    fmt_examples(st[bad].drop_duplicates()))

        # ---- uniqueness
        if c == t.pk:
            nk = norm_key(s)
            dup = nk.duplicated(keep=False) & nk.ne("")
            if dup.any():
                add("ERROR", 1, "key: primary key not unique", t.name, c,
                    int(dup.sum()), n, f"{nk[dup].nunique()} key values repeat",
                    fmt_examples(nk[dup].drop_duplicates()))
        elif typ in ("text", "code", "key") and m["n_distinct"] >= 50:
            ratio = m["n_distinct"] / max(m["n_nonnull"], 1)
            if 0.99 <= ratio < 1:
                dup = st.duplicated(keep=False) & m["nonnull"]
                add("WARN", 1, "key: near-unique column has duplicates", t.name, c,
                    int(dup.sum()), n,
                    f"{ratio:.2%} unique - likely meant to be unique",
                    fmt_examples(st[dup].drop_duplicates()))
        if m["n_distinct"] == 1 and t.n > 1:
            add("INFO", 1, "type: constant column", t.name, c, n, n,
                f"only value {next(iter(m['uniq']))!r}")


# --------------------------------------------------------------------------
# Group 2: single-table rules
# --------------------------------------------------------------------------
def canon(t: Table) -> pd.DataFrame:
    """Normalised copy: trimmed, case-folded, numbers/dates canonical."""
    out = {}
    for c in t.df.columns:
        m = t.cols[c]
        if m["type"] in ("key", "integer"):
            out[c] = norm_key(t.df[c])
        elif m["type"] == "number":
            out[c] = m["parsed"].round(6).astype(str)
        elif m["type"] == "date":
            out[c] = m["parsed"].dt.strftime("%Y-%m-%d").fillna(m["stripped"])
        elif m["type"] == "boolean":
            out[c] = m["parsed"].astype(str)
        else:
            out[c] = m["stripped"].str.replace(r"\s+", " ", regex=True).str.casefold()
    return pd.DataFrame(out)


def duplicate_checks(t: Table, cdf: pd.DataFrame, refs=None):
    n = t.n
    non_pk = [c for c in t.df.columns if c != t.pk]
    if not non_pk:
        return
    exact = t.df.duplicated(subset=non_pk, keep=False)
    if exact.any():
        add("WARN", 2, "duplicates: identical rows (ignoring the PK)", t.name,
            ", ".join(non_pk[:4]) + ("..." if len(non_pk) > 4 else ""),
            int(exact.sum()), n, f"{int(t.df[exact].duplicated(subset=non_pk).sum())} extra copies",
            fmt_examples(t.df.loc[exact, t.pk].head(5)) if t.pk else "")
    near = cdf.duplicated(subset=non_pk, keep=False) & ~exact
    if near.any():
        add("WARN", 2, "near-duplicates: identical after trimming/case/number normalisation",
            t.name, "", int(near.sum()), n,
            "rows differ only in spacing, case or number formatting",
            fmt_examples(t.df.loc[near, t.pk].head(5)) if t.pk else "")
    # rows identical on all columns but one (dimension-sized tables only)
    if n <= 20000 and len(non_pk) >= 3:
        for c in non_pk:
            others = [x for x in non_pk if x != c]
            d = cdf.duplicated(subset=others, keep=False) & ~cdf.duplicated(subset=non_pk, keep=False)
            if d.any():
                npairs = trunc = unref = 0
                copies, ex = [], []
                for _, g in cdf[d].groupby(others, sort=False):
                    npairs += 1
                    vals = t.df.loc[g.index, c].str.strip().tolist()
                    if len(vals) == 2 and vals[0] != vals[1] and \
                            (vals[0].startswith(vals[1]) or vals[1].startswith(vals[0])):
                        trunc += 1
                    if t.pk:
                        keys = norm_key(t.df.loc[g.index, t.pk])
                        if refs is not None:
                            used = keys.isin(refs)
                            if len(keys) == 2 and used.sum() == 1:
                                unref += 1
                                copies.append(keys[~used].iloc[0])
                        if len(ex) < 5:
                            ex.append(" / ".join(f"{k}:{v}" for k, v in zip(keys, vals)))
                notes = []
                if trunc:
                    notes.append(f"in {trunc} of {npairs} pairs one value is a truncation of the other")
                if unref:
                    notes.append(f"in {unref} of {npairs} pairs only one row is used by any fact table "
                                 f"(unused copies: {', '.join(sorted(copies, key=lambda x: (len(x), x))[:10])}"
                                 f"{'...' if len(copies) > 10 else ''})")
                confirmed = (trunc + unref) and max(trunc, unref) >= 0.8 * npairs
                add("ERROR" if confirmed else "WARN", 2,
                    "duplicates: same entity recorded twice" if confirmed else
                    "near-duplicates: rows identical except one column",
                    t.name, c, int(d.sum()), n,
                    f"{npairs} groups identical in every other column; differ only in '{c}'"
                    + ("; " + "; ".join(notes) if notes else ""), fmt_examples(ex))
    # natural grain of fact-like tables: FK columns + date columns
    if t.role == "fact":
        grain = list(t.fks) + [c for c, m in t.cols.items() if m["type"] == "date"]
        if grain:
            dup = cdf.duplicated(subset=grain, keep=False)
            share_unique = 1 - dup.mean()
            if dup.any() and share_unique >= 0.99:
                add("WARN", 2, "duplicates: grain violation", t.name, ", ".join(grain),
                    int(dup.sum()), n,
                    f"({', '.join(grain)}) is unique for {share_unique:.2%} of rows - "
                    "the rest look like double-loaded records",
                    fmt_examples(t.df.loc[dup, t.pk].head(6)) if t.pk else "")
            elif dup.any():
                add("INFO", 2, "duplicates: table grain is finer than FKs + date",
                    t.name, ", ".join(grain), int(dup.sum()), n,
                    "several rows share the same keys and date (expected for event tables)")


DATE_PARTS = {
    "year": [lambda d: d.dt.year],
    "quarter": [lambda d: d.dt.quarter],
    "month": [lambda d: d.dt.month],
    "day": [lambda d: d.dt.day], "day_of_month": [lambda d: d.dt.day],
    "week_of_year": [lambda d: d.dt.isocalendar().week.astype(float),
                     lambda d: d.dt.strftime("%U").astype(int) + 1,
                     lambda d: d.dt.strftime("%W").astype(int) + 1,
                     lambda d: (d.dt.dayofyear - 1) // 7 + 1],
    "month_name": [lambda d: d.dt.month_name()],
    "day_of_week": [lambda d: d.dt.day_name(), lambda d: d.dt.dayofweek,
                    lambda d: d.dt.dayofweek + 1, lambda d: (d.dt.dayofweek + 1) % 7],
    "day_name": [lambda d: d.dt.day_name()],
    "is_month_end": [lambda d: d.dt.is_month_end.astype(int)],
    "is_month_start": [lambda d: d.dt.is_month_start.astype(int)],
    "is_quarter_end": [lambda d: d.dt.is_quarter_end.astype(int)],
    "is_year_end": [lambda d: d.dt.is_year_end.astype(int)],
    "is_weekend": [lambda d: (d.dt.dayofweek >= 5).astype(int)],
    "is_weekday": [lambda d: (d.dt.dayofweek < 5).astype(int)],
}


def _as_text(series, m=None):
    if m is not None and m["type"] == "boolean":
        return m["parsed"].map(lambda x: "" if pd.isna(x) else str(int(x)))
    s = series.astype(str).str.strip().str.casefold()
    return s.str.replace(r"\.0$", "", regex=True)


def date_part_checks(t: Table):
    dcols = [c for c, m in t.cols.items() if m["type"] == "date"]
    if len(dcols) != 1:
        return
    dc = dcols[0]
    d = t.cols[dc]["parsed"]
    ok = d.notna()
    for c in t.df.columns:
        key = c.lower()
        if key not in DATE_PARTS:
            continue
        actual = _as_text(t.df[c], t.cols[c])
        best = None
        for fn in DATE_PARTS[key]:
            exp = _as_text(fn(d[ok]))
            mism = (exp != actual[ok]) & actual[ok].ne("")
            if best is None or mism.sum() < best.sum():
                best = mism
        if best is None:
            continue
        rate = 1 - best.mean()
        if best.any() and rate >= 0.5:
            idx = best[best].index
            add("ERROR", 2, "row contradiction: derived date part disagrees with the date",
                t.name, f"{c} vs {dc}", int(best.sum()), t.n,
                f"{c} matches {dc} on {rate:.2%} of rows",
                fmt_examples([f"{t.df.at[i, dc]} -> {c}={t.df.at[i, c]}" for i in idx[:5]]))
        elif best.any():
            add("INFO", 2, "row contradiction: date-part column uses an unknown convention",
                t.name, f"{c} vs {dc}", int(best.sum()), t.n,
                f"only {rate:.2%} agreement with standard {key}")
    # weekend vs trading/business day style flags
    for c in t.df.columns:
        if re.search(r"(trading|business|work)_?day", c.lower()) and t.cols[c]["type"] == "boolean":
            flag = t.cols[c]["parsed"]
            bad = ok & (d.dt.dayofweek >= 5) & (flag == 1)
            if bad.any():
                add("ERROR", 2, "row contradiction: weekend flagged as a trading/business day",
                    t.name, f"{c} vs {dc}", int(bad.sum()), t.n, "",
                    fmt_examples(t.df.loc[bad, dc].head(5)))
            wk = ok & (d.dt.dayofweek < 5)
            hol = wk & (d.dt.strftime("%m-%d").isin(["01-01", "07-04", "12-25"])) & (flag == 1)
            if wk.any() and (flag[wk] == 1).all() or hol.any():
                add("INFO", 2, "row contradiction: trading-day flag ignores market holidays",
                    t.name, f"{c} vs {dc}", int(hol.sum()), t.n,
                    "fixed-date holidays (Jan 1, Jul 4, Dec 25) on weekdays are flagged as trading days",
                    fmt_examples(t.df.loc[hol, dc].head(5)))


OPS = [
    ("{a} - {b}", lambda a, b: a - b, False),
    ("{a} + {b}", lambda a, b: a + b, True),
    ("{a} * {b}", lambda a, b: a * b, True),
    ("{a} * {b} / 100", lambda a, b: a * b / 100, True),
    ("{a} * {b} / 10000", lambda a, b: a * b / 1e4, True),
    ("{a} * {b} / 1200", lambda a, b: a * b / 1200, True),
    ("{a} * {b} / 120000", lambda a, b: a * b / 1.2e5, True),
    ("{a} / {b}", lambda a, b: a / b, False),
]


def arithmetic_checks(t: Table, rng):
    """Discover formulas c = f(a, b) that hold for >=95% of rows; flag the rest."""
    num = [c for c, m in t.cols.items()
           if m["type"] in ("number", "integer") and c != t.pk
           and not DATE_PART_RX.match(c.lower()) and m["n_distinct"] > 2]
    if len(num) < 3:
        return
    P = {c: t.cols[c]["parsed"] for c in num}
    DEC = {c: decimals_of(t.df[c]) for c in num}
    for trio in itertools.combinations(num, 3):
        mask = P[trio[0]].notna() & P[trio[1]].notna() & P[trio[2]].notna()
        if mask.sum() < 30:
            continue
        idx = mask[mask].index
        samp = idx if len(idx) <= 20000 else rng.choice(idx, 20000, replace=False)
        best = None   # (score, prefer, c, a, b, label, fn, rel, tol_name)
        for c in trio:
            a_, b_ = [x for x in trio if x != c]
            cv = P[c][samp]
            strict = 2 * 10 ** -DEC[c] + 1e-9 * np.abs(cv)
            loose = np.maximum(strict, 1e-3 * np.abs(cv))
            for a, b in ((a_, b_), (b_, a_)):
                for rank, (label, fn, commutative) in enumerate(OPS):
                    if commutative and a > b:
                        continue
                    with np.errstate(all="ignore"):
                        ev = fn(P[a][samp], P[b][samp])
                    err = np.abs(ev - cv)
                    s_strict, s_loose = (err <= strict).mean(), (err <= loose).mean()
                    prefer = -1 if "/ {b}" in label else 0   # prefer * and +/- forms
                    for score, rel, name in ((s_strict, 0, "strict"),
                                             (s_loose - 0.02, 1e-3, "0.1% relative")):
                        if score >= 0.95:
                            cand = (score, prefer, -rank, c, a, b, label, fn, rel, name)
                            if best is None or cand[:3] > best[:3]:
                                best = cand
                            break
        if not best:
            continue
        _, _, _, c, a, b, label, fn, rel, tol_name = best
        if (np.isclose(P[c][samp], P[a][samp], rtol=1e-6)).mean() >= 0.95:
            continue
        cf = P[c][idx]
        with np.errstate(all="ignore"):
            full = fn(P[a][idx], P[b][idx])
        tol = np.maximum(2 * 10 ** -DEC[c] + 1e-9 * np.abs(cf), rel * np.abs(cf))
        bad = np.abs(full - cf) > tol
        formula = f"{c} = " + label.format(a=a, b=b)
        FORMULAS.append(dict(table=t.name, target=c, inputs=(a, b), formula=formula))
        by_group = ""
        groupers = [g for g, mg in t.cols.items() if mg["type"] in ("category", "boolean")
                    and 2 <= mg["n_distinct"] <= 20 and mg["n_nonnull"] >= 0.8 * t.n]
        for g in groupers:
            gv = t.cols[g]["stripped"][idx]
            if bad.any():
                vb = bad.groupby(gv).sum()
                vb = vb[vb > 0]
                by_group += f"; violations by {g}: " + ", ".join(f"{k} {int(v)}" for k, v in vb.items())
            if "*" in label and "/ {b}" not in label:
                hold = (~bad).groupby(gv).mean()
                for gval, hr in hold.items():
                    if INCOME_RX.search(str(gval)) and hr >= RULE_HOLD_SHARE:
                        gi = gv[gv.eq(gval)].index
                        add("WARN", 2, "plausibility: income rows carry the full position value",
                            t.name, f"{c} ({g}='{gval}')", len(gi), t.n,
                            f"{formula} holds on {hr:.2%} of '{gval}' rows, so each amount equals the "
                            f"whole position's market value, not a payout (normally a few % a year); "
                            f"median '{gval}' {c} = {P[c][gi].median():,.2f}",
                            fmt_examples([f"{t.df.at[i, a]} x {t.df.at[i, b]} = {t.df.at[i, c]}"
                                          for i in gi[:3]]))
        if bad.any():
            ex = [f"row {t.df.at[i, t.pk] if t.pk else i}: {c}={t.df.at[i, c]} "
                  f"expected {full[i]:.6g}" for i in bad[bad].index[:5]]
            # which input explains the break (e.g. a sign flipped on one input)?
            why = ""
            with np.errstate(all="ignore"):
                for x in (a, b):
                    alt = {a: P[a][idx], b: P[b][idx]}
                    alt[x] = alt[x].abs()
                    fixed = np.abs(fn(alt[a], alt[b]) - cf) <= tol
                    if fixed[bad].mean() >= 0.99:
                        why = f"; using abs({x}) satisfies the rule on {fixed[bad].mean():.0%} of these rows (sign error in {x})"
                        break
            add("ERROR", 2, "row contradiction: column breaks a formula that holds for the rest",
                t.name, c, int(bad.sum()), t.n,
                f"discovered rule {formula} (holds on {1 - bad.mean():.2%} of "
                f"{len(idx)} complete rows, tolerance {tol_name}){by_group}{why}", fmt_examples(ex))
        else:
            add("INFO", 2, "row contradiction: discovered formula holds on every row",
                t.name, c, 0, t.n, f"{formula} (tolerance {tol_name})")


def conditional_checks(t: Table):
    """A category that decides whether another column is filled / its sign."""
    groupers = [c for c, m in t.cols.items()
                if m["type"] in ("category", "boolean") and 2 <= m["n_distinct"] <= 20
                and m["n_nonnull"] >= 0.8 * t.n]
    for g in groupers:
        gv = t.cols[g]["stripped"]
        for x in t.df.columns:
            if x == g:
                continue
            blank = ~t.cols[x]["nonnull"]
            rate = blank.groupby(gv).mean()
            size = gv.value_counts()
            rate = rate[size.reindex(rate.index) >= 30]
            if len(rate) < 2:
                continue
            structural = (rate >= 0.98).any() and (rate <= 0.02).any()
            if not structural:
                continue
            bad = pd.Series(False, index=t.df.index)
            parts = []
            for gval, r in rate.items():
                inm = gv.eq(gval)
                if r >= 0.98 and r < 1:
                    b = inm & ~blank
                    parts.append(f"{g}='{gval}' should leave {x} blank: {int(b.sum())} filled")
                    bad |= b
                elif 0 < r <= 0.02:
                    b = inm & blank
                    parts.append(f"{g}='{gval}' should fill {x}: {int(b.sum())} blank")
                    bad |= b
            if bad.any():
                add("WARN", 2, "row contradiction: column filled/blank against its category",
                    t.name, f"{x} by {g}", int(bad.sum()), t.n, "; ".join(parts),
                    fmt_examples(t.df.loc[bad, t.pk].head(5)) if t.pk else "")
            else:
                filled_in = [str(k) for k, r in rate.items() if r <= 0.02]
                add("INFO", 2, "row contradiction: conditional completeness rule holds",
                    t.name, f"{x} by {g}", 0, t.n,
                    f"{x} is filled only when {g} in {filled_in}")
        # sign consistency within category
        for x, m in t.cols.items():
            if m["type"] not in ("number", "integer") or x == t.pk:
                continue
            p = m["parsed"]
            for gval, sub in p.groupby(gv):
                sub = sub.dropna()
                sub = sub[sub != 0]
                if len(sub) < 30:
                    continue
                pos = (sub > 0).mean()
                if 0.98 <= pos < 1 or 0 < pos <= 0.02:
                    wrong = sub[(sub < 0)] if pos >= 0.98 else sub[(sub > 0)]
                    add("WARN", 2, "row contradiction: sign differs from the rest of its category",
                        t.name, f"{x} by {g}", len(wrong), t.n,
                        f"{g}='{gval}': {pos:.2%} positive",
                        fmt_examples(t.df.loc[wrong.index, x].head(5)))


def fd_checks(t: Table, cdf: pd.DataFrame):
    """Near functional dependencies: D decides X almost always - flag the rest."""
    n = t.n
    if n < 50:
        return
    det_ok = ("key", "category", "boolean", "date", "integer", "code")
    dets = [c for c, m in t.cols.items() if m["type"] in det_ok and c != t.pk
            and 2 <= m["n_distinct"] <= 0.5 * n]
    targets = [c for c, m in t.cols.items() if c != t.pk and m["n_distinct"] >= 2]
    full_fd = set()

    def test(dcols, x):
        sub = cdf[dcols + [x]]
        sub = sub[(sub != "").all(axis=1) & (sub != "nan").all(axis=1)]
        grp = sub.groupby(dcols, sort=False)[x]
        size = grp.size()
        multi = size[size >= 2]
        if len(multi) < 20 or multi.sum() < 0.5 * len(sub):
            return None
        nun = grp.nunique().reindex(multi.index)
        viol = nun[nun > 1]
        if len(viol) == 0:
            return "full"
        if len(viol) > 0.01 * len(nun):
            return None
        vsub = sub.set_index(dcols).loc[viol.index].reset_index()
        mode = vsub.groupby(dcols)[x].agg(lambda s: s.mode().iloc[0])
        vsub = vsub.join(mode.rename("_mode"), on=dcols)
        minority = int((vsub[x] != vsub["_mode"]).sum())
        ex = [f"{dict(zip(dcols, k if isinstance(k, tuple) else (k,)))}" for k in viol.index[:3]]
        return (len(viol), len(nun), minority, ex)

    for d in dets:
        for x in targets:
            if x == d:
                continue
            r = test([d], x)
            if r == "full":
                full_fd.add((d, x))
            elif r:
                nv, ng, minority, ex = r
                add("WARN", 2, "row contradiction: breaks a near functional dependency",
                    t.name, f"{d} -> {x}", minority, n,
                    f"{x} is single-valued per {d} in {1 - nv/ng:.2%} of {ng} groups; "
                    f"{nv} groups have conflicting values", fmt_examples(ex, 3))
    pair_cols = [c for c in dets if t.cols[c]["n_distinct"] <= 100
                 or t.cols[c]["type"] == "date"]
    for d1, d2 in itertools.combinations(pair_cols, 2):
        if cdf[[d1, d2]].drop_duplicates().shape[0] > 0.5 * n:
            continue
        for x in targets:
            if x in (d1, d2) or (d1, x) in full_fd or (d2, x) in full_fd:
                continue
            if t.cols[x]["n_distinct"] > 5000:
                continue
            r = test([d1, d2], x)
            if r and r != "full":
                nv, ng, minority, ex = r
                add("WARN", 2, "row contradiction: breaks a near functional dependency",
                    t.name, f"({d1}, {d2}) -> {x}", minority, n,
                    f"{x} is single-valued per ({d1}, {d2}) in {1 - nv/ng:.2%} of {ng} "
                    f"groups; {nv} groups conflict", fmt_examples(ex, 3))
            elif r == "full" and t.cols[x]["type"] == "number":
                add("INFO", 2, "row contradiction: discovered dependency holds",
                    t.name, f"({d1}, {d2}) -> {x}", 0, n,
                    f"every ({d1}, {d2}) pair has exactly one {x}")


# --------------------------------------------------------------------------
# Group 3: referential integrity
# --------------------------------------------------------------------------
def fk_checks(t: Table, tables, date_dim):
    for c, (dname, dcol) in t.fks.items():
        D = tables[dname]
        pk_norm = set(norm_key(D.df[dcol]))
        pk_raw = set(D.df[dcol])
        fk_raw = t.df[c]
        fk_norm = norm_key(fk_raw)
        filled = t.cols[c]["nonnull"]
        orphan = filled & ~fk_norm.isin(pk_norm)
        if orphan.any():
            vals = fk_norm[orphan]
            add("ERROR", 3, "foreign key: value has no matching primary key",
                t.name, c, int(orphan.sum()), t.n,
                f"{vals.nunique()} distinct {c} values missing from {dname}.{dcol} "
                f"(range {key_range(vals)}); rows per missing key: median "
                f"{vals.value_counts().median():g}",
                fmt_examples(vals.drop_duplicates().sort_values(key=lambda s: pd.to_numeric(s, errors='coerce'))),
                involves=[t.name, dname])
        else:
            add("INFO", 3, "foreign key: all values resolve", t.name, c, 0, t.n,
                f"-> {dname}.{dcol}", involves=[t.name, dname])
        textfail = filled & ~orphan & ~fk_raw.isin(pk_raw)
        if textfail.any():
            add("ERROR", 3, "foreign key: matches only after type normalisation",
                t.name, c, int(textfail.sum()), t.n,
                f"raw text differs from {dname}.{dcol} (e.g. '45.0' vs '45'); "
                "a join on the raw columns silently loses these rows",
                fmt_examples(fk_raw[textfail].drop_duplicates()), involves=[t.name, dname])
    # unresolved *_id columns
    for c, m in t.cols.items():
        if m["type"] == "key" and c != t.pk and c not in t.fks:
            add("INFO", 3, "foreign key: no table has this key as its primary key",
                t.name, c, 0, t.n, "cannot verify")
    # date columns of fact tables vs the calendar dimension
    if date_dim:
        dname, dcol = date_dim
        cal = set(tables[dname].cols[dcol]["parsed"].dropna().dt.strftime("%Y-%m-%d"))
        for c in t.date_fks:
            p = t.cols[c]["parsed"]
            ds = p.dt.strftime("%Y-%m-%d")
            miss = p.notna() & ~ds.isin(cal)
            if miss.any():
                add("ERROR", 3, "foreign key: date not in calendar dimension",
                    t.name, c, int(miss.sum()), t.n, f"calendar {dname}.{dcol} "
                    f"covers {min(cal)}..{max(cal)}",
                    fmt_examples(t.df.loc[miss, c].drop_duplicates()),
                    involves=[t.name, dname])
            else:
                add("INFO", 3, "foreign key: all dates resolve to the calendar",
                    t.name, c, 0, t.n, f"-> {dname}.{dcol}", involves=[t.name, dname])


# --------------------------------------------------------------------------
# Group 4: cross-table business rules
# --------------------------------------------------------------------------
def lookup(D: Table, key_col, val_col):
    k = norm_key(D.df[key_col]) if D.cols[key_col]["type"] != "date" else \
        D.cols[key_col]["parsed"].dt.strftime("%Y-%m-%d")
    v = canon_cache[D.name][val_col]
    s = pd.Series(v.values, index=k.values)
    return s[~s.index.duplicated()]


class _CanonCache(dict):
    """Normalised copies are built only for tables a check actually touches."""
    tables: dict = {}

    def __missing__(self, key):
        val = canon(self.tables[key])
        self[key] = val
        return val


canon_cache = _CanonCache()


def join_paths(t: Table, tables, date_dim):
    """(fk column in t, dimension table, dimension key) incl. date -> calendar."""
    paths = [(c, tables[d], dc) for c, (d, dc) in t.fks.items()]
    if date_dim:
        for c in t.date_fks:
            paths.append((c, tables[date_dim[0]], date_dim[1]))
    return paths


def attribute_agreement(t: Table, tables, date_dim):
    """Fact attributes that duplicate a dimension attribute must agree."""
    ct = canon_cache[t.name]
    for c, D, dk in join_paths(t, tables, date_dim):
        keys = norm_key(t.df[c]) if t.cols[c]["type"] != "date" else \
            t.cols[c]["parsed"].dt.strftime("%Y-%m-%d")
        for x, mx in t.cols.items():
            if x in (c, t.pk) or mx["type"] not in ("category", "key", "boolean", "code", "integer"):
                continue
            for y, my in D.cols.items():
                if y == dk:
                    continue
                same_name = x.lower() == y.lower()
                jacc = 0
                if not same_name and mx["type"] == "category" and my["type"] == "category":
                    a, b = {u.casefold() for u in mx["uniq"]}, {u.casefold() for u in my["uniq"]}
                    jacc = len(a & b) / max(len(a | b), 1)
                if not (same_name or jacc >= 0.6):
                    continue
                ref = keys.map(lookup(D, dk, y))
                both = ref.notna() & ref.ne("") & ct[x].ne("")
                mism = both & (ref != ct[x])
                if not both.any():
                    continue
                rate = mism.sum() / both.sum()
                label = f"{x} vs {D.name}.{y} (via {c})"
                if mism.any() and rate <= 0.5:
                    ex = [f"{t.df.at[i, c]}: {x}={t.df.at[i, x]} / {y}={ref.at[i]}"
                          for i in mism[mism].index[:5]]
                    add("WARN", 4, "fact disagrees with its dimension", t.name, label,
                        int(mism.sum()), t.n,
                        f"{rate:.2%} of joined rows disagree "
                        f"({t.df.loc[mism, c].nunique()} distinct {c})",
                        fmt_examples(ex), involves=[t.name, D.name])
                elif mism.any():
                    add("INFO", 4, "columns look alike but mostly disagree", t.name, label,
                        int(mism.sum()), t.n, f"{rate:.2%} disagree - probably different meanings",
                        involves=[t.name, D.name])
                else:
                    add("INFO", 4, "fact agrees with its dimension", t.name, label, 0, t.n,
                        "", involves=[t.name, D.name])


def date_order_vs_dimension(t: Table, tables, date_dim):
    """Fact dated before a start-like date of the entity it references."""
    for c, (dname, dk) in t.fks.items():
        D = tables[dname]
        if date_dim and dname == date_dim[0]:
            continue
        keys = norm_key(t.df[c])
        for y, my in D.cols.items():
            if my["type"] != "date":
                continue
            dmap = pd.Series(my["parsed"].values, index=norm_key(D.df[dk]).values)
            dmap = dmap[~dmap.index.duplicated()]
            ref = keys.map(dmap)
            for x, mx in t.cols.items():
                if mx["type"] != "date":
                    continue
                fd = mx["parsed"]
                cmp_ref, grain = ref, "day"
                if (fd.dt.day == 1)[fd.notna()].mean() >= 0.95:   # monthly fact
                    cmp_ref, grain = ref.dt.to_period("M").dt.to_timestamp(), "month"
                before = fd.notna() & cmp_ref.notna() & (fd < cmp_ref)
                if before.any():
                    ex = [f"{c}={t.df.at[i, c]}: {x}={t.df.at[i, x]} < {y}={ref.at[i].date()}"
                          for i in before[before].index[:5]]
                    add("WARN", 4, "fact dated before the related entity's date",
                        t.name, f"{x} < {dname}.{y}", int(before.sum()), t.n,
                        f"{t.df.loc[before, c].nunique()} distinct {c}; compared at {grain} grain",
                        fmt_examples(ex), involves=[t.name, dname])


def calendar_flag_checks(t: Table, tables, date_dim):
    """Event dates on days the calendar marks as closed."""
    if not date_dim:
        return
    D = tables[date_dim[0]]
    groupers = [g for g, m in t.cols.items() if m["type"] == "category"
                and 2 <= m["n_distinct"] <= 20 and m["n_nonnull"] >= 0.8 * t.n]
    for c in t.date_fks:
        p = t.cols[c]["parsed"]
        if (p.dt.day == 1)[p.notna()].mean() >= 0.95:
            continue   # 1st-of-month period stamps are not event dates
        ds = p.dt.strftime("%Y-%m-%d")
        for y, my in D.cols.items():
            if my["type"] != "boolean":
                continue
            share_true = (my["parsed"] == 1).mean()
            if share_true < 0.6:
                continue
            flag = ds.map(lookup(D, date_dim[1], y))
            off = flag.isin(["0.0", "0"])
            if not off.any():
                continue
            cal_off, fact_off = 1 - share_true, off[p.notna()].mean()
            uniform = fact_off >= 0.8 * cal_off
            detail = (f"{fact_off:.1%} of rows fall on days where {y} is false "
                      f"({cal_off:.1%} of calendar days are)")
            if uniform:
                detail += "; dates are spread as if the flag did not exist"
            for g in groupers[:1]:
                br = off.groupby(t.cols[g]["stripped"]).mean().sort_values(ascending=False)
                detail += f"; by {g}: " + ", ".join(f"{k} {v:.1%}" for k, v in br.items())
            add("WARN" if uniform else "INFO", 4,
                "plausibility: events dated on days the calendar marks as closed",
                t.name, f"{c} vs {D.name}.{y}", int(off.sum()), t.n, detail,
                fmt_examples(t.df.loc[off, c].drop_duplicates()), involves=[t.name, D.name])


def unreferenced_members(dims, tables):
    for D in dims:
        if not D.pk:
            continue
        refs = [(t, c) for t in tables.values() for c, (d, _) in t.fks.items() if d == D.name]
        if not refs:
            continue
        used = set()
        for t, c in refs:
            used |= set(norm_key(t.df[c]))
        pk = norm_key(D.df[D.pk])
        unused = ~pk.isin(used)
        if unused.any():
            add("INFO", 4, "dimension members never referenced", D.name, D.pk,
                int(unused.sum()), D.n,
                "not used by " + ", ".join(sorted({t.name for t, _ in refs})),
                fmt_examples(pk[unused].head(5)),
                involves=[D.name] + [t.name for t, _ in refs])


def monthly_key(t: Table):
    dcols = [c for c, m in t.cols.items() if m["type"] == "date"]
    if len(dcols) != 1:
        return None, None
    p = t.cols[dcols[0]]["parsed"]
    return dcols[0], p.dt.to_period("M").astype(str)


def fact_vs_fact(facts, tables, targets):
    info = {}
    for F in facts:
        dc, mk = monthly_key(F)
        if dc is None:
            continue
        p = F.cols[dc]["parsed"]
        info[F.name] = dict(dc=dc, mk=mk, periodic=(p.dt.day == 1)[p.notna()].mean() >= 0.95)
    # an event table is compared with ONE periodic table per FK (the largest),
    # so a single root cause is not reported twice
    ref_periodic = {}
    for E in facts:
        if E.name not in info or info[E.name]["periodic"]:
            continue
        for fk in E.fks:
            cands = [P for P in facts if P.name in info and info[P.name]["periodic"] and fk in P.fks]
            if cands:
                ref_periodic[(E.name, fk)] = max(cands, key=lambda P: P.n).name
    for F1, F2 in itertools.combinations(facts, 2):
        if not ({F1.name, F2.name} & targets) or F1.name not in info or F2.name not in info:
            continue
        shared = [c for c in F1.fks if c in F2.fks]
        if not shared:
            continue
        fk = max(shared, key=lambda c: F1.cols[c]["n_distinct"])
        d1, m1, periodic1 = info[F1.name]["dc"], info[F1.name]["mk"], info[F1.name]["periodic"]
        d2, m2, periodic2 = info[F2.name]["dc"], info[F2.name]["mk"], info[F2.name]["periodic"]
        k1 = norm_key(F1.df[fk]) + "|" + m1
        k2 = norm_key(F2.df[fk]) + "|" + m2
        inv = [F1.name, F2.name]
        if periodic1 and periodic2:
            s1, s2 = set(k1), set(k2)
            for A, kA, B, sB in ((F1, k1, F2, s2), (F2, k2, F1, s1)):
                only = kA[~kA.isin(sB)]
                if len(only):
                    months = only.str.split("|").str[1].str[5:7].value_counts().sort_index()
                    add("WARN", 4, "periodic facts do not line up", A.name,
                        f"({fk}, month) vs {B.name}", len(only), A.n,
                        f"{len(only)} {A.name} rows have no {B.name} row for the same {fk} and month "
                        f"({only.str.split('|').str[0].nunique()} {fk}s; spread over calendar months "
                        f"{months.min()}-{months.max()} rows each)",
                        fmt_examples(only.drop_duplicates()), involves=inv)
            u1, u2 = ~k1.duplicated(keep=False), ~k2.duplicated(keep=False)
            if u1.mean() < 0.9 or u2.mean() < 0.9:
                continue
            n1 = [c for c, m in F1.cols.items() if m["type"] == "number"]
            n2 = [c for c, m in F2.cols.items() if m["type"] == "number"]
            A = pd.DataFrame({c: F1.cols[c]["parsed"] for c in n1})[u1.values]
            A.index = k1[u1].values
            B = pd.DataFrame({c: F2.cols[c]["parsed"] for c in n2})[u2.values]
            B.index = k2[u2].values
            J = A.join(B, how="inner", lsuffix="__1", rsuffix="__2")
            if len(J) < 30:
                continue
            for x in n1:
                for y in n2:
                    xa = J[x + "__1"] if x in n2 else J[x]
                    yb = J[y + "__2"] if y in n1 else J[y]
                    ok = xa.notna() & yb.notna()
                    eq = np.isclose(xa[ok], yb[ok], rtol=1e-9, atol=0.005)
                    if eq.mean() >= 0.8:
                        bad = (~eq).sum()
                        if bad:
                            wrong = xa[ok][~eq]
                            ex = [f"{k}: {x}={xa[k]:.2f} vs {y}={yb[k]:.2f}" for k in wrong.index[:5]]
                            add("ERROR", 4, "facts disagree with each other", F1.name,
                                f"{x} vs {F2.name}.{y}", int(bad), F1.n,
                                f"same {fk} and month should carry the same value "
                                f"(equal on {eq.mean():.2%} of {ok.sum()} matched rows)",
                                fmt_examples(ex), involves=inv)
                        else:
                            add("INFO", 4, "facts agree with each other", F1.name,
                                f"{x} vs {F2.name}.{y}", 0, F1.n,
                                f"equal on all {ok.sum()} matched ({fk}, month) rows", involves=inv)
        elif periodic1 != periodic2:
            P, E = (F1, F2) if periodic1 else (F2, F1)
            if ref_periodic.get((E.name, fk)) != P.name:
                continue
            pcol, ecol = info[P.name]["dc"], info[E.name]["dc"]
            span = pd.DataFrame({"k": norm_key(P.df[fk]), "d": P.cols[pcol]["parsed"]}) \
                .groupby("k")["d"].agg(["min", "max"])
            ek = norm_key(E.df[fk])
            ed = E.cols[ecol]["parsed"]
            lo = ek.map(span["min"])
            hi = ek.map(span["max"]) + pd.offsets.MonthEnd(0)
            before = lo.notna() & ed.notna() & (ed < lo)
            after = lo.notna() & ed.notna() & (ed > hi)
            outside = before | after
            nospan = E.cols[fk]["nonnull"] & lo.isna()
            if outside.any():
                notes = flag_association(tables[E.fks[fk][0]], set(ek[outside]), span["max"])
                add("WARN", 4, "event outside the entity's periodic history", E.name,
                    f"{ecol} vs {P.name}.{pcol}", int(outside.sum()), E.n,
                    f"{int(before.sum())} rows before the first and {int(after.sum())} after the last "
                    f"{P.name} row for the same {fk} ({ek[outside].nunique()} {fk}s)"
                    + ("; " + "; ".join(notes) if notes else ""),
                    fmt_examples([f"{fk}={ek[i]} {ecol}={E.df.at[i, ecol]}" for i in outside[outside].index[:5]]),
                    involves=inv + [E.fks[fk][0]])
            if nospan.any():
                add("WARN", 4, "event for an entity with no periodic history", E.name,
                    f"{fk} vs {P.name}", int(nospan.sum()), E.n,
                    f"{ek[nospan].nunique()} {fk} values appear in {E.name} but never in {P.name}",
                    fmt_examples(ek[nospan].drop_duplicates()), involves=inv)


def flag_association(D: Table, affected: set, span_max: pd.Series):
    """Explain affected entities with a boolean attribute of their dimension."""
    notes = []
    if not D.pk:
        return notes
    dk = norm_key(D.df[D.pk])
    last = span_max.max()
    early = span_max < last
    for y, my in D.cols.items():
        if my["type"] != "boolean":
            continue
        yv = pd.Series(my["parsed"].values, index=dk.values)
        yv = yv[~yv.index.duplicated()]
        a = yv.reindex(list(affected)).dropna()
        if len(a):
            top = a.value_counts(normalize=True)
            if top.iloc[0] >= 0.99:
                notes.append(f"{top.iloc[0]:.0%} of affected entities have {D.name}.{y}="
                             f"{'True' if top.index[0] == 1 else 'False'}")
        ee = yv.reindex(span_max.index)
        ok = ee.notna()
        if ok.any() and early[ok].any():
            for v in (0, 1):
                if (early[ok] == (ee[ok] == v)).mean() >= 0.999:
                    notes.append(f"history ends before {last:%Y-%m} for exactly the "
                                 f"{int(early[ok].sum())} entities with {y}={'True' if v else 'False'}")
    return notes


def _tokens(text):
    return {singular(w) for w in re.findall(r"[a-z]+", str(text).lower())} - \
        {"fact", "dim", "tbl", "raw", "stg"}


def cross_measure_checks(facts, targets):
    """A category in one fact table that names another fact table (e.g. a
    'Fee' transaction vs a fees table) records the same money twice."""
    def money_col(T):
        c = [x for x, m in T.cols.items() if m["type"] == "number"
             and re.search(r"amount|value", x.lower())]
        return c[0] if c else None
    for E in facts:
        ae, (de, _) = money_col(E), monthly_key(E)
        if not ae or not de:
            continue
        cats = [g for g, m in E.cols.items() if m["type"] == "category" and 2 <= m["n_distinct"] <= 20]
        for F in facts:
            if F is E or not ({E.name, F.name} & targets):
                continue
            af, (df_, _) = money_col(F), monthly_key(F)
            if not af or not df_:
                continue
            ftoks = _tokens(F.name)
            shared = [c for c in E.fks if c in F.fks]
            fk = max(shared, key=lambda c: E.cols[c]["n_distinct"]) if shared else None
            fy = F.cols[df_]["parsed"].dt.year
            yf = F.cols[af]["parsed"].groupby(fy).sum()
            for g in cats:
                for val in sorted(E.cols[g]["uniq"]):
                    vt = _tokens(val)
                    if not (vt & ftoks):
                        continue
                    sub = E.cols[g]["stripped"].eq(val)
                    ey = E.cols[de]["parsed"][sub].dt.year
                    ye = E.cols[ae]["parsed"][sub].groupby(ey).sum()
                    years = sorted(set(ye.index) | set(yf.index))
                    off = [y for y in years if not yf.get(y) or not (0.95 <= ye.get(y, 0) / yf[y] <= 1.05)]
                    detail = (f"'{val}' rows of {E.name}.{ae} vs all of {F.name}.{af}, by year: "
                              + ", ".join(f"{y}: {ye.get(y, 0):,.0f} vs {yf.get(y, 0):,.0f}" for y in years))
                    extra = vt - ftoks
                    for gf, mf in F.cols.items():
                        if mf["type"] != "category" or not extra:
                            continue
                        hitmap = {u: bool(_tokens(u) & extra) for u in mf["uniq"]}
                        hit = mf["stripped"].map(hitmap).fillna(False).astype(bool)
                        if hit.any() and not hit.all():
                            ys = F.cols[af]["parsed"][hit].groupby(fy[hit]).sum()
                            detail += (f"; vs only {F.name} rows where {gf} matches {sorted(extra)}: "
                                       + ", ".join(f"{y}: {ye.get(y, 0):,.0f} vs {ys.get(y, 0):,.0f}"
                                                   for y in years))
                    if fk:
                        ke = norm_key(E.df[fk])[sub] + "|" + ey.astype(str)
                        kf = norm_key(F.df[fk]) + "|" + fy.astype(str)
                        j = pd.concat([E.cols[ae]["parsed"][sub].groupby(ke.values).sum(),
                                       F.cols[af]["parsed"].groupby(kf.values).sum()],
                                      axis=1, join="inner").dropna()
                        if len(j):
                            agree = np.isclose(j.iloc[:, 0], j.iloc[:, 1], rtol=0.01).mean()
                            detail += f"; per {fk}-year totals agree within 1% for {agree:.1%} of {len(j)} pairs"
                    if off:
                        add("WARN", 4, "facts disagree: same money recorded in two tables",
                            E.name, f"{g}='{val}' vs {F.name}.{af}", int(sub.sum()), E.n,
                            detail + "; pick one table as the source of truth",
                            involves=[E.name, F.name])
                    else:
                        add("INFO", 4, "facts agree: same money recorded in two tables",
                            E.name, f"{g}='{val}' vs {F.name}.{af}", 0, E.n, detail,
                            involves=[E.name, F.name])


def inferable_blanks(dims, tables, targets):
    """Blank dimension values that a fact attribute pins down uniquely."""
    for D in dims:
        if not D.pk:
            continue
        dk = norm_key(D.df[D.pk])
        refs = [(F, fk) for F in tables.values() for fk, (d, _) in F.fks.items() if d == D.name]
        for y, my in D.cols.items():
            if my["type"] != "category" or y == D.pk or my["n_nonnull"] == D.n:
                continue
            if not ({D.name} | {F.name for F, _ in refs}) & targets:
                continue
            yv = pd.Series(my["stripped"].values, index=dk.values)
            yv = yv[~yv.index.duplicated()]
            blank_keys = set(dk[~my["nonnull"]])
            done = False
            for F, fk in refs:
                if done:
                    break
                ent = norm_key(F.df[fk])
                for x, mx in F.cols.items():
                    if x in (fk, F.pk) or mx["type"] not in ("category", "key", "code", "boolean"):
                        continue
                    per = pd.DataFrame({"e": ent.values, "x": canon_cache[F.name][x].values}).drop_duplicates()
                    if per["e"].duplicated().mean() > 0.01:
                        continue   # x is not a fixed attribute of the entity
                    per = per.drop_duplicates("e").set_index("e")["x"]
                    known = per[per.index.isin(yv.index[yv.ne("")])]
                    pairs = pd.DataFrame({"x": known.values, "y": yv.reindex(known.index).values})
                    xy = pairs.groupby("x")["y"].agg(lambda s: sorted(set(s)))
                    size = pairs.groupby("x").size()
                    bl = per[per.index.isin(blank_keys)]
                    ok = bl[bl.map(lambda v: v in xy.index and len(xy[v]) == 1 and size[v] >= 20)]
                    if len(ok) == 0:
                        continue
                    mapping = {v: xy[v][0] for v in sorted(set(ok))}
                    rule = "; ".join(f"{x}={v} is used only by {y}='{w}' ({size[v]} entities)"
                                     for v, w in mapping.items())
                    add("INFO", 4, "blank dimension value can be inferred from a fact",
                        D.name, f"{y} via {F.name}.{x}", len(ok), D.n,
                        f"{len(ok)} of {len(blank_keys)} blank {y} values: {rule}. "
                        f"{len(bl) - len(ok)} blanks are not inferable and "
                        f"{len(blank_keys - set(per.index))} never appear in {F.name}",
                        fmt_examples(sorted(ok.index, key=lambda k: (len(k), k))),
                        involves=[D.name, F.name])
                    done = True
                    break


def rate_vs_level(t: Table):
    """A rate column that is just the % change of a balance column (e.g. a return
    computed from AUM) silently counts deposits and withdrawals as performance."""
    ent, dc = entity_and_date(t)
    if not ent or not dc:
        return
    d = t.cols[dc]["parsed"]
    okd = d.notna()
    if okd.sum() < 100 or (d[okd].dt.day == 1).mean() < 0.95:
        return
    nums = [c for c, m in t.cols.items() if m["type"] == "number"]
    P = {c: t.cols[c]["parsed"][okd] for c in nums}
    levels = [c for c in nums if P[c].min() >= 0 and P[c].median() > 100]
    rates = [c for c in nums if c not in levels and P[c].abs().median() < 1]
    if not levels or not rates:
        return
    e = norm_key(t.df[ent])[okd].values
    per = pd.PeriodIndex(d[okd].dt.to_period("M"))
    bases = {"year-to-date vs the prior December":
             pd.PeriodIndex((d[okd].dt.year - 1).astype(str) + "-12", freq="M"),
             "month-over-month": per - 1}
    for L in levels:
        lv = pd.Series(P[L].values, index=pd.MultiIndex.from_arrays([e, per]))
        lv = lv[~lv.index.duplicated()]
        for R in rates:
            r = P[R]
            for basis, bp in bases.items():
                base = lv.reindex(pd.MultiIndex.from_arrays([e, bp])).values
                with np.errstate(all="ignore"):
                    est = P[L].values / base - 1
                good = np.isfinite(est) & r.notna().values
                if good.sum() < 100:
                    continue
                rv = r.values[good]
                match = np.abs(est[good] - rv) <= 1e-4 + 1e-4 * np.abs(rv)
                if match.mean() < RULE_HOLD_SHARE:
                    continue
                linked = sorted({x for f in FORMULAS if f["table"] == t.name
                                 and R in (f["target"],) + tuple(f["inputs"])
                                 for x in (f["target"],) + tuple(f["inputs"])} - {R})
                i = np.flatnonzero(good)[np.argmax(np.abs(rv))]
                row = r.index[i]
                ex = (f"{ent}={t.df.at[row, ent]} {dc}={t.df.at[row, dc]}: {L} {P[L][row]:,.2f} / "
                      f"base {base[i]:,.2f} - 1 = {est[i]:.4f}; {R}={t.df.at[row, R]}")
                add("WARN", 2, "accuracy: rate is the simple % change of a balance (includes cash flows)",
                    t.name, f"{R} vs {L}", int(good.sum()), t.n,
                    f"{R} = {L} / {L}[{basis}] - 1 on {match.mean():.2%} of {int(good.sum())} rows "
                    f"that have a base; deposits and withdrawals therefore show up as gains and "
                    f"losses, so it is balance growth, not investment performance"
                    + (f"; tied by formula to {', '.join(linked)}, which inherit it" if linked else ""),
                    ex)
                break


def entity_and_date(t: Table):
    ent = max(t.fks, key=lambda c: t.cols[c]["n_distinct"]) if t.fks else None
    dcols = [c for c, m in t.cols.items() if m["type"] == "date"]
    return ent, (dcols[0] if len(dcols) == 1 else None)


def sentinel_kind(t: Table, c, p, val):
    """Classify a repeated round value as a minimum floor or a placeholder."""
    is_min = bool(np.isclose(val, p.min()))
    ent, dc = entity_and_date(t)
    if ent and dc:
        d = pd.DataFrame({"e": norm_key(t.df[ent]), "d": t.cols[dc]["parsed"], "v": p}) \
            .dropna().sort_values(["e", "d"])
        first = d.groupby("e").cumcount() == 0
        hit = np.isclose(d["v"], val)
        nxt = d.groupby("e")["v"].shift(-1)[hit].dropna()
        never_first = not (hit & first).any()
        builds = (nxt >= val - 1e-9).mean() if len(nxt) else 0
        if is_min and never_first and builds >= 0.95:
            return "minimum floor", (f"it is the column minimum, never an entity's first value, and "
                                     f"{builds:.0%} of the following values are >= it - looks like a "
                                     f"balance floor, not a missing value")
        if not never_first:
            return "placeholder", "it appears as an entity's first value - possibly a default for a missing number"
    if is_min:
        return "minimum floor", "it is the column minimum"
    return "placeholder", "isolated repeated value - possibly a stand-in for a missing number"


def key_range(vals: pd.Series) -> str:
    num = pd.to_numeric(vals, errors="coerce")
    if num.notna().all():
        return f"{num.min():g}..{num.max():g}"
    return f"{vals.min()}..{vals.max()}"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tables", nargs="*", help="table names or CSV paths (default: all)")
    ap.add_argument("--data-dir", default=str(BASE_DIR), help="folder with the CSVs")
    ap.add_argument("--out-dir", default=str(REPORT_DIR))
    args = ap.parse_args()

    t0 = time.time()
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)

    tables: dict[str, Table] = {}
    paths = sorted(data_dir.glob("*.csv"))
    for p in paths:
        name = re.sub(r"\s*\(\d+\)$", "", p.stem).strip()
        if name != p.stem:
            add("INFO", 0, "file: copy-style filename", name, "", 0, 0,
                f"file is named '{p.name}'; treated as table '{name}'")
        if name in tables:
            add("WARN", 0, "file: two files map to the same table", name, "", 0, 0,
                f"'{tables[name].path.name}' and '{p.name}' - keeping the first")
            continue
        tables[name] = Table(name, p, read_csv_as_text(p))
    for extra in args.tables:
        ep = Path(extra)
        if ep.suffix.lower() == ".csv" and ep.exists():
            name = re.sub(r"\s*\(\d+\)$", "", ep.stem).strip()
            tables[name] = Table(name, ep, read_csv_as_text(ep))
    if not tables:
        raise SystemExit(f"no CSV files found in {data_dir}")

    targets = set()
    for a in args.tables:
        name = re.sub(r"\s*\(\d+\)$", "", Path(a).stem).strip()
        if name not in tables:
            raise SystemExit(f"unknown table '{a}'. Available: {', '.join(tables)}")
        targets.add(name)
    targets = targets or set(tables)

    print(f"Loaded {len(tables)} tables as text in {time.time()-t0:.1f}s")
    date_dim = build_model(tables)
    canon_cache.tables = tables
    REFS.clear()
    for t in tables.values():
        for c, (d, _) in t.fks.items():
            REFS.setdefault(d, set()).update(norm_key(t.df[c]))
    for t in tables.values():
        add("INFO", 0, "file: inferred table model", t.name, t.pk or "", 0, t.n,
            f"role={t.role}; rows={t.n}; cols={len(t.df.columns)}; PK={t.pk}; FKs=" +
            (", ".join(f"{c}->{d}" for c, (d, _) in t.fks.items()) or "none") +
            (f"; dates->{date_dim[0]}: {', '.join(t.date_fks)}" if t.date_fks else ""))
    if date_dim:
        p = tables[date_dim[0]].cols[date_dim[1]]["parsed"]
        as_of = p.max()
    else:
        as_of = pd.Timestamp.today().normalize()

    profile = []
    for name in sorted(targets):
        t = tables[name]
        ts = time.time()
        profile += profile_rows(t)
        column_checks(t, as_of)
        cdf = canon_cache[name]
        duplicate_checks(t, cdf, REFS.get(name))
        date_part_checks(t)
        arithmetic_checks(t, rng)
        rate_vs_level(t)
        conditional_checks(t)
        fd_checks(t, cdf)
        fk_checks(t, tables, date_dim)
        attribute_agreement(t, tables, date_dim)
        date_order_vs_dimension(t, tables, date_dim)
        calendar_flag_checks(t, tables, date_dim)
        print(f"  {name:<28} {t.n:>8,} rows  {len(t.df.columns):>3} cols  "
              f"role={t.role:<10} {time.time()-ts:5.1f}s")
    dims = [t for t in tables.values() if t.role == "dimension"]
    facts = [t for t in tables.values() if t.role == "fact"]
    ts = time.time()
    unreferenced_members([d for d in dims if d.name in targets], tables)
    fact_vs_fact(facts, tables, targets)
    cross_measure_checks(facts, targets)
    inferable_blanks(dims, tables, targets)
    print(f"  cross-table checks{'':<13}{time.time()-ts:5.1f}s")

    # ---- write reports
    prof = pd.DataFrame(profile)
    prof.to_csv(out_dir / "profile_raw.csv", index=False)

    rows = [f for f in FINDINGS if f["_involves"] & targets]
    dq = pd.DataFrame(rows).drop(columns="_involves")
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    dq["_o"] = dq["severity"].map(order)
    dq = dq.sort_values(["_o", "group", "table", "check", "column"]).drop(columns="_o")
    dq.insert(0, "finding_id", [f"DQ{i:04d}" for i in range(1, len(dq) + 1)])
    dq.to_csv(out_dir / "dq_summary_raw.csv", index=False)

    print(f"\nWrote {out_dir / 'profile_raw.csv'} ({len(prof)} columns profiled)")
    print(f"Wrote {out_dir / 'dq_summary_raw.csv'} ({len(dq)} findings)")
    summary = dq.pivot_table(index="group", columns="severity", values="finding_id",
                             aggfunc="count", fill_value=0)
    print(summary.reindex(columns=[c for c in ["ERROR", "WARN", "INFO"] if c in summary]).to_string())
    print(f"Done in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
