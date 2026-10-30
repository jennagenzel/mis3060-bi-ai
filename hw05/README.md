# HW5: Wildcat Capital Star Schema

This assignment models the Wildcat Capital data as a star schema. It identifies every primary and foreign key, states the grain of each fact table, classifies every measure by additivity, and builds the model in Power BI. The model is the foundation for the DAX measures in Assignment 6.

## Structure

```
hw05/
├── README.md                      This file
├── star_design.md                 Written answers for Parts A, B, C, E and F
├── checks_keys.py                 Code proof for Parts A and B (keys and grain checks)
├── Specifications.md              The spec used to create checks_keys.py
├── dim_advisor.csv                25 advisors
├── dim_benchmark.csv              8 performance benchmarks
├── dim_client.csv                 2,500 clients
├── dim_date.csv                   1,827 days, 2020-01-01 to 2024-12-31
├── dim_security.csv               500 securities and ETFs
├── fact_fees.csv                  122,197 monthly fee charges
├── fact_portfolio_snapshot.csv    129,547 monthly account snapshots
├── fact_transactions.csv          298,572 trades, income, cash flows and fee debits
└── powerbi/
    ├── hw05.pbix                  Power BI model (Part D)
    └── model_view.png             Screenshot of the full Model view (Part D)
```

What each part of the assignment is answered in:

| Part | Topic | Where |
|---|---|---|
| A | Keys | `star_design.md`, Part A; proven in `checks_keys.py` |
| B | Grain | `star_design.md`, Part B; uniqueness checked in `checks_keys.py` |
| C | Measures | `star_design.md`, Part C |
| D | Power BI model | `powerbi/hw05.pbix` and `powerbi/model_view.png` |
| E | Relationships and design questions | `star_design.md`, Part E |
| F | Reflection | `star_design.md`, Part F |

## How to run

### Key and grain checks (Parts A and B)

From the `hw05` folder, with the virtual environment activated (`..\.venv\Scripts\Activate.ps1` in PowerShell), run:

```
python checks_keys.py
```

The script needs only pandas (included in `requirements.txt`). It loads the eight CSV files and prints PASS or FAIL for each check:
- Row counts match the handout
- Every primary key is unique and never blank
- Every foreign key matches its target table, with `security_id` blank only on Deposit, Withdrawal and Advisory Fee rows
- Fact dates match `dim_date[date]` and not `dim_date[date_id]`
- Each fact table's grain is unique: one row per client per month for fees and snapshots, and one row per `txn_id` for transactions

It ends with a summary (currently 40 passed, 0 failed) and exits with an error code if any check fails.

### Power BI model (Part D)

1. Install Power BI Desktop (Windows).
2. Open `powerbi/hw05.pbix`. The data is imported into the file, so the model, relationships and report page open without needing the CSV files.
3. To view the model, click Model view (third icon on the left rail). To view the checks, click Report view (first icon).
4. To refresh the data from the CSV files: the file was built on the class virtual desktop, so its data sources point to a folder there (`Wildcat Capital Clean`). On another computer, go to Home → Transform data → Data source settings, choose Change Source for each file, and point it to the matching CSV in this `hw05` folder. Then click Refresh.

`star_design.md` is plain Markdown. Open it in VS Code and press Ctrl+Shift+V to see the formatted preview.

### The model

- 8 tables: 3 fact tables (`fact_fees`, `fact_portfolio_snapshot`, `fact_transactions`) and 5 dimensions (`dim_advisor`, `dim_benchmark`, `dim_client`, `dim_date`, `dim_security`).
- 13 relationships, all many-to-one with single cross-filter direction. 12 are active. `dim_client[advisor_id]` → `dim_advisor[advisor_id]` is inactive because it would create a second path to `dim_advisor` (explained in Part E, question b).
- Fact dates (`fee_date`, `snapshot_date`, `txn_date`) join to `dim_date[date]`, not `dim_date[date_id]`.
- `dim_date` is marked as the date table on the `date` column.
- No DAX measures. The row-count checks use Power BI's built-in Count.

### Checks on the report page

- Row counts: one card per table showing Count of its primary key. All eight match the handout.
- Blank members: a table of `dim_security[ticker]` with Sum of `fact_transactions[amount]`. It has one `(Blank)` row for the cash transactions, which have no security.
- Slicer: a slicer on `dim_advisor[last_name]`. Selecting an advisor filters all three fact tables.

## Claude Code findings

I used Claude Code to check the CSV files and the saved `.pbix` against the assignment directions. It found:

Data checks
- All eight files match the handout's row and column counts exactly.
- One file was downloaded as `fact_transactions (1).csv`. It was renamed to `fact_transactions.csv` to match the handout.
- Every primary key is unique and never blank.
- Every foreign key matches a row in the table it points to. The only blanks are expected ones (below).

Things that shaped the design
- Fact dates are calendar dates (for example `2020-01-01`) and match `dim_date[date]`. None match `dim_date[date_id]`, which is a row number from 1 to 1,827.
- 101,528 transactions have no `security_id`. All of them are Deposits, Withdrawals or Advisory Fees, which move cash and involve no security. In Power BI they form one `(Blank)` ticker totaling $3,573,887,227.67, exactly the sum of those three transaction types, so no broken keys are hidden in it.
- Every fact row's `advisor_id` matches that client's `advisor_id` in `dim_client`, so the choice of which advisor relationship to keep active doesn't change any totals.
- 1,532 of 2,500 clients have a `client_since` date before 2020, outside the date table, so `client_since` was not joined to `dim_date`.

Measure findings (Part C)
- Every `fact_transactions[amount]` is positive, even for Withdrawals and Sells, so amounts can only be netted after giving one side a negative sign.
- Fee `amount` always equals `aum_basis × bps_charged ÷ 10,000 ÷ 12`, and `active_alpha_ytd` always equals `return_ytd − benchmark_return_ytd`.
- `aum` and `aum_basis` are monthly balances, so summing them across months overstates them.
- Every snapshot and fee is dated the 1st of the month, so the month-end and year-end flags in `dim_date` never match a snapshot.
- 175 clients' snapshots stop before December 2024 (clients who left), which matters for year-end AUM (Part F, question 2).

Power BI model checks (from the saved `hw05.pbix`)
- All 13 relationships are many-to-one with single direction, with exactly one inactive.
- Key columns are whole numbers and date columns are dates.
- `dim_date` is marked as the date table on `date`.
- The file contains no DAX measures.
