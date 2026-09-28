"""
hw03_timeline.py  -  MIS3060 HW03: Corporate Events Timeline

Combines the two HW03 pipeline outputs:
  - hw03/earnings_history.csv   (8-K Item 2.02 earnings filings)
  - hw03/executive_events.csv   (8-K Item 5.02 executive events)

For every executive event it:
  1. Finds the nearest earnings filing for the same company (matched on ticker)
     and stores the absolute gap in days as `days_to_nearest_earnings`.
  2. Labels `event_timing`:
       'same week'        -> within 7 days (inclusive) of that earnings filing
       'before earnings'  -> event filed more than 7 days before it
       'after earnings'   -> event filed more than 7 days after it
       'no earnings data' -> company has no rows in earnings_history.csv
  3. Saves hw03/corporate_events_timeline.csv: every executive-event column,
     every earnings column (prefixed `earnings_`), plus the two new columns.
  4. Prints a per-company summary and a final before/after count.

Uses only the Python standard library - no pip installs needed.
Run from the repo root or from inside hw03 - paths resolve next to this script.
"""

import csv
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
EARNINGS_CSV = HERE / "earnings_history.csv"
EVENTS_CSV = HERE / "executive_events.csv"
OUTPUT_CSV = HERE / "corporate_events_timeline.csv"

SAME_WEEK_DAYS = 7
KEYS = ["company", "ticker", "cik"]  # identity columns shared by both tables
MISSING = "NO_EARNINGS_DATA"         # explicit marker, not a blank cell


def load(path):
    """Read a CSV as a list of dicts (all values stay text, so CIK zeros survive)."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def to_date(s):
    return date.fromisoformat(s.strip())


def classify(signed_days):
    if signed_days is None:
        return "no earnings data"
    if abs(signed_days) <= SAME_WEEK_DAYS:
        return "same week"
    return "before earnings" if signed_days < 0 else "after earnings"


def main():
    earn_cols, earnings = load(EARNINGS_CSV)
    event_cols, events = load(EVENTS_CSV)

    # Earnings columns (other than the shared identity columns) get a prefix
    # so both tables' columns can sit side by side in one row.
    earn_extra = [c for c in earn_cols if c not in KEYS]
    earn_out_cols = [f"earnings_{c}" for c in earn_extra]
    out_cols = event_cols + earn_out_cols + ["days_to_nearest_earnings", "event_timing"]

    # Group earnings filings by ticker.
    by_ticker = {}
    for e in earnings:
        by_ticker.setdefault(e["ticker"], []).append(e)

    rows = []
    for ev in events:
        ev_date = to_date(ev["filing_date"])
        row = dict(ev)
        candidates = by_ticker.get(ev["ticker"], [])
        if not candidates:
            signed = None
            for c in earn_out_cols:
                row[c] = MISSING
            row["days_to_nearest_earnings"] = MISSING
        else:
            # Nearest by absolute gap; ties go to the earlier earnings filing.
            best = min(
                candidates,
                key=lambda e: (abs((ev_date - to_date(e["filing_date"])).days),
                               to_date(e["filing_date"])),
            )
            signed = (ev_date - to_date(best["filing_date"])).days  # negative = before
            for c in earn_extra:
                row[f"earnings_{c}"] = best[c]
            row["days_to_nearest_earnings"] = abs(signed)
        row["event_timing"] = classify(signed)
        rows.append((row, signed))

    # ---- Save ----------------------------------------------------------------
    try:
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=out_cols)
            writer.writeheader()
            writer.writerows(r for r, _ in rows)
    except PermissionError:
        raise SystemExit(f"\nCould not write {OUTPUT_CSV.name} - it is probably open in Excel "
                         f"(Excel locks files it has open). Close it and run this script again.")
    print(f"Saved {len(rows)} rows -> {OUTPUT_CSV}\n")

    # ---- Per-company summary -------------------------------------------------
    print("=" * 78)
    print("EXECUTIVE EVENTS vs. NEAREST EARNINGS ANNOUNCEMENT")
    print("=" * 78)
    names = {}
    for r in events + earnings:
        names.setdefault(r["ticker"], r["company"])
    for t in names:
        print(f"\n{names[t]} ({t})")
        sub = sorted((x for x in rows if x[0]["ticker"] == t),
                     key=lambda x: x[0]["filing_date"])
        if not sub:
            print("  No executive events in the events table.")
            continue
        for r, s in sub:
            who = f"{r['event_type']:<11} {r['person_name']} ({r['title']})"
            print(f"  {r['filing_date']} | {who}")
            if s is None:
                print(f"             -> no earnings filings for {t} in earnings_history.csv")
                continue
            rel = "before" if s < 0 else "after" if s > 0 else "on the same day as"
            print(f"             -> {r['event_timing'].upper()}: {abs(s)} days {rel} "
                  f"earnings filed {r['earnings_filing_date']} ({r['earnings_period']})")

    # ---- Final count ---------------------------------------------------------
    counts = Counter(r["event_timing"] for r, _ in rows)
    print("\n" + "=" * 78)
    print("FINAL COUNT (all companies)")
    print("=" * 78)
    for label in ["before earnings", "after earnings", "same week", "no earnings data"]:
        print(f"  {label:<18} {counts.get(label, 0):>3}")
    print(f"  {'total events':<18} {len(rows):>3}")

    # Direction only (ignoring the 7-day window) for the strict before/after question.
    signed = [s for _, s in rows if s is not None]
    print(f"\n  Strict direction (same-week events split by side): "
          f"{sum(s < 0 for s in signed)} before, {sum(s > 0 for s in signed)} after, "
          f"{sum(s == 0 for s in signed)} same day")

    missing = sorted({e["ticker"] for e in events} - set(by_ticker))
    if missing:
        print(f"\n  NOTE: {', '.join(missing)} have executive events but no rows in "
              f"earnings_history.csv, so they could not be matched.")


if __name__ == "__main__":
    main()
