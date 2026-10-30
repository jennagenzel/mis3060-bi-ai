# Wildcat Star Schema Design

# Part A: Tables and Keys

| Table | Type | Primary key | Foreign keys (column → table[column]) |
|---|---|---|---|
| dim_advisor | Dimension | `advisor_id` | — |
| dim_benchmark | Dimension | `benchmark_id` | — |
| dim_client | Dimension | `client_id` | `advisor_id` → dim_advisor[advisor_id] |
| dim_date | Dimension | `date_id` | — |
| dim_security | Dimension | `security_id` | `benchmark_id` → dim_benchmark[benchmark_id] |
| fact_fees | Fact | `fee_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`fee_date` → dim_date[date] |
| fact_portfolio_snapshot | Fact | `snapshot_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`benchmark_id` → dim_benchmark[benchmark_id]<br>`snapshot_date` → dim_date[date] |
| fact_transactions | Fact | `txn_id` | `client_id` → dim_client[client_id]<br>`advisor_id` → dim_advisor[advisor_id]<br>`security_id` → dim_security[security_id]<br>`txn_date` → dim_date[date] |

## Notes

- Fact dates match `dim_date[date]`, not `dim_date[date_id]`. `fee_date`, `snapshot_date` and `txn_date` are stored as `YYYY-MM-DD` text, and every value matches a value in `dim_date[date]` (2020-01-01 to 2024-12-31). `date_id` is an integer surrogate key (1–1,827), and none of the fact dates match it.
- `fact_transactions.security_id` can legitimately be blank. 101,528 rows have no security: every Deposit (35,956), Withdrawal (29,830) and Advisory Fee (35,742) row. These are cash movements, not trades, so no security is involved. Every Buy, Sell and Dividend row has a `security_id`, and every non-blank value matches `dim_security`.
- `dim_client.client_since` is not a foreign key to `dim_date`. 1,532 of 2,500 clients joined before 2020, which is earlier than the first date in `dim_date`, so this column is left as a plain attribute.
- No other foreign key has blanks or orphans. Each primary key is unique and never blank.
- In all three fact tables, the `advisor_id` on each row is the same as that client's `advisor_id` in `dim_client`.

# Part B: Grain of Each Fact Table

- fact_fees: One row represents the fee charged to one client for one month (dated the first of the month), with a single fee type of Management, Advisory, Custodial or Performance.
- fact_portfolio_snapshot: One row represents one client's account snapshot for one month (dated the first of the month), including AUM, year-to-date return against the benchmark, and cash percentage.
- fact_transactions: One row represents a single transaction in one client's account on one day: a Buy, Sell or Dividend tied to a security, or a Deposit, Withdrawal or Advisory Fee cash movement with no security.

# Part C: Additivity of Numeric Columns

## Measures in the fact tables

| Fact table | Column | Additivity | What it means for summing or averaging |
|---|---|---|---|
| fact_fees | `amount` | Additive | Can be summed across clients, advisors, fee types and months; for example, total fees for 2023 is the sum of every 2023 row. |
| fact_fees | `aum_basis` | Semi-additive | Can be summed across clients for a single month (total AUM billed that month), but not across months, because adding twelve monthly balances counts the same money twelve times; use the average or the latest month instead. |
| fact_fees | `bps_charged` | Non-additive | A rate is never summed; to get an overall rate, use a weighted average (total `amount` × 12 × 10,000 ÷ total `aum_basis`) rather than a simple average of the rates. |
| fact_portfolio_snapshot | `aum` | Semi-additive | Can be summed across clients for one `snapshot_date` (firm AUM that month), but not across months; over time use the month-end/latest value or the average. |
| fact_portfolio_snapshot | `return_ytd` | Non-additive | A percentage return cannot be summed across clients or months; compare it per client and month, or use an AUM-weighted average across clients for the same date. |
| fact_portfolio_snapshot | `benchmark_return_ytd` | Non-additive | A benchmark's percentage return cannot be summed; read it for one benchmark and date, and average only within the same date. |
| fact_portfolio_snapshot | `active_alpha_ytd` | Non-additive | This is `return_ytd` − `benchmark_return_ytd` (true on every row), so like them it cannot be summed; average it (preferably AUM-weighted) across clients for one date. |
| fact_portfolio_snapshot | `cash_pct` | Non-additive | A percentage of the account (between 1% and 8%) cannot be summed; for a firm-wide figure, weight it by `aum` (total cash ÷ total AUM) rather than averaging the percentages. |
| fact_transactions | `amount` | Additive (within `txn_type`) | Can be summed across clients, securities and dates, but only for one `txn_type` at a time; every amount is stored as a positive number, so Deposits and Withdrawals (or Buys and Sells) must be given opposite signs before netting them. |
| fact_transactions | `shares` | Semi-additive | Can be summed across clients and dates for one security and one `txn_type` (total shares of AFDV bought), but not across securities, because shares of different securities are not comparable; it is also blank for cash transactions, and on Dividend rows it is not a number of shares traded, so Dividend rows should be left out when totaling shares. |
| fact_transactions | `price` | Non-additive | A per-share price is never summed; use the price on a single trade, or a share-weighted average (total `amount` ÷ total `shares`) for one security. |

## Numeric columns in the fact tables that are not measures

These columns contain numbers but are identifiers, date parts or flags, so summing or averaging them gives no meaningful result.

- Keys: `fee_id`, `snapshot_id`, `txn_id` (primary keys); `client_id`, `advisor_id`, `benchmark_id`, `security_id` (foreign keys). Count them, or count distinct values; never sum or average them.
- Date parts: `fact_portfolio_snapshot.year` and `fact_portfolio_snapshot.month`. These are for grouping and filtering; their total represents nothing.
- Flags (0/1): `fact_portfolio_snapshot.is_return_suspect` and `fact_transactions.is_post_departure_txn`. Their sum is only a count of flagged rows, and their average is the share of rows flagged; use them as filters, not measures.
- Category that looks numeric: `fact_portfolio_snapshot.account_type` contains the value `529` (a type of college savings account), but it is text alongside `IRA`, `Roth IRA`, `Taxable` and `Trust`.

## Numeric attributes in the dimension tables that should never be summed

These describe a single advisor, client, date or security. Adding them across rows double-counts or produces a meaningless total, especially once they are joined to a fact table and repeated on every fact row.

- dim_advisor: `advisor_id`, `years_experience` (adding experience across advisors means nothing; average it per advisor), `aum_target_mm` (a goal for one advisor; repeated on every fact row after a join, so summing it inflates the target).
- dim_benchmark: `benchmark_id`.
- dim_client: `client_id`, `age` (average it across distinct clients, never sum it), `zip_code` (a code with leading zeros; treat it as text), `initial_aum` (a one-time starting balance; summing it after joining to monthly facts counts it once per month), `advisor_id`, `is_active` (a flag; its sum is only a count of active clients).
- dim_date: `date_id`, `year`, `quarter`, `month`, `week_of_year` (for grouping only), and the flags `is_month_end`, `is_quarter_end`, `is_year_end`, `is_trading_day` (use them as filters).
- dim_security: `security_id`, `benchmark_id`, `is_etf` (a flag), `expense_ratio_bps` (a rate; average it per security, or weight it by holdings; blank for non-ETFs).

# Part E: Relationships and Design

My Power BI model has 8 tables and 13 relationships. Every relationship is many-to-one with a single filter direction, meaning each dimension filters the fact tables. 12 relationships are active and 1 is inactive.

Conformed dimensions: `dim_date`, `dim_client` and `dim_advisor` connect to all three fact tables. Because they're shared, one slicer on any of them filters fees, snapshots and transactions at the same time.

## (a) Why do some transactions have no `security_id`? Is that a defect?

101,528 transactions have no `security_id`, and all of them are Deposits, Withdrawals or Advisory Fees. These move cash into or out of an account; they aren't trades in a stock or fund, so there's no security to record. Every Buy, Sell and Dividend has a `security_id`, and all of those IDs match a security in `dim_security`.

This is not a defect. It's how the data is supposed to look. In Power BI, these rows show up as one `(Blank)` ticker totaling $3,573,887,227.67, which equals exactly the deposits, withdrawals and fees added together. That proves no broken keys are hiding in the blank row.

## (b) Which `advisor_id` relationships did you keep active, and why?

Active: the three direct links from each fact table to `dim_advisor`.
Inactive: the link from `dim_client` to `dim_advisor`.

If all four were active, Power BI would have two routes from `dim_advisor` to each fact table: one direct, and one through `dim_client`. Power BI only allows one active route, so I had to turn one off. I kept the direct links because:
- Each dimension then filters each fact table in one step, which is what a star schema should do.
- It takes only one inactive relationship instead of three.

This choice doesn't change any numbers, because every fact row's `advisor_id` matches the advisor listed for that client in `dim_client`.

## (c) Which date column did you join on, and why?

I joined each fact table's date (`fee_date`, `snapshot_date` and `txn_date`) to `dim_date[date]`, not `dim_date[date_id]`.

A join only works when both columns hold the same kind of value. The fact tables store real dates like `2020-01-01`, and so does `dim_date[date]`. `date_id` is just a row number from 1 to 1,827. Every fact date matches a value in `dim_date[date]`, and none match a `date_id`. I also marked `dim_date` as the date table using the `date` column, which Power BI needs for its date functions.

## (d) Star or snowflake? Does any dimension connect to another, and did you keep it?

Yes, two dimensions connect to other dimensions:
- `dim_security` → `dim_benchmark`: kept, and active. It's the only way to link a transaction to its benchmark (transaction → security → benchmark). It doesn't create a second route, because `fact_transactions` can only reach `dim_benchmark` through `dim_security`.
- `dim_client` → `dim_advisor`: kept, but inactive, for the reason in (b).

So the model is mainly a star: three fact tables sharing the same dimensions, with one small snowflake branch, `dim_security` → `dim_benchmark`.

I also chose not to connect `dim_client[client_since]` to `dim_date`. 1,532 of the 2,500 clients joined before 2020, and the date table only covers 2020 to 2024, so most of those dates would have nothing to match.

# Part F: Reflection

| # | Fact table | Business question | One visual, no DAX? |
|---|---|---|---|
| 1 | `fact_fees` | How much fee revenue did each advisor region earn each year? | Yes |
| 2 | `fact_portfolio_snapshot` | How much money (AUM) did we manage at the end of each year? | No |
| 3 | `fact_transactions` | How much net new money did each advisor bring in (deposits minus withdrawals and advisory fees) each quarter? | No |

## Question 1: Fee revenue by region and year (`fact_fees`)

Can it be answered in one visual? Yes.

Build a matrix with `dim_advisor[region]` on the rows, `dim_date[year]` on the columns, and Sum of `fact_fees[amount]` as the value.

This works because fees can be added up. Each row is one month's fee for one client, so adding the rows gives the total fees for any region, year or combination. Power BI's default Sum gives the right answer, which means that no DAX is required.

## Question 2: Year-end AUM (`fact_portfolio_snapshot`)

Can it be answered in one visual? No.

The problem: `aum` is a balance (like a bank account balance), and each client has a snapshot every month. If you put `year` on a visual and Sum `aum`, Power BI adds all 12 monthly balances together, so the total comes out about 12 times too high. You only want the balance from the last month of the year.

The date table can't fix this on its own. Every snapshot is dated the 1st of the month (for example, 2024-12-01), so the `is_year_end` flag in `dim_date`, which is only true on December 31, never matches a snapshot. Power BI's default Sum gives a wrong answer, and the only ways to get the right one are a DAX measure or a filter on `month = 12` that the reader has to know to add. Nothing in the model tells them to add it, so the visual is easy to get wrong.

Schema fix: add a column to `fact_portfolio_snapshot` called `is_year_end_snapshot`, set to 1 on every December snapshot and 0 on all other months. Only clients still with the firm in December have a December snapshot, so the 175 clients whose snapshots stop before December 2024 are not counted after they leave. A visual can then filter to `is_year_end_snapshot = 1`, and a normal Sum of `aum` gives the correct year-end total.

## Question 3: Net new money by advisor and quarter (`fact_transactions`)

Can it be answered in one visual? No.

The problem: every `amount` is stored as a positive number, even for withdrawals. A $1,000 deposit and a $1,000 withdrawal are both stored as 1,000. Summing them gives $2,000 instead of the correct $0, and the visual has no column it can use to subtract withdrawals. Getting the right number needs a DAX measure that subtracts withdrawals and advisory fees from deposits.

Schema fix: Add a column to `fact_transactions` called `net_cash_amount`, and this column stores money coming in as positive and money going out as negative:
- Deposit: positive (+1,000)
- Withdrawal and Advisory Fee: negative (−1,000)
- Buy, Sell and Dividend: 0, since these don't add or remove the client's money

A matrix with `dim_advisor[last_name]` on the rows, `dim_date[quarter]` on the columns, and Sum of `net_cash_amount` then answers the question directly.
