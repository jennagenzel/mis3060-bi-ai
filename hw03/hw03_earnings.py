"""
hw03_earnings.py  -  MIS3060 HW03, Specification A: Earnings Pipeline

One run does the following:
  1. Sends the required SEC User-Agent header on every HTTP request.
  2. Pulls each company's filing history from the EDGAR submissions API and keeps
     8-K filings whose `items` field contains "2.02" (Results of Operations).
  3. Keeps the four most recent of those filings per company (one per quarter).
  4. Opens each filing's index page, finds the earnings press release exhibit
     (.htm, normally EX-99.1), downloads it and strips the HTML to plain text.
  5. Extracts revenue, diluted EPS and net income from the condensed financial
     statement tables in the release (exact GAAP figures, in millions), falling
     back to the narrative sentences only if a table row is not found; and the
     reporting period.
  6. Prints one line per filing as it is processed.
  7. Writes every row to hw03/earnings_history.csv.
  8. Writes "NOT_FOUND" for any field the regexes could not extract.

Run from the repo root (mis3060-bi-ai) or from inside hw03 - the CSV always
lands next to this script in the hw03 folder.
"""

import csv
import html
import re
import time
from datetime import datetime
from pathlib import Path

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # the script still works without bs4 (regex fallback)
    BeautifulSoup = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_AGENT = "MIS3060 Villanova jgenzel@villanova.edu"
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

# The five assigned companies.
# CIKs are zero-padded to 10 digits for the submissions API.
COMPANIES = [
    {"company": "Apple Inc.",            "ticker": "AAPL", "cik": "0000320193"},
    {"company": "Microsoft Corporation", "ticker": "MSFT", "cik": "0000789019"},
    {"company": "NVIDIA Corporation",    "ticker": "NVDA", "cik": "0001045810"},
    {"company": "JPMorgan Chase & Co.",  "ticker": "JPM",  "cik": "0000019617"},
    {"company": "Walmart Inc.",          "ticker": "WMT",  "cik": "0000104169"},
]

FILINGS_PER_COMPANY = 4
MIN_DAYS_BETWEEN_FILINGS = 45   # treats 8-Ks closer than this as the same quarter
REQUEST_PAUSE = 0.15            # SEC allows max 10 requests/second
NOT_FOUND = "NOT_FOUND"

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_CSV = SCRIPT_DIR / "earnings_history.csv"
CSV_COLUMNS = ["company", "ticker", "cik", "filing_date", "period",
               "revenue_reported", "eps_diluted", "net_income"]



# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------
def get(url, retries=3):
    """GET a URL with the SEC User-Agent, polite pacing and simple retries.
    This is the ONLY place the script calls requests.get(), and it passes
    headers=HEADERS explicitly on every call (including every retry)."""
    for attempt in range(1, retries + 1):
        time.sleep(REQUEST_PAUSE)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 503):       # rate limited - back off
                time.sleep(2 * attempt)
                continue
            resp.raise_for_status()
        except requests.RequestException as exc:
            if attempt == retries:
                raise
            print(f"    retry {attempt} for {url}: {exc}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"Failed to fetch {url}")


# ---------------------------------------------------------------------------
# Step 2 + 3: find the 8-K Item 2.02 filings
# ---------------------------------------------------------------------------
def get_earnings_filings(cik):
    """Return the most recent FILINGS_PER_COMPANY 8-K Item 2.02 filings,
    newest first, keeping at most one filing per quarter."""
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    recent = get(url).json()["filings"]["recent"]

    matches = []
    for i, form in enumerate(recent["form"]):
        items = recent["items"][i] or ""
        if form == "8-K" and "2.02" in items.split(","):
            matches.append({
                "accession": recent["accessionNumber"][i],
                "filing_date": recent["filingDate"][i],
                "primary_doc": recent["primaryDocument"][i],
            })

    # recent[] is already newest-first, but sort to be safe
    matches.sort(key=lambda f: f["filing_date"], reverse=True)

    # one per quarter: skip any 8-K filed within MIN_DAYS of one already kept
    # (companies sometimes file a second 2.02 8-K for the same quarter)
    selected = []
    for f in matches:
        d = datetime.strptime(f["filing_date"], "%Y-%m-%d")
        if all(abs((d - datetime.strptime(s["filing_date"], "%Y-%m-%d")).days)
               >= MIN_DAYS_BETWEEN_FILINGS for s in selected):
            selected.append(f)
        if len(selected) == FILINGS_PER_COMPANY:
            break
    return selected


# ---------------------------------------------------------------------------
# Step 4: locate and download the press-release exhibit
# ---------------------------------------------------------------------------
def filing_index_url(cik, accession):
    cik_int = str(int(cik))                     # archive paths use the unpadded CIK
    acc_nodash = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{accession}-index.htm"


def find_press_release_url(index_url, primary_doc):
    """Parse the filing index table and return the URL of the earnings
    press release (.htm). Preference: EX-99.1 > any EX-99.x > primary doc."""
    page = get(index_url).text
    base = index_url.rsplit("/", 1)[0] + "/"

    # Each document row: <tr> ... <a href="...file.htm">file.htm</a> ... <td>EX-99.1</td> ...
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I)
    exhibits = []   # (doc_type, url, description)
    for row in rows:
        href = re.search(r'href="([^"]+\.html?)"', row, flags=re.I)
        if not href:
            continue
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)]
        doc_type = next((c.upper() for c in cells if re.match(r"^(EX-|8-K)", c, re.I)), "")
        link = href.group(1)
        if link.startswith("/ix?doc="):         # inline-XBRL viewer link
            link = link[len("/ix?doc="):]
        url = "https://www.sec.gov" + link if link.startswith("/") else base + link
        exhibits.append((doc_type, url, " ".join(cells).lower()))

    for doc_type, url, _ in exhibits:
        if doc_type == "EX-99.1":
            return url
    for doc_type, url, desc in exhibits:
        if doc_type.startswith("EX-99") and ("press" in desc or "release" in desc or "result" in desc):
            return url
    for doc_type, url, _ in exhibits:
        if doc_type.startswith("EX-99"):
            return url
    return None   # no press-release exhibit in this filing


def html_to_text(raw_html):
    """Strip HTML tags/scripts and collapse whitespace into plain text."""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(" ")
    else:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw_html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("​", " ")
    text = re.sub(r"[‘’]", "'", text)
    text = re.sub(r"[“”]", '"', text)
    text = re.sub(r"[–—]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Step 5: regex extraction
# ---------------------------------------------------------------------------
NUM = r"\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?"
UNIT = r"(billion|million|B|M)\b"
NUM_NC = r"(?:\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"   # same as NUM, non-capturing

ORDINALS = {"first": "first", "second": "second", "third": "third", "fourth": "fourth",
            "1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth",
            "q1": "first", "q2": "second", "q3": "third", "q4": "fourth"}


def _fmt_money(value, unit):
    unit = {"b": "billion", "m": "million"}.get(unit.lower(), unit.lower())
    return f"{value} {unit}"



def _fmt_revenue(value, unit):
    """Revenue rounded to 1 decimal place, e.g. '94.9 billion'.
    Table figures (millions/thousands) of 1 billion or more are converted to
    billions first so the rounding stays meaningful: 76,693 million -> 76.7 billion."""
    unit = {"b": "billion", "m": "million"}.get(unit.lower(), unit.lower())
    num = float(str(value).replace(",", ""))
    to_billions = {"billion": 1, "million": 1e-3, "thousand": 1e-6}
    if unit in to_billions and num * to_billions[unit] >= 1:
        return f"{num * to_billions[unit]:,.1f} billion"
    return f"{num:,.1f} {unit}"

def _table_scale(text, pos=None):
    """Detect '(in millions...)' / '(in thousands...)' notes for table values.
    With pos, use the closest note ABOVE that position (releases can mix
    'Dollars in billions' and 'Amounts in millions' tables); otherwise the first."""
    notes = list(re.finditer(r"in (millions|thousands|billions)", text, flags=re.I))
    if pos is not None:
        above = [n for n in notes if n.start() < pos]
        notes = above[-1:] or notes
    m = notes[0] if notes else None
    return {"millions": "million", "thousands": "thousand", "billions": "billion"}[m.group(1).lower()] if m else "million"


def extract_period(text):
    head = text[:4000]   # the period is stated near the top of the release
    patterns = [
        # headline form: "Results for Fourth Quarter and Fiscal 2026"
        (r"\b(first|second|third|fourth)[- ]quarter and (fiscal(?: year)?) (\d{4})", "qf"),
        # "fourth quarter fiscal 2024", "fourth quarter of fiscal year 2024"
        (r"\b(first|second|third|fourth)[- ]quarter(?: of)? (fiscal(?: year)?) (\d{4})", "qf"),
        # "fiscal 2025 third quarter", "fiscal year 2025 second quarter"
        (r"\b(fiscal(?: year)?) (\d{4}) (first|second|third|fourth)[- ]quarter", "fq"),
        # "Q3 FY25", "Q3 fiscal 2025"
        (r"\b(Q[1-4]) (?:FY|fiscal(?: year)?) ?'?(\d{2,4})\b", "qfy"),
        # "fourth quarter 2024", "second quarter of 2025"
        (r"\b(first|second|third|fourth)[- ]quarter(?: of)? (\d{4})", "q"),
        # "Q2 2025"
        (r"\b(Q[1-4]) (\d{4})\b", "qy"),
        # "third quarter ended September 30, 2024"
        (r"\b(first|second|third|fourth) (?:fiscal )?quarter ended ([A-Z][a-z]+ \d{1,2},? \d{4})", "qended"),
        # "quarter ended June 30, 2025"
        (r"\bquarter ended ([A-Z][a-z]+ \d{1,2},? \d{4})", "ended"),
    ]
    # Forward-looking mentions ("outlook for the first quarter of fiscal 2027",
    # "Beginning in the first quarter of ...") name the NEXT quarter, not the
    # one being reported - skip a match if one of these words comes just before it.
    forward = re.compile(r"(outlook|guidance|beginning|expect|forecast|next)\b[^.]{0,40}$", re.I)
    for pat, kind in patterns:
        m = next((x for x in re.finditer(pat, head, flags=re.I)
                  if not forward.search(head[max(0, x.start() - 60):x.start()])), None)
        if not m:
            continue
        if kind == "qf":
            return f"{m.group(1).lower()} quarter fiscal {m.group(3)}"
        if kind == "fq":
            return f"{m.group(3).lower()} quarter fiscal {m.group(2)}"
        if kind == "qfy":
            yr = m.group(2)
            yr = "20" + yr if len(yr) == 2 else yr
            return f"{ORDINALS[m.group(1).lower()]} quarter fiscal {yr}"
        if kind == "q":
            return f"{m.group(1).lower()} quarter {m.group(2)}"
        if kind == "qy":
            return f"{ORDINALS[m.group(1).lower()]} quarter {m.group(2)}"
        if kind == "qended":
            return f"{m.group(1).lower()} quarter ended {m.group(2)}"
        if kind == "ended":
            return f"quarter ended {m.group(1)}"

    # Fallback (e.g. Walmart): the headline says only "reports second quarter
    # results", with no year. The fiscal year appears in the comparison-table
    # header, which pairs this quarter with the same quarter a year earlier:
    # "Q2 FY27 Q2 FY26". Requiring the matching pair skips guidance mentions
    # like "outlook for Q3".
    for m in re.finditer(r"\bQ([1-4]) FY'?(\d{2}) Q\1 FY'?(\d{2})\b", text):
        if int(m.group(2)) == int(m.group(3)) + 1:
            return f"{ORDINALS['q' + m.group(1)]} quarter fiscal 20{m.group(2)}"
    return NOT_FOUND


def _narrative_revenue(text):
    # Narrative sentences, e.g. "quarterly revenue of $94.9 billion",
    # "Revenue was $65.6 billion", "net sales increased 10% to $155.7 billion"
    rev_word = r"(?:total )?(?:net )?(?:revenues?|net sales|sales)"
    narrative = [
        rf"{rev_word}(?: for the (?:quarter|period))?(?: of| was| were| totaled| reached| came in at)(?: a record)? \$ ?({NUM}) ?{UNIT}",
        rf"{rev_word} (?:increased|decreased|grew|rose|declined|fell|up|down) (?:\d+(?:\.\d+)?%|[\w\s]{{0,40}}?) to \$ ?({NUM}) ?{UNIT}",
        rf"(?:record )?{rev_word}[^.$]{{0,80}}?\$ ?({NUM}) ?{UNIT}",
        rf"\$ ?({NUM}) ?{UNIT} (?:in|of) (?:quarterly )?(?:total )?(?:net )?(?:revenues?|net sales|sales)",
    ]
    for pat in narrative:
        m = re.search(pat, text, flags=re.I)
        if m:
            return _fmt_revenue(m.group(1), m.group(2))

    # Table fallback: "Total net sales $ 94,930" / "Revenue $ 65,585" (units from table header)
    table = re.search(rf"\b(?:Total net sales|Total revenues?|Net sales|Revenues?)\s*\$?\s*({NUM})\b", text)
    if table and table.group(1).replace(",", "").replace(".", "").isdigit() and len(table.group(1)) >= 4:
        return _fmt_revenue(table.group(1), _table_scale(text))
    return NOT_FOUND


def _narrative_eps(text):
    patterns = [
        rf"diluted (?:earnings|net income) per (?:common )?share(?: \(\"?EPS\"?\))?(?: attributable to [\w\s.,]+?)?(?: of| was| were| totaled| came in at)? \$ ?(\d+\.\d{{2}})",
        rf"(?:earnings|EPS|net income) per diluted share[^$.]{{0,60}}?\$ ?(\d+\.\d{{2}})",
        rf"diluted EPS(?: of| was| were)? \$ ?(\d+\.\d{{2}})",
        rf"\$ ?(\d+\.\d{{2}}) per diluted share",
        rf"(?:GAAP )?EPS(?: of| was| were)? \$ ?(\d+\.\d{{2}})",
        rf"net income of \$ ?{NUM_NC} ?(?:billion|million),? or \$ ?(\d+\.\d{{2}}) per (?:common )?share",
        rf"\(\$ ?(\d+\.\d{{2}}) per share\)",
        rf"diluted (?:earnings|net income) per (?:common )?share[^$]{{0,120}}?\$ ?\(?(\d+\.\d{{2}})",
        # table row: "Diluted $ 1.64"
        rf"\bDiluted\s*\$?\s*\(?(\d+\.\d{{2}})\)?",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            return m.group(1)
    return NOT_FOUND


def _narrative_net_income(text):
    patterns = [
        rf"net income(?: attributable to [\w\s.,]+?)?(?: for the (?:quarter|period))?(?: of| was| were| totaled| came in at)? \$ ?({NUM}) ?{UNIT}",
        rf"net income (?:increased|decreased|grew|rose|declined|fell) (?:\d+(?:\.\d+)?%|[\w\s]{{0,40}}?) to \$ ?({NUM}) ?{UNIT}",
        rf"net income[^.$]{{0,80}}?\$ ?({NUM}) ?{UNIT}",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.I)
        if m:
            return _fmt_money(m.group(1), m.group(2))

    # Table fallback 1 (e.g. Walmart): "Consolidated net income attributable to
    # Walmart $ 6,366" - the shareholders' figure, never the noncontrolling line.
    table = re.search(rf"\bnet income attributable to (?!noncontrolling)[A-Z][A-Za-z.,&\s]{{0,40}}?\s*\$\s*({NUM})\b",
                      text, flags=re.I)
    if table and len(table.group(1)) >= 3:
        return _fmt_money(table.group(1), _table_scale(text, table.start()))

    # Table fallback 2: "Net income $ 24,780" (units from table header)
    table = re.search(rf"\bNet income(?: attributable to [A-Za-z.,\s]+?)?\s*\$?\s*({NUM})\b", text)
    if table and len(table.group(1)) >= 3:
        return _fmt_money(table.group(1), _table_scale(text))
    return NOT_FOUND


# ---------------------------------------------------------------------------
# Financial-statement (table) extraction - tried FIRST for accuracy.
# Press-release headlines round ("$111.2 billion"); the condensed income
# statements give the exact figure ("Total net sales $ 111,184", in millions).
# In every release the current quarter is the first number after the row label.
# ---------------------------------------------------------------------------
REVENUE_ROWS = [
    rf"\bTotal net sales\s*(?:\(\d\))?\s*\$?\s*({NUM})",      # Apple
    rf"\bTotal revenues?\s*\$?\s*({NUM})",                     # Microsoft, Walmart
    rf"\bNet revenue\s*-\s*reported\s*\$?\s*({NUM})",          # JPMorgan
    rf"\bRevenues?\s*\$\s*({NUM})",                            # NVIDIA
]
NET_INCOME_ROWS = [
    # Walmart: shareholders' figure, never the noncontrolling-interest line
    rf"\bnet income attributable to (?!noncontrolling)[A-Z][A-Za-z.,&\s]{{0,40}}?\s*\$\s*({NUM})",
    rf"\bNet income\s*\$\s*\(?({NUM})",                        # Apple, MSFT, NVDA, JPM
]
EPS_ROWS = [
    r"\bEarnings per share\s*-\s*diluted\s*\$?\s*(\(?\d+\.\d{2}\)?)",                          # JPMorgan
    r"\bDiluted net income per common share attributable to [A-Z][\w.]*\s*\$?\s*(\(?\d+\.\d{2}\)?)",  # Walmart
    r"\bDiluted\s*\$\s*(\(?\d+\.\d{2}\)?)",                                                    # Apple, MSFT, NVDA
]


def _statement_scale(text, pos):
    """Unit of the table a row sits in: the closest '(In millions' /
    '($ in millions' / 'Amounts in millions' note ABOVE the row. Ignores
    phrases like 'shares ... reflected in thousands'. Defaults to millions,
    the unit all five companies use in their statements."""
    notes = [m for m in re.finditer(r"(?:\(|\$|Amounts|Dollars)\s*(?:are )?in (millions|thousands|billions)",
                                    text[:pos], flags=re.I)]
    return {"millions": "million", "thousands": "thousand", "billions": "billion"}[
        notes[-1].group(1).lower()] if notes else "million"


def _first_row(patterns, text, min_len=1, case=0):
    for pat in patterns:
        for m in re.finditer(pat, text, flags=case):
            if len(m.group(1).strip("()")) >= min_len:
                return m
    return None


def _statement_money(m, text):
    """Exact figure as reported, e.g. 'Total net sales $ 111,184' -> '111,184 million'."""
    return f"{m.group(1)} {_statement_scale(text, m.start())}"


def extract_revenue(text):
    m = _first_row(REVENUE_ROWS, text, min_len=5)          # >= 1,000 (million)
    return _statement_money(m, text) if m else _narrative_revenue(text)


def extract_net_income(text):
    m = _first_row(NET_INCOME_ROWS, text, min_len=3)
    if m:
        sign = "-" if m.group(0).rstrip(m.group(1)).endswith("(") else ""   # (1,234) = loss
        return f"{sign}{m.group(1)} {_statement_scale(text, m.start())}"
    return _narrative_net_income(text)


def extract_eps(text):
    m = _first_row(EPS_ROWS, text)
    if m:
        v = m.group(1)
        return "-" + v.strip("()") if v.startswith("(") else v.strip("()")
    return _narrative_eps(text)


def dollar(value):
    return value if value == NOT_FOUND else f"${value}"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    rows = []
    for co in COMPANIES:
        ticker, cik = co["ticker"], co["cik"]
        print(f"\n=== {co['company']} ({ticker}, CIK {cik}) ===")
        try:
            filings = get_earnings_filings(cik)
        except Exception as exc:
            print(f"{ticker}: could not read submissions API - {exc}")
            continue
        if not filings:
            print(f"{ticker}: no 8-K Item 2.02 filings found")
            continue

        for f in filings:
            row = {"company": co["company"], "ticker": ticker, "cik": cik,
                   "filing_date": f["filing_date"], "period": NOT_FOUND,
                   "revenue_reported": NOT_FOUND, "eps_diluted": NOT_FOUND,
                   "net_income": NOT_FOUND}
            try:
                idx_url = filing_index_url(cik, f["accession"])
                pr_url = find_press_release_url(idx_url, f["primary_doc"])
                if not pr_url:
                    print(f"    WARNING: {ticker} {f['filing_date']}: no press release exhibit "
                          f"(EX-99 .htm) found at {idx_url} - fields set to NOT_FOUND")
                else:
                    text = html_to_text(get(pr_url).text)
                    row["period"] = extract_period(text)
                    row["revenue_reported"] = extract_revenue(text)
                    row["eps_diluted"] = extract_eps(text)
                    row["net_income"] = extract_net_income(text)
            except Exception as exc:
                print(f"    WARNING: {ticker} {f['filing_date']}: error processing filing - {exc}")

            # guarantee no blank cells
            for key in CSV_COLUMNS:
                if row[key] in (None, ""):
                    row[key] = NOT_FOUND
            rows.append(row)

            print(f"{ticker} | {row['period']} | Revenue: {dollar(row['revenue_reported'])} | "
                  f"EPS: {dollar(row['eps_diluted'])} | Net Income: {dollar(row['net_income'])}")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
