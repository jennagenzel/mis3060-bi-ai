"""
Debug helper for hw03_executives.py (not part of the assignment).

Downloads the same Item 5.02 filings the pipeline uses and saves the text of
each filing's Item 5.02 section to hw03/item502_sections/ so the extraction
rules can be checked against the real wording.
"""
from pathlib import Path

import hw03_executives as h

OUT = Path(__file__).resolve().parent / "item502_sections"
OUT.mkdir(exist_ok=True)

cutoff = h.twelve_months_ago()
for co in h.COMPANIES:
    for f in h.get_502_filings(co["cik"], cutoff):
        section = h.isolate_item_502(h.download_8k_text(co["cik"], f))
        name = f"{co['ticker']}_{f['filing_date']}_{f['accession']}.txt"
        (OUT / name).write_text(section, encoding="utf-8")
        print("saved", name)
print(f"\nDone - files are in {OUT}")
