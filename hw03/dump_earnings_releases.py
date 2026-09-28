"""
Debug helper for hw03_earnings.py (not part of the assignment).

Downloads the same Item 2.02 press releases the pipeline uses for one company
and saves each one's plain text to hw03/earnings_releases/ so the extraction
regexes can be checked against the real wording.

Usage:  python dump_earnings_releases.py          (defaults to WMT)
        python dump_earnings_releases.py AAPL
"""
import sys
from pathlib import Path

import hw03_earnings as h

TICKER = (sys.argv[1] if len(sys.argv) > 1 else "WMT").upper()
OUT = Path(__file__).resolve().parent / "earnings_releases"
OUT.mkdir(exist_ok=True)

co = next(c for c in h.COMPANIES if c["ticker"] == TICKER)
for f in h.get_earnings_filings(co["cik"]):
    idx_url = h.filing_index_url(co["cik"], f["accession"])
    pr_url = h.find_press_release_url(idx_url, f["primary_doc"])
    name = f"{TICKER}_{f['filing_date']}.txt"
    if not pr_url:
        print("no press release exhibit for", f["filing_date"])
        continue
    text = h.html_to_text(h.get(pr_url).text)
    (OUT / name).write_text(f"SOURCE: {pr_url}\n\n{text}", encoding="utf-8")
    print("saved", name, "<-", pr_url)
print(f"\nDone - files are in {OUT}")
