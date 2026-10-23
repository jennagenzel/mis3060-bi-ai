# Specifications

## Part A 

Here is a summary of the 8 data tables in my hw04 folder:
| File | Rows | Cols | Role |
|---|---:|---:|---|
| `dim_advisor.csv` | 25 | 7 | Advisors |
| `dim_client.csv` | 2,525 | 14 | Clients |
| `dim_date.csv` | 1,827 | 12 | Calendar, 2020–2024 |
| `dim_security.csv` | 500 | 8 | Securities and ETFs |
| `dim_benchmark.csv` | 8 | 4 | Performance benchmarks |
| `fact_fees.csv` | 122,197 | 8 | Monthly fee charges |
| `fact_portfolio_snapshot.csv` | 129,547 | 13 | Monthly account snapshots |
| `fact_transactions.csv` | 298,772 | 9 | Trades, income, cash flows, fee debits |

Here is the rule you need to follow: read every file as text (`dtype=str`, `keep_default_na=False`). Default `pd.read_csv` parsing can silently change a column: it drops leading zeros, turns `45` into `45.0`, turns blank cells and the word `None` into `NaN`, and hides `%` and `$` strings. Read as text first, then convert each column on purpose.

Write a script that will work on ANY of the 8 data tables (not per table hard coding) that at minimum reports the following for every column: null/blank count, distinct count, dominant value shapes, share of values that fail to parse as the expected type, whitespace problems, mixed formats, and numeric min/max. The script must add checks in four groups:

1. Column level: type, allowed values, ranges, key uniqueness
2. Single-table rules: duplicates, near-duplicates, values that contradict other columns of the same row
3. Referential integrity: every foreign key must point to an existing primary key
4. Cross-table business rules: facts that disagree with dimensions, or with each other

Tag each finding **ERROR** (wrong, or will break a join or calculation), **WARN** (probably wrong; investigate) or **INFO** (worth knowing). Save  `reports/profile_raw.csv` and `reports/dq_summary_raw.csv` in my hw04 folder. "Save the script as`scripts/01_profile.py` in my hw04 folder.

## Part C

Here is the rule you need to follow: read every file as text (`dtype=str`, `keep_default_na=False`). Default `pd.read_csv` parsing can silently change a column: it drops leading zeros, turns `45` into `45.0`, turns blank cells and the word `None` into `NaN`, and hides `%` and `$` strings. Read as text first, then convert each column on purpose.

Write me a script that reads the eight raw files and writes a new set of eight cleaned files based of the errors and/or warnings found in ` 01_profile.py`. Never modify the raw files in any way, shape or form. The script must clean all of the errors identified in the data, indicated in ` 01_profile.py`.  Save it as `scripts/02_clean.py` in my hw04 folder. Here are additional requirements that the script must meet:
- **Same file names, same columns: add clearly named flag columns (0/1) where a value is suspicious but cannot be corrected without inventing data
- One transformation at a time. After **each**: print rows affected and a before/after check, and `assert` the after-state. The script must stop if a fix did not do what you claimed
- Reconcile instead of guessing: Where one column can be recomputed from others, or two tables describe the same fact, use that to confirm a repair
- Nothing is deleted silently: Rows you remove go to a quarantine file with enough columns to trace them. Prove `raw rows = clean rows + quarantined rows` for every table
- Audit trail: save `data/audit/cleaning_log.csv` (table, issue, action, rows affected, note), `data/audit/value_changes.csv` (table, key column, key, column, old value, new value) and one `data/audit/quarantine_*.csv` per quarantined set
- Save the clean tables in `data/clean/`
- Write `data/clean/README_clean.md`: relationships between tables, column-type settings a BI tool will need, the flag columns you added, and **known limitations** you chose not to fix, each with a reason


## Part D

Write me a script titled `scripts/03_validate.py` and save it to my hw04 folder. Here is what the script must do/ contain:

-  Has **One** reusable function `check_referential_integrity(fact_df, fact_key, dim_df, dim_key)` that returns match rate, orphan rows, distinct orphan keys, and null-key rate. The script must apply it to every relationship between the eight tables (there are ten ID-based ones and three that join to the date table; find them). 

**Keep this function: I  will reuse it in Assignment 5** - additionally, save it as a copy somewhere in a md/txt file so I can reference it for future use.

- Rule-based checks for every column with a natural business bound (valid ranges, allowed code lists, sign rules)
- Have at least two **cross-table reconciliations** (ex: a recomputed amount versus the stored amount)
- IQR outlier flags on at least two numeric columns with no natural bound, plus one sentence on whether "flagged" means "wrong"

Run everything on both raw and clean tables and save `reports/data_quality_scorecard.csv`: one row per table per stage (raw / clean) with % completeness, % key uniqueness, % type validity, % rule pass, % referential match.

## Part E

Write me a report titled `reports/cleaning_report.md` (1–2 pages) for the Wildcat Capital portfolio committee. It must be built  EXCLUSIVELY from my actual decision log and scorecard (outputs in hw04 folder);  paste the numbers in, DO NOT invent figures. 

Here are the required components: executive summary, cleaning summary table, at least three key judgment calls with justification and risk, a limitations section, and the footer

 include this section for me to edit: `AI-assisted report — reviewed for factual accuracy on [date] by [your name]`

It is crucial that all numbers come from my output. Any fabricated or incorrect number will result in a serious point deduction on my assignment.