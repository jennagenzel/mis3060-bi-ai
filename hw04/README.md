# HW04 — Data Profiling, Cleaning and Validation

Wildcat Capital client-portfolio data: 8 raw tables (5 dimensions, 3 facts) are audited, cleaned and validated with three Python scripts. Every decision is documented in `decision_log.md`, and every change is traceable in `data/audit/`.

## Folder structure

```
hw04/
├── README.md                     this file
├── Specifications.md             assignment prompts
├── decision_log.md               one row per issue: evidence, dimension, decision, justification, risk
├── *.csv                         8 RAW tables (never modified; transactions file is "fact_transactions (1).csv")
├── scripts/
│   ├── 01_profile.py             Part A - generic profiler + data-quality checks (no per-table code)
│   ├── 02_clean.py               Part C - cleans the raw tables per decision_log.md
│   ├── 03_validate.py            referential integrity, business rules, reconciliations, IQR, scorecard
│   └── check_referential_integrity.md   copy of the reusable function (for Assignment 5)
├── reports/
│   ├── profile_raw.csv           one row per table x column (nulls, distinct, shapes, parse failures...)
│   ├── dq_summary_raw.csv        every finding, tagged ERROR / WARN / INFO
│   ├── data_quality_scorecard.csv  raw vs clean: completeness, key uniqueness, type validity, rule pass, referential match
│   └── cleaning_report.md        1-2 page report for the portfolio committee
└── data/
    ├── clean/                    8 cleaned tables (same names and columns + 0/1 flag columns) + README_clean.md
    └── audit/                    cleaning_log.csv, value_changes.csv, quarantine_*.csv
```

## How to run

From the `hw04` folder in PowerShell:

```powershell
..\.venv\Scripts\Activate.ps1          # activate the course virtual environment (parent folder)
python scripts\01_profile.py           # audit all 8 tables  -> reports\profile_raw.csv, reports\dq_summary_raw.csv
python scripts\02_clean.py             # clean               -> data\clean\, data\audit\
python scripts\03_validate.py          # validate raw + clean -> reports\data_quality_scorecard.csv
```

- Run the scripts in order: `02_clean.py` reads the raw files, and `03_validate.py` needs `data\clean\`.
- `01_profile.py` takes optional table names, e.g. `python scripts\01_profile.py dim_client fact_fees`.
- All scripts read every file as text (`dtype=str, keep_default_na=False`) and convert columns on purpose.
- `02_clean.py` checks the SHA-256 hash of each raw file at the start and the end, and stops if anything changed. Each cleaning step asserts its result and stops the script if a fix did not do what it claimed.

## Cleaning order (02_clean.py)

| Step | Why it runs here |
|---|---|
| 1. Quarantine duplicate clients | First, so no later fix is applied to a row that is about to be removed |
| 2. Standardize states, then fill risk profiles | After step 1, so counts and the benchmark → profile evidence cover real clients only |
| 3. Convert expense ratios | Independent of the other tables |
| 4. Convert `%` returns, then flag extreme returns | The `%` values can't be compared with the −75% / +300% bounds until they are decimals |
| 5. Flag AUM floor, then flag fees on the floor | Each floor fee is confirmed by matching it to a snapshot already flagged at the floor |
| 6. Quarantine orphan transactions, then fix and flag transactions | Repairs aren't spent on rows that can't join to a client |
| 7. Convert `security_id` before validation | Joins to securities can only be tested once `'45.0'` has become `'45'` |
| 8. Validate, then re-check raw-file hashes | Checks the finished tables and proves the raw files were never modified |

## Claude Code findings

### 1. Data problems flagged, and what was done

Full detail is in `decision_log.md` (29 issues). Actions taken:

| Problem flagged | Action |
|---|---|
| 300 `return_ytd` values written as text like `'9.28%'` | **Converted** to decimals; confirmed by return = benchmark + alpha on 300/300 rows |
| 836 Buy rows with negative shares | **Converted** to positive; confirmed by amount = \|shares\| × price on 836/836 rows; flagged `shares_sign_corrected` |
| 197,175 `security_id` values stored as `'45.0'` (text join to securities failed) | **Converted** to `'45'`; join now matches 100% |
| 219 `expense_ratio_bps` values stored as `'17.0'` | **Converted** to whole numbers |
| 200 transactions for client IDs 2702–3192 that don't exist | **Quarantined** to `data/audit/` |
| 25 clients recorded twice (IDs 2501–2525, last name off by one final letter) | **Quarantined** the copies; no fact row used them |
| 78 states spelled out ("Pennsylvania") | **Standardized** to two-letter codes |
| 76 blank risk profiles | **Filled** as Balanced (benchmark 3 is used only by Balanced clients); flagged `risk_profile_imputed` |
| `return_ytd` is AUM change incl. deposits/withdrawals: 817 below −75%, 373 above +300% | **Flagged** `return_flow_distorted` |
| $1,000 AUM floor (420 snapshots) and fees charged on it (386) | **Flagged** `aum_at_floor`, `fee_on_floor_aum` |
| 53,864 dividends equal the full position value | **Flagged** `dividend_is_position_value` |
| 2,410 transactions after an account's last snapshot (inactive clients) | **Flagged** `txn_after_account_close` |
| 84,999 transactions (28%) on weekends | **Flagged** `on_non_trading_day` |
| 7,350 snapshot months with no fee row | **Flagged** `fee_missing` |
| Advisory Fee transactions disagree with `fact_fees` (2023: $63.7M vs $42.4M) | **Flagged** `advisory_fee_unreconciled`; `fact_fees` used for fee revenue |

13 further items looked suspicious but were confirmed legitimate and **left as is** (e.g. blank `security_id` on cash rows, ZIP codes with leading zeros, the text `'None'` for advisors with no certification, large balances for ultra-high-net-worth clients).

**Result (`reports/data_quality_scorecard.csv`):**

- **Transactions:** referential match rose from 81.95% to 100% and type validity from 91.73% to 100%.
- **Clients:** key uniqueness rose from 98.02% to 100%.
- **Clean data overall:** every table is at 100% on completeness, key uniqueness and type validity. Rule pass is 100% everywhere except `fact_transactions` (98.002%), where the remaining failures are the flagged advisory-fee rows.

### 2. Problems Claude Code found in its own work, and what was done

| Found | Fix |
|---|---|
| The first version of `01_profile.py` missed root causes and gave misleading labels: it didn't detect that returns include cash flows, dividends equal to position value, the advisory-fee mismatch, or that post-snapshot activity belongs to inactive clients. It also called the $1,000 AUM a "placeholder" and flagged correct 0% returns. | Re-verified every finding directly against the raw data and **rewrote the script (revision 2)**, still with no per-table code. The change list is in the script's docstring. |
| `02_clean.py` stopped on its own assert: one duplicate-client pair was Pace/Pacen (an extra letter), not a truncated name. | The script now identifies the copy by which row the fact tables use; the decision log wording was corrected. |
| Decision log count of returns above +300% was off by one (372) | Corrected to 373, the count after the `%` values are converted |
| The decision log and report contained two unsupported percentages ("about 5%" of months without a fee; "roughly 20–50%" fee understatement) | **Removed** from both files; replaced with verified figures (7,350 months; 2023: $42.4M vs $63.7M) |
| `03_validate.py` has no direct rule for `active_alpha_ytd` | Left as is: alpha has no natural limit of its own and is validated through the return = benchmark + alpha reconciliation |

Every number in `reports/cleaning_report.md` was cross-checked three ways: against the decision log and scorecard, against the script outputs, and against a recount from the raw data.

## Known limitations

These are flagged rather than fixed, because fixing them would mean inventing data. The full list, with reasons, is in `data/clean/README_clean.md`.

- **Returns:** `return_ytd` and alpha are balance growth, not investment performance.
- **Dividends:** dividend amounts are position values, not payouts.
- **Fees:** the two fee sources disagree.
- **Dates:** weekend dates, and market holidays marked as trading days.
