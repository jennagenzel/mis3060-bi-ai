"""
hw03_executives.py  -  MIS3060 HW03, Specification B: Executive Events Pipeline

One run does the following:
  1. Sends the same SEC User-Agent header used in hw03_earnings.py on every request.
  2. Pulls each company's filing history from the EDGAR submissions API and keeps
     8-K filings whose `items` field contains "5.02" (Departure of Directors or
     Certain Officers; Election of Directors; Appointment of Certain Officers)
     and whose `filingDate` falls within the past 12 months.
  3. Downloads each filing's full 8-K document, strips the HTML, isolates the
     Item 5.02 section and extracts, for every person it describes:
       event type ("departure", "appointment" or "both"), full name, title,
       and effective date of the change.
  4. Writes one row per event - a filing that reports a departure AND an
     appointment produces two rows. "both" is used when the SAME person leaves
     one role and takes another (e.g. CFO -> Senior Advisor).
  5. Prints each event as it is processed:  Ticker | Date | Event Type | Name | Title
  6. Prints "<Ticker>: No executive events in past 12 months" when a company has
     no Item 5.02 8-Ks in the window (valid data, not an error).
  7. Saves everything to hw03/executive_events.csv.

An effective date the filing never states is stored as "not stated in filing (announced
YYYY-MM-DD)". Any other field that cannot be extracted is stored as "NOT_FOUND" (never blank), matching
the convention used in hw03_earnings.py.

Run from the repo root (mis3060-bi-ai) or from inside hw03 - the CSV always lands
next to this script in the hw03 folder.
"""

import csv
import html
import re
import time
from datetime import date, datetime
from pathlib import Path

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # the script still works without bs4 (regex fallback)
    BeautifulSoup = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
USER_AGENT = "MIS3060 Villanova jgenzel@villanova.edu"   # same header as hw03_earnings.py
HEADERS = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"}

COMPANIES = [
    {"company": "Apple Inc.",            "ticker": "AAPL", "cik": "0000320193"},
    {"company": "Microsoft Corporation", "ticker": "MSFT", "cik": "0000789019"},
    {"company": "NVIDIA Corporation",    "ticker": "NVDA", "cik": "0001045810"},
    {"company": "JPMorgan Chase & Co.",  "ticker": "JPM",  "cik": "0000019617"},
    {"company": "Walmart Inc.",          "ticker": "WMT",  "cik": "0000104169"},
]

TARGET_ITEM = "5.02"
FORM_TYPES = {"8-K"}          # add "8-K/A" here to also include amendments
REQUEST_PAUSE = 0.15          # SEC allows max 10 requests/second
NOT_FOUND = "NOT_FOUND"

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_CSV = SCRIPT_DIR / "executive_events.csv"
CSV_COLUMNS = ["company", "ticker", "cik", "filing_date", "event_type",
               "person_name", "title", "effective_date"]


# ---------------------------------------------------------------------------
# HTTP helper - the ONLY place requests.get() is called, always with HEADERS
# ---------------------------------------------------------------------------
def get(url, retries=3):
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
# Step 2: find 8-K Item 5.02 filings from the past 12 months
# ---------------------------------------------------------------------------
def twelve_months_ago(today=None):
    today = today or date.today()
    try:
        return today.replace(year=today.year - 1)
    except ValueError:                       # Feb 29 -> Feb 28
        return today.replace(year=today.year - 1, day=28)


def _collect(block, cutoff, out):
    """Append matching filings from one 'recent'-style column block."""
    for i, form in enumerate(block.get("form", [])):
        filing_date = block["filingDate"][i]
        items = block.get("items", [""] * len(block["form"]))[i] or ""
        if (form in FORM_TYPES
                and TARGET_ITEM in [x.strip() for x in items.split(",")]
                and filing_date >= cutoff.isoformat()):
            out.append({
                "accession": block["accessionNumber"][i],
                "filing_date": filing_date,
                "primary_doc": block["primaryDocument"][i],
            })


def get_502_filings(cik, cutoff):
    """Return 8-K Item 5.02 filings filed on/after `cutoff`, newest first."""
    data = get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    filings = data["filings"]
    matches = []
    _collect(filings["recent"], cutoff, matches)

    # 'recent' normally covers >= 1 year, but heavy filers can spill into the
    # paged history files - read those too if they overlap the 12-month window.
    for extra in filings.get("files", []):
        if extra.get("filingTo", "0000-00-00") >= cutoff.isoformat():
            _collect(get(f"https://data.sec.gov/submissions/{extra['name']}").json(),
                     cutoff, matches)

    seen, unique = set(), []
    for f in sorted(matches, key=lambda f: f["filing_date"], reverse=True):
        if f["accession"] not in seen:
            seen.add(f["accession"])
            unique.append(f)
    return unique


# ---------------------------------------------------------------------------
# Step 3a: download the 8-K and strip HTML
# ---------------------------------------------------------------------------
def filing_base_url(cik, accession):
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"


def html_to_text(raw_html):
    """Strip HTML tags/scripts and collapse whitespace into plain text."""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for tag in soup.find_all(style=re.compile(r"display:\s*none", re.I)):
            tag.decompose()                       # hidden inline-XBRL header
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


def download_8k_text(cik, filing):
    """Download the 8-K document itself (primaryDocument). If that fails,
    fall back to the complete submission text file for the accession."""
    base = filing_base_url(cik, filing["accession"])
    try:
        return html_to_text(get(base + filing["primary_doc"]).text)
    except Exception:
        return html_to_text(get(base + filing["accession"] + ".txt").text)


# ---------------------------------------------------------------------------
# Step 3b: isolate the Item 5.02 section
# ---------------------------------------------------------------------------
ITEM_502 = re.compile(r"Item\s*5\.02\.?", re.I)
# the standard item heading - some filers put it after "(b)" instead of after "Item 5.02"
HEADING_502 = re.compile(
    r"Departure of Directors or (?:Certain )?Officers[^.]{0,250}?"
    r"(?:Compensatory Arrangements of Certain Officers|Appointment of Certain Officers)\.?", re.I)
# next item heading (but not a cross-reference like "Item 5.02(c)" or "Item 401(d)")
NEXT_SECTION = re.compile(r"\b(?i:Item)\s*\d{1,2}\.\d{2}\b(?!\s*\()|\bSIGNATURES?\b(?=\s)")


def isolate_item_502(text):
    heads = list(ITEM_502.finditer(text))
    if heads:
        # prefer the occurrence that is followed by the "Departure of ..." title
        head = next((h for h in heads
                     if re.match(r"\W*Departure", text[h.end():h.end() + 40], re.I)), heads[0])
        body = text[head.end():]
        stop = NEXT_SECTION.search(body)
        if stop:
            body = body[:stop.start()]
    else:
        body = text
    return HEADING_502.sub(" ", body, count=1).strip()


# ---------------------------------------------------------------------------
# Step 3c: text clean-up, sentences and dates
# ---------------------------------------------------------------------------
MONTHS = ("January|February|March|April|May|June|July|August|September|October|"
          "November|December|Jan\\.|Feb\\.|Mar\\.|Apr\\.|Jun\\.|Jul\\.|Aug\\.|Sept?\\.|"
          "Oct\\.|Nov\\.|Dec\\.")
DATE_RE = rf"(?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}}"

_ABBREV = re.compile(r"\b(Messrs|Mr|Ms|Mrs|Dr|Mx|Inc|Co|Corp|Ltd|Jr|Sr|No|St|U\.S|[A-Z])\.")


def split_sentences(text):
    protected = _ABBREV.sub(lambda m: m.group(1) + "<DOT>", text)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"(])", protected)
    return [p.replace("<DOT>", ".").strip() for p in parts if p.strip()]


def to_iso(date_str):
    s = re.sub(r"\s+", " ", date_str).replace("Sept.", "Sep.")
    s = re.sub(r"\s*,\s*", ", ", s)
    for fmt in ("%B %d, %Y", "%b. %d, %Y", "%B %d %Y", "%b. %d %Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return date_str


def prepare_section(section):
    """Normalise wording that trips up the extraction rules."""
    # 'Vice President, or VP, and Chief Accounting Officer, or CAO, of NVIDIA' ->
    # 'Vice President and Chief Accounting Officer of NVIDIA'
    section = re.sub(r",\s*or\s+(?:the\s+)?(?:[A-Z][A-Za-z&]*\s?){1,3},", " ", section)
    # 'effective February 1, 2026 (the "Effective Date")' ... 'as of the Effective Date'
    # -> replace later references to a defined date term with the date itself
    for m in re.finditer(rf'({DATE_RE})\s*\((?:the\s+)?"([^"]{{3,40}})"\)', section):
        section = re.sub(rf'\bthe {re.escape(m.group(2))}\b(?!")', m.group(1), section)
    return re.sub(r"\s+", " ", section)


# ---------------------------------------------------------------------------
# Step 3d: find the people
# ---------------------------------------------------------------------------
# Capitalised words that are NOT parts of a person's name
STOP = set("""
Mr Ms Mrs Dr Mx Messrs Mister Madam The A An On In As At By For Of To And Or But With From Upon
Under Pursuant Prior During After Before Since Each This That These Those Such His Her Their
Our We He She It Its There Effective Following Additionally Also Further Furthermore Lastly
General Item Items Section Exhibit Exhibits Form Report Current Registrant Company Companys
Corporation Firm Inc Co Corp Ltd LLC LP Plc PLC Holdings Group Bank Capital Partners Partner Board
Directors Director Committee Compensation Nominating Governance Audit Risk Annual Meeting
Meetings Special Shareholders Stockholders Shareholder Stockholder Chief Executive Financial
Operating Accounting Technology Legal Officer Officers Senior Vice President Presidents
Chairman Chairwoman Chair Chairperson Counsel Secretary Treasurer Controller Principal Head
Global Corporate Lead Independent Presiding Deputy International Americas Retail Services
Operations Human Resources People Marketing Strategy Commercial Digital Consumer Community
Banking Business Asset Wealth Management Investment Agreement Agreements Plan Plans Letter
Offer Award Awards Stock Equity Incentive Restricted Units Unit Performance Retirement
Departure Election Appointment Transition Separation Release Press News Securities Exchange
Act Commission United States America January February March April May June July August
September October November December Monday Tuesday Wednesday Thursday Friday Saturday Sunday
Fiscal Year Quarter Apple Microsoft NVIDIA Nvidia JPMorgan JPMorganChase Chase Walmart Sam
Sams Club Morgan Sachs Goldman University School College Institute Foundation Trust Fund
Street New York California Washington Texas Arkansas Delaware Cupertino Redmond Santa Clara
Bentonville Please Forward Looking Statements Information Signature Signatures Dated Date
Name Named Title Advisor Adviser Special Worldwide Field Achievement Target Opportunity Base
Salary Goals Goal Share Shares Continuity Retention Protection Protection-based Vesting
Policy Recoupment Recovery Regulation Schedule Proxy Statement Proposal Composite Index
Hardware Engineering Software Supply Chain Innovation Automation Product Products Sales
Solutions Industry Merchandising Consumables Associate Associates Covenant Non-Compete
Post-Termination Variable Payment Plan Program Programs Committee Position Positions
Tax Assistant Live Nation Entertainment Dansk Supermarked Tesco Coles Amazon Oracle Intel
Reuters Thomson Motors Standard Poor Poors Park Avenue Indemnification Indemnity
""".split())

PARTICLES = {"de", "van", "von", "der", "da", "del", "di", "la", "le", "du", "bin"}
NAME_TOKEN = re.compile(r"[A-Z](?:\.|[a-zA-Z'\-]*[a-z][a-zA-Z'\-]*)")
HONORIFIC = r"(?:Messrs|Mr|Ms|Mrs|Dr|Mx)\.?"


def candidate_names(section):
    """Runs of 2-4 capitalised name-like tokens (middle initials / particles
    allowed) that are not stop words. Returns [(name, start_offset)]."""
    names, run = [], []

    def close():
        toks = list(run)
        while toks and toks[-1][0] in PARTICLES:
            toks.pop()
        full_tokens = [t for t, _ in toks if not t.endswith(".") and t not in PARTICLES]
        if (2 <= len(toks) <= 4 and len(full_tokens) >= 2 and not toks[-1][0].endswith(".")
                and toks[0][0] not in PARTICLES):
            names.append((" ".join(t for t, _ in toks), toks[0][1]))
        run.clear()

    for m in re.finditer(r"\S+", section):
        raw = m.group(0)
        core = raw.lstrip("(\"'[")
        core = re.sub(r"'s?$", "", core.rstrip(",;:)\"]"))
        ends_run = core != raw.lstrip("(\"'[") and not raw.endswith(".")
        if core.endswith(".") and len(core) > 2:              # sentence-final period
            core, ends_run = core[:-1], True
        is_initial = re.fullmatch(r"[A-Z]\.", core) is not None
        is_name_tok = (core in PARTICLES or is_initial or
                       (NAME_TOKEN.fullmatch(core) is not None and core not in STOP))
        if is_name_tok:
            run.append((core, m.start()))
            if ends_run:
                close()
        else:
            close()
    close()
    return names


TRIGGER = re.compile(r"appoint|elect|named(?! executive)|promot|hire|join|succeed|resign|retire|"
                     r"step(?:s|ped)? down|depart|leav|re-?election|transition|separat|"
                     r"serve as|become", re.I)


def find_people(section):
    """Return {full_name: [aliases]} for the people the section talks about."""
    honorific_surnames = set(re.findall(rf"\b{HONORIFIC}\s+([A-Z][A-Za-z'\-]+(?: [A-Z][A-Za-z'\-]+)?)", section))
    honorific_lasts = {s.split()[-1] for s in honorific_surnames}
    people = {}
    for name, pos in candidate_names(section):
        toks = name.split()
        last = toks[-1]
        has_honorific = last in honorific_lasts
        if not has_honorific:
            # 'Senior Vice President of Hardware Engineering' - a capitalised phrase
            # after "of"/"at"/"'s" is an organisation or department, not a person
            if re.search(r"(?:\bof|\bat|\bfor|'s)\s*$", section[max(0, pos - 6):pos]):
                continue
            window = section[max(0, pos - 150): pos + len(name) + 150]
            if not TRIGGER.search(window):
                continue
        # merge spellings of the same person ("John Furner" / "John R. Furner")
        same = next((n for n in people if n.split()[-1] == last and n.split()[0] == toks[0]), None)
        if same is None:
            people[name] = None
        elif len(name) > len(same):
            del people[same]
            people[name] = None
    # drop names that are just the tail of a longer one ("Nora Johnson" < "Suzanne Nora Johnson")
    for n in list(people):
        if any(o != n and o.endswith(" " + n) for o in people):
            del people[n]
    # people only ever referred to as "Mr. Smith"
    for sur in honorific_surnames:
        last = sur.split()[-1]
        if last not in STOP and not any(p.split()[-1] == last for p in people):
            people[last] = None

    out = {}
    for full in people:
        toks = full.split()
        aliases = {full, toks[-1]}
        if len(toks) >= 3 and not toks[1].endswith("."):
            aliases.add(" ".join(toks[1:]))                  # "Di Sibio", "Nora Johnson"
        out[full] = aliases
    return out


# ---------------------------------------------------------------------------
# Step 3e: event keywords
# ---------------------------------------------------------------------------
# keywords that apply to the person who is the SUBJECT of the clause
DEPART_SUBJ = re.compile(
    r"\b(?:resign\w*|retire[sd]?\b|retiring|retirement|step(?:s|ped|ping)? down"
    r"|depart(?:s|ed|ing|ure)?\b|leav(?:e|es|ing)\b|left the (?:company|firm|board)"
    r"|will not (?:stand|seek|be nominated) for re-?election"
    r"|(?:not|decline[sd]?) to (?:stand|seek) (?:for )?re-?election"
    r"|transition(?:s|ed|ing)? (?:out of|from)|ceas(?:e|es|ed) to (?:serve|be)"
    r"|no longer (?:serve|be)|separat(?:e|es|ed|ion) from|succeeded by|replaced by"
    r"|until [^.;]{0,80}?at which time"
    r"|(?:employment|service) (?:was|will be) terminated|conclude (?:his|her|their) (?:service|tenure))",
    re.I)
APPOINT_SUBJ = re.compile(
    r"\b(?:(?:has been|have been|was|were|will be|is|is being|had been|to be|been|being)(?: also)?"
    r" (?:appointed|elected|named|promoted|hired|designated|selected|chosen)"
    r"|will (?:join|become|serve as|assume|succeed|take on|lead)"
    r"|(?<!continue )(?<!continues )(?<!continued )to (?:succeed|serve as|become|assume|join)\b"
    r"|succeed(?:s|ed|ing)?\b(?! by)"
    r"|transition(?:s|ed|ing)? to (?:the |a |an )?(?:new )?(?:role|position)"
    r"|join(?:s|ed|ing)? (?:the (?:company|firm|board)|as)"
    r"|accepted (?:an?|the) (?:offer|appointment|position))",
    re.I)
# keywords just BEFORE a person's name ("the Board appointed Jane Doe")
APPOINT_PRE = re.compile(
    r"(?:appoint(?:ed|s|ing|ment of)|elect(?:ed|s|ing|ion of)|nam(?:ed|es|ing)(?! executive)"
    r"|promot(?:ed|es|ion of|ions of)|hir(?:ed|es|ing)|designat(?:ed|es)|welcom(?:ed|es)|select(?:ed|s)"
    r"|succeeded by|replaced by|(?:appointment|election|hiring|selection) of)"
    r"(?:\s+[\w,]+){0,2}?\s*[,:]?\s*$", re.I)
DEPART_PRE = re.compile(
    r"(?:(?:retirement|resignation|departure|separation|termination) of|succeed(?:s|ed|ing)?"
    r"|replac(?:e|es|ing)|transition (?:of (?:duties|responsibilities) )?from)"
    r"(?:\s+[\w,]+){0,2}?\s*[,:]?\s*$", re.I)
SUCCESSION_BY = re.compile(r"(?:succeeded|replaced) by(?:\s+[\w,]+){0,2}?\s*[,:]?\s*$", re.I)
SUCCEED_PRE = re.compile(r"(?:succeed(?:s|ed|ing)?|replac(?:e|es|ing))\s*$", re.I)
# "will transition from his role as Chief Executive Officer to Executive Chair"
ROLE_CHANGE = re.compile(r"transition\w* from (?:his|her|their) (?:role|position)s? as (.{3,120}?) to (.{3,160})", re.I)
# "Doug Petno, 61, and Troy Rohrbaugh, 56, ... have been elected"
COORDINATED = re.compile(r"^\s*(?:,\s*(?:age\s*)?\d{1,3}\s*)?,?\s*(?:and|&)\s*$")


def is_biographical(sentence, filing_year):
    """Sentences like 'Mr. X served as ... from 2015 to 2019' describe past
    career history, not the event being reported."""
    for m in re.finditer(r"\b(?:since|from|in|until|between|through|during|prior to)\s+"
                         r"(?:[A-Za-z]+\s+){0,2}((?:19|20)\d{2})\b", sentence):
        if int(m.group(1)) < filing_year:
            return True
    return bool(re.search(r"\bprior to (?:joining|his|her|that|becoming)|\bpreviously served\b",
                          sentence, re.I))


# ---------------------------------------------------------------------------
# Step 3f: titles
# ---------------------------------------------------------------------------
LC_TITLE_WORDS = (r"(?:president|chief|executive|officer|vice|senior|general|counsel|financial|"
                  r"operating|accounting|secretary|treasurer|controller|director|chair|chairman|"
                  r"chairwoman|principal|corporate|lead|independent|co-president|co-chief)")
CONNECTORS = {"and", "of", "&", "the", "for"}
TITLE_TOKEN = rf"(?:[A-Z][\w&'.\-]*|{LC_TITLE_WORDS}\b|and|of|&|the|for)"
TITLE_RUN = rf"{TITLE_TOKEN}(?:\s*,?\s*{TITLE_TOKEN})*"
TITLE_LEAD = (r"(?:(?:the|our|its|a|an|his|her|their|then-?|current|currently|interim|acting|sole|new)\s+)*"
              r"(?:(?:[A-Z][\w.&]*(?: Inc\.)?)'s\s+)?"
              r"(?:(?:current|then-?current|interim|acting|sole|new)\s+)?")
TITLE_HINT = re.compile(
    r"\b(?:Chief|Officer|President|Vice|Senior|Executive|Chair\w*|Counsel|General|Secretary|"
    r"Treasurer|Controller|Director|Head|Global|Corporate|Principal|Financial|Operating|"
    r"Accounting|Lead|Deputy|Co-\w+|Board|Advisor|Adviser|Partner|Leader|"
    r"CEOs?|CFO|COO|CAO|CTO|CLO|CIO|CHRO|CMO|CRO|EVP|SVP|VP)\b", re.I)
TITLE_ANCHOR = re.compile(
    r"\b(?:Officer|President|Chair\w*|Counsel|Secretary|Treasurer|Controller|Director|Head|"
    r"Advisor|Adviser|Partner|Leader|CEO|CFO|COO|CAO|CTO|CLO|CIO|CHRO|CMO|CRO|VP|EVP|SVP)s?\b")
_PEOPLE_WORDS = set()          # names in the current section (so "as CFO, Kevan Parekh" stops at CFO)


def _cap(word):
    if word in CONNECTORS or not word[:1].islower():
        return word
    return "-".join(p[:1].upper() + p[1:] for p in word.split("-"))


def clean_title(raw):
    """Turn a captured run of words into a tidy title, or None."""
    if not raw:
        return None
    raw = re.sub(r"^(?:(?:of|for|and|&|the)\s+)+", "", raw.strip(" ,"))
    raw = re.sub(r"\s+(?:of|for)\s+(?:the\s+)?(?:Company|Corporation|Firm|Registrant|"
                 r"[A-Z][\w.&']*(?:\s+(?:[A-Z][\w.&']*|&))*\s+(?:Inc\.?|Corporation|Corp\.?|Co\.?))\s*,?\s*$",
                 "", raw)
    kept = []
    for i, part in enumerate(p.strip() for p in raw.split(",")):
        if not part:
            continue
        words = part.split()
        if re.match(rf"{HONORIFIC}\s", part) or any(w.strip(".") in _PEOPLE_WORDS for w in words):
            break
        # first part must look like a title; later parts may be a unit name ("Walmart U.S.")
        if (i == 0 and not TITLE_HINT.search(part)) or (i > 0 and not TITLE_HINT.search(part)
                                                        and (len(words) > 5 or words[0] in CONNECTORS)):
            break
        kept.append(part)
    title = " ".join(_cap(w) for w in ", ".join(kept).split())
    for pat in (r"\s+(?:of|for|and|&|the)\s*$",
                r"\s+(?:of|for)\s+(?:the\s+)?(?:Company|Corporation|Firm|Registrant)$",
                r"\s+(?:of|for)\s+(?:the\s+)?[A-Z][\w.&']*(?:\s+(?:[A-Z][\w.&']*|&))*\s+"
                r"(?:Inc\.?|Corporation|Corp\.?|Co\.?)$",
                r"\s+(?:of|for|and|&|the)\s*$"):
        title = re.sub(pat, "", title)
    if title.endswith(".") and not re.search(r"\b[A-Z]\.[A-Z]\.$", title):
        title = title[:-1]
    title = re.sub(r"\b(Co-President|President|Officer|CEO|Chair)s\b", r"\1", title).strip(" ,")
    return title if TITLE_ANCHOR.search(title) else None


def title_after(text):
    """Title that starts at the beginning of `text` (after optional determiners)."""
    m = re.match(TITLE_LEAD + r"(" + TITLE_RUN + r")", text.lstrip(" ,"))
    return clean_title(m.group(1)) if m else None


def find_role_title(segment):
    """'... as Chief Financial Officer', 'in the role of President', etc."""
    for m in re.finditer(r"\b(?:as|(?:in|to) (?:the|this|that) (?:role|position|office)s? of|"
                         r"to (?:the )?(?:roles?|positions?) of)\s+", segment):
        t = title_after(segment[m.end():])
        if t:
            return t
    for m in re.finditer(r"\b(?:will become|to become|became|becomes|promoted to|named|appointed|"
                         r"elected)\s+(?!to\b)", segment):
        t = title_after(segment[m.end():])
        if t:
            return t
    return None


BOARD_RE = re.compile(r"\b(?:the Board|Board of Directors|as a director|re-?election|member of the Board)\b", re.I)


def appositive_title(after_mention):
    """'Jane Doe, 52, the Company's Senior Vice President and CFO, ...' -> (title, is_current)"""
    m = re.match(r"\s*,\s*(?:(?:age\s*)?\d{2}\s*,\s*)?(?:who (?:is|was|has served as|serves as) )?",
                 after_mention)
    if not m or "," not in after_mention[:m.end() + 1]:
        return None, False
    rest = after_mention[m.end():]
    return title_after(rest), bool(re.match(r"(?:the )?current(?:ly)?\b", rest, re.I))


# ---------------------------------------------------------------------------
# Step 3g: effective dates
# ---------------------------------------------------------------------------
ANNUAL_MEETING = re.compile(
    r"\b(?:at|until|following|upon|after|through) (?:the )?(?:conclusion of |close of )?(?:the )?"
    r"(?:[A-Z]\w*'s )?((?:[A-Z][a-z]+ )?(?:\d{4} )?annual (?:shareholders'?|stockholders'?|shareholder|"
    r"stockholder|general)?\s*meeting)", re.I)


def _effective_in(text, sentence, fallback_event_date):
    m = re.search(rf"\beffective (?:as of |on |at |upon )?(?:the (?:close|end|start) of "
                  rf"(?:business|the day|day) (?:on )?)?({DATE_RE})", text, re.I)
    if m:
        return to_iso(m.group(1))
    if re.search(r"\beffective immediately\b|\bwith immediate effect\b", text, re.I):
        own_on = re.search(rf"\bOn ({DATE_RE})", sentence)
        return to_iso(own_on.group(1)) if own_on else fallback_event_date
    m = re.search(r"\beffective ((?:as of |upon |at |following |on |after |with )?(?:the )?"
                  r"(?:conclusion|close|end|completion|expiration|start|beginning|commencement|"
                  r"employment|date|filing|appointment|election|adjournment)[^.;]{0,100}?)(?=[,.;]|$)",
                  text)                                        # case-sensitive on purpose
    if m:
        later = re.search(DATE_RE, text[m.start(1):m.end() + 150])
        return to_iso(later.group(0)) if later else "effective " + m.group(1).strip()
    m = ANNUAL_MEETING.search(text)
    if m:
        return "effective at the " + m.group(1).strip()
    m = re.search(rf"\b(?:will|to|would|plans to|intends to) (?:retire|resign|step down|depart|"
                  rf"leave|join|become|assume|begin|start)[^.;]{{0,80}}?\b(?:on|as of|by) ({DATE_RE})",
                  text, re.I)
    if m:
        return to_iso(m.group(1))
    return None


def find_effective_date(entries, section, filing_date):
    """entries: [(clause_after_name, sentence, text_before_name)] for one person."""
    first_on = re.search(rf"\bOn ({DATE_RE})", section)
    event_date = to_iso(first_on.group(1)) if first_on else filing_date
    for seg, sentence, _ in entries:          # 1. the person's own clauses
        d = _effective_in(seg, sentence, event_date)
        if d:
            return d
    for _, sentence, pre in entries:          # 2. "Effective January 8, 2026, the Board appointed X"
        d = _effective_in(pre, sentence, event_date)
        if d:
            return d
    for seg, _, pre in entries:               # 3. any date next to the person
        m = re.search(DATE_RE, seg)
        if m:
            return to_iso(m.group(0))
        dates = re.findall(DATE_RE, pre)
        if dates:
            return to_iso(dates[-1])
    m = re.search(rf"\beffective (?:as of |on )?({DATE_RE})", section, re.I)
    if m:
        return to_iso(m.group(1))
    # the filing gives no effective date at all (e.g. "has decided to retire" with
    # no date) - record that fact plus the announcement date instead of NOT_FOUND
    return f"not stated in filing (announced {event_date})"


# ---------------------------------------------------------------------------
# Step 3h + 4: turn one Item 5.02 section into event rows (one row per person)
# ---------------------------------------------------------------------------
def extract_events(section, filing_date):
    global _PEOPLE_WORDS
    section = prepare_section(section)
    filing_year = int(filing_date[:4])
    people = find_people(section)
    if not people:
        return fallback_event(section, filing_date)
    _PEOPLE_WORDS = {w for p in people for w in p.split() if len(w) > 2}

    alias_to_person = {}
    for full, aliases in people.items():
        for a in sorted(aliases, key=len, reverse=True):
            alias_to_person.setdefault(a, full)
    alias_re = re.compile(
        rf"(?:{HONORIFIC}\s+)?\b(?:" +
        "|".join(re.escape(a) for a in sorted(alias_to_person, key=len, reverse=True)) +
        r")\b(?:'s?)?")

    info = {p: {"dep": [False, False], "app": [False, False],        # [non-bio, bio]
                "dep_title": [], "app_title": [], "cur_title": [], "cur_is_current": False,
                "entries": [[], []], "order": None} for p in people}

    for s_idx, sentence in enumerate(split_sentences(section)):
        mentions = []
        for m in alias_re.finditer(sentence):
            alias = re.sub(rf"^{HONORIFIC}\s+|'s?$", "", m.group(0))
            if alias in alias_to_person:
                mentions.append((m.start(), m.end(), alias_to_person[alias]))
        for i, (start, end, person) in enumerate(mentions):
            rec = info[person]
            if rec["order"] is None:
                rec["order"] = (s_idx, start)
            prev_end = mentions[i - 1][1] if i else 0
            next_start = mentions[i + 1][0] if i + 1 < len(mentions) else len(sentence)
            pre, seg = sentence[prev_end:start], sentence[end:next_start]
            bio = 1 if is_biographical(pre + " " + seg, filing_year) else 0
            appos, is_current = appositive_title(seg)
            # "Doug Petno, 61, and Troy Rohrbaugh, 56, ... have been elected" - share the clause
            if COORDINATED.match(seg) and i + 1 < len(mentions):
                n_end = mentions[i + 1][1]
                n_next = mentions[i + 2][0] if i + 2 < len(mentions) else len(sentence)
                seg = sentence[n_end:n_next]
            rec["entries"][bio].append((seg, sentence, pre))

            # --- classify ---
            pre_app = False
            if SUCCESSION_BY.search(pre):
                rec["app"][bio] = pre_app = True
            elif DEPART_PRE.search(pre):
                rec["dep"][bio] = True
                # "Jane Doe will succeed John Smith as CFO" / "... in this role":
                # the departing person's old title = the successor's new title
                if SUCCEED_PRE.search(pre.strip()) and i:
                    successor = info[mentions[i - 1][2]]
                    t = find_role_title(seg[:150])
                    if t:
                        successor["app_title"].append(t)
                        rec["dep_title"].append(t)
                    elif re.match(r"\s*in (?:this|that|the same|such) (?:role|position)", seg) \
                            and successor["app_title"]:
                        rec["dep_title"].append(successor["app_title"][0])
            elif APPOINT_PRE.search(pre):
                rec["app"][bio] = pre_app = True

            change = ROLE_CHANGE.search(seg)
            dep_hit = DEPART_SUBJ.search(seg)
            app_hit = APPOINT_SUBJ.search(seg)
            if change:
                rec["dep"][bio] = rec["app"][bio] = True
            if dep_hit:
                rec["dep"][bio] = True
            if app_hit:
                rec["app"][bio] = True

            # --- titles ---
            if appos:
                rec["cur_title"].append(appos)
                rec["cur_is_current"] |= is_current and not bio
            if bio:
                continue
            if change:
                old, new = title_after(change.group(1)), title_after(change.group(2))
                if old:
                    rec["dep_title"].append(old)
                if new:
                    rec["app_title"].append(new)
            if app_hit or pre_app:
                start_at = app_hit.end() if app_hit else 0
                t = (find_role_title(seg[start_at:]) or title_after(seg[start_at:])
                     or find_role_title(seg))
                if t and t != appos:
                    rec["app_title"].append(t)
                elif re.search(r"\b(?:to|on|join) (?:the|its|our) Board\b|as a (?:member of the Board|director)",
                               seg, re.I):
                    rec["app_title"].append("Director")
            if dep_hit:
                if dep_hit.group(0).lower().startswith("until"):    # "continue to serve as X until ..."
                    t = find_role_title(seg[:dep_hit.start()])
                else:
                    t = find_role_title(seg[dep_hit.start():dep_hit.start() + 150])
                if t:
                    rec["dep_title"].append(t)
                elif BOARD_RE.search(seg):
                    rec["dep_title"].append("Director")

    rows = []
    for person in sorted(people, key=lambda p: info[p]["order"] or (1e9, 0)):
        rec = info[person]
        use = 0 if (rec["dep"][0] or rec["app"][0]) else 1      # prefer non-biographical evidence
        dep, app = rec["dep"][use], rec["app"][use]
        if not (dep or app):
            continue
        entries = rec["entries"][use] + rec["entries"][1 - use]
        all_segs = " ".join(e[0] for e in entries)
        cur = rec["cur_title"][0] if rec["cur_title"] else None
        board = "Director" if BOARD_RE.search(all_segs) else None
        new_title = rec["app_title"][0] if rec["app_title"] else None
        old_title = cur or (rec["dep_title"][0] if rec["dep_title"] else None)
        # "Art Levinson, current Chair of the Board, will become Lead Independent Director"
        if app and not dep and rec["cur_is_current"] and new_title and cur and new_title != cur:
            dep = True
        if dep and app:
            event = "both"
            old = (rec["dep_title"][0] if rec["dep_title"] else None) or cur
            if old and new_title and old != new_title:
                title = f"{old} -> {new_title}"
            else:
                title = new_title or old or board
        elif dep:
            event, title = "departure", old_title or board
        else:
            event, title = "appointment", new_title or board or cur
        rows.append({
            "event_type": event,
            "person_name": person,
            "title": title or NOT_FOUND,
            "effective_date": find_effective_date(entries, section, filing_date),
        })
    return rows


def fallback_event(section, filing_date):
    """Section describes an event but no person could be isolated:
    keep one row so the filing is not silently lost."""
    dep = bool(DEPART_SUBJ.search(section) or re.search(r"\b(?:retirement|resignation|departure) of\b", section, re.I))
    app = bool(re.search(r"\b(?:appointed|elected|named(?! executive officer)|promoted|hired)\b", section, re.I))
    if not (dep or app):
        return []
    return [{
        "event_type": "both" if dep and app else ("departure" if dep else "appointment"),
        "person_name": NOT_FOUND,
        "title": find_role_title(section) or NOT_FOUND,
        "effective_date": find_effective_date([(section, section, "")], section, filing_date),
    }]


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main():
    cutoff = twelve_months_ago()
    print(f"Looking for 8-K Item {TARGET_ITEM} filings dated {cutoff.isoformat()} or later\n")
    rows = []
    for co in COMPANIES:
        ticker, cik = co["ticker"], co["cik"]
        print(f"=== {co['company']} ({ticker}, CIK {cik}) ===")
        try:
            filings = get_502_filings(cik, cutoff)
        except Exception as exc:
            print(f"{ticker}: ERROR reading submissions API - {exc}\n")
            continue
        if not filings:
            print(f"{ticker}: No executive events in past 12 months\n")
            continue

        for f in filings:
            try:
                section = isolate_item_502(download_8k_text(cik, f))
                events = extract_events(section, f["filing_date"])
            except Exception as exc:
                print(f"    WARNING: {ticker} {f['filing_date']} ({f['accession']}): {exc}")
                continue
            if not events:
                print(f"    {ticker} | {f['filing_date']} | Item 5.02 describes no departure or "
                      f"appointment (e.g. compensation arrangement only) - no row written")
                continue
            for ev in events:
                row = {"company": co["company"], "ticker": ticker, "cik": cik,
                       "filing_date": f["filing_date"], **ev}
                for key in CSV_COLUMNS:                 # no blank cells
                    if row.get(key) in (None, ""):
                        row[key] = NOT_FOUND
                rows.append(row)
                print(f"{ticker} | {row['filing_date']} | {row['event_type']} | "
                      f"{row['person_name']} | {row['title']}")
        print()

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows)} events to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
