# Clean data — README

Produced by `scripts/02_clean.py` from the raw files in `hw04/` (raw files are never modified). Decisions follow `decision_log.md`. Every change is listed in `data/audit/value_changes.csv` and every step in `data/audit/cleaning_log.csv`.

## Row counts

| Table | Raw | Clean | Quarantined |
|---|---:|---:|---:|
| dim_advisor | 25 | 25 | 0 |
| dim_benchmark | 8 | 8 | 0 |
| dim_client | 2,525 | 2,500 | 25 |
| dim_date | 1,827 | 1,827 | 0 |
| dim_security | 500 | 500 | 0 |
| fact_fees | 122,197 | 122,197 | 0 |
| fact_portfolio_snapshot | 129,547 | 129,547 | 0 |
| fact_transactions | 298,772 | 298,572 | 200 |

Quarantine files: `data/audit/quarantine_dim_client_duplicates.csv` (25 rows), `data/audit/quarantine_fact_transactions_orphan_clients.csv` (200 rows)

## Relationships (star schema)

| From (many) | To (one) | Key |
|---|---|---|
| fact_fees | dim_client | client_id |
| fact_fees | dim_advisor | advisor_id |
| fact_fees | dim_date | fee_date → date |
| fact_portfolio_snapshot | dim_client | client_id |
| fact_portfolio_snapshot | dim_advisor | advisor_id |
| fact_portfolio_snapshot | dim_benchmark | benchmark_id |
| fact_portfolio_snapshot | dim_date | snapshot_date → date |
| fact_transactions | dim_client | client_id |
| fact_transactions | dim_advisor | advisor_id |
| fact_transactions | dim_security | security_id (blank on cash/fee rows) |
| fact_transactions | dim_date | txn_date → date |
| dim_client | dim_advisor | advisor_id (client's assigned advisor) |
| dim_security | dim_benchmark | benchmark_id |

Grain: fact_fees and fact_portfolio_snapshot = one row per client per month (dated the 1st); fact_transactions = one row per event. Join dates on `dim_date.date`, not `date_id`.

## Column types for a BI tool

Import every file as text first, then set these types. Columns not listed are text.

| Table | Column(s) | Type |
|---|---|---|
| dim_advisor | advisor_id | Whole number (key) |
| dim_advisor | years_experience | Whole number |
| dim_advisor | aum_target_mm | Whole number ($ millions) |
| dim_advisor | certifications | Text - turn OFF 'None'/blank-as-null conversion |
| dim_benchmark | benchmark_id | Whole number (key) |
| dim_client | client_id | Whole number (key) |
| dim_client | age | Whole number |
| dim_client | zip_code | TEXT - never number (leading zeros) |
| dim_client | initial_aum | Decimal (currency) |
| dim_client | client_since | Date (YYYY-MM-DD) |
| dim_client | advisor_id | Whole number (key) |
| dim_client | is_active | True/False |
| dim_client | risk_profile_imputed | Whole number 0/1 |
| dim_date | date_id | Whole number |
| dim_date | date | Date (YYYY-MM-DD) - join key for fact dates |
| dim_date | year/quarter/month/week_of_year | Whole number |
| dim_date | is_month_end/is_quarter_end/is_year_end/is_trading_day | Whole number 0/1 |
| dim_security | security_id | Whole number (key) |
| dim_security | benchmark_id | Whole number (key) |
| dim_security | is_etf | True/False |
| dim_security | expense_ratio_bps | Whole number (blank = not a fund) |
| fact_fees | fee_id | Whole number (key) |
| fact_fees | client_id/advisor_id | Whole number (key) |
| fact_fees | fee_date | Date (YYYY-MM-DD) |
| fact_fees | aum_basis/amount | Decimal (currency) |
| fact_fees | bps_charged | Decimal |
| fact_fees | fee_on_floor_aum | Whole number 0/1 |
| fact_portfolio_snapshot | snapshot_id | Whole number (key) |
| fact_portfolio_snapshot | client_id/advisor_id/benchmark_id | Whole number (key) |
| fact_portfolio_snapshot | snapshot_date | Date (YYYY-MM-DD) |
| fact_portfolio_snapshot | year/month | Whole number |
| fact_portfolio_snapshot | aum | Decimal (currency) |
| fact_portfolio_snapshot | return_ytd/benchmark_return_ytd/active_alpha_ytd/cash_pct | Decimal fraction (0.05 = 5%); a few use scientific notation (9.9e-05) |
| fact_portfolio_snapshot | flag columns | Whole number 0/1 |
| fact_transactions | txn_id | Whole number (key) |
| fact_transactions | client_id/advisor_id | Whole number (key) |
| fact_transactions | security_id | Whole number (key; blank on cash/fee rows) |
| fact_transactions | txn_date | Date (YYYY-MM-DD) |
| fact_transactions | shares/price/amount | Decimal (blank shares/price on cash/fee rows) |
| fact_transactions | flag columns | Whole number 0/1 |

## Flag columns added (0 = no, 1 = yes)

| Table | Column | Rows = 1 | Meaning |
|---|---|---:|---|
| dim_client | `risk_profile_imputed` | 75 | risk_profile was blank and was filled from the client's benchmark (only one profile uses that benchmark) |
| fact_portfolio_snapshot | `return_flow_distorted` | 1,190 | return_ytd < -0.75 or > 3.0; the field is AUM change incl. deposits/withdrawals, so these values are not investment performance (also distorts active_alpha_ytd) |
| fact_portfolio_snapshot | `aum_at_floor` | 420 | aum equals the $1,000 minimum-balance floor; true balance unknown |
| fact_portfolio_snapshot | `fee_missing` | 7,350 | no fact_fees row for this client and month (waiver or billing gap - fee rate unknown) |
| fact_fees | `fee_on_floor_aum` | 386 | fee was charged on the $1,000 floor balance (see snapshot aum_at_floor) |
| fact_transactions | `shares_sign_corrected` | 835 | shares was negative on a Buy; sign removed because amount = abs(shares) x price |
| fact_transactions | `dividend_is_position_value` | 53,826 | Dividend amount equals the whole position's market value, not a cash payout; exclude from income totals |
| fact_transactions | `txn_after_account_close` | 2,410 | dated after the client's last monthly snapshot; client is_active=False |
| fact_transactions | `on_non_trading_day` | 84,946 | txn_date falls on a day dim_date marks as non-trading (all are Saturdays/Sundays) |
| fact_transactions | `advisory_fee_unreconciled` | 35,304 | Advisory Fee row whose client-year total does not match fact_fees within 1%; use fact_fees for fee revenue |

## Known limitations (not fixed, with reasons)

1. **return_ytd and active_alpha_ytd are AUM change, not investment performance.** return_ytd = aum / prior-December aum - 1, so deposits and withdrawals count as gains/losses. A time-weighted return cannot be rebuilt because transaction amounts do not reconcile to AUM. Extreme rows are flagged (return_flow_distorted); all rows are affected to some degree, so do not present this field as performance.
2. **Dividend amounts are position values, not payouts.** Every Dividend amount equals shares x price. There is no yield data to derive the real payout, so amounts are unchanged and flagged (dividend_is_position_value). Exclude them from income or cash-flow totals.
3. **Advisory Fee transactions do not match fact_fees.** Totals differ every year and per client-year they agree for about 1% of pairs. There is no way to tell which is right; fact_fees is treated as the source of truth for fee revenue and the transactions are flagged.
4. **$1,000 AUM floor.** AUM sits at exactly $1,000 after large withdrawals and later balances build on it. The true balance is unknown, so values are flagged (aum_at_floor, fee_on_floor_aum), not filled.
5. **Snapshot months without a fee.** About 5% of client-months have no fee row. The rate varies, so the missing fee cannot be rebuilt (fee_missing).
6. **Transactions on weekends.** About 28% of rows of every type fall on Saturday/Sunday. The real date is unknown, so dates are not moved (on_non_trading_day). Monthly reporting is unaffected.
7. **Activity after an account closed.** Transactions continue after the last snapshot for inactive clients. They may be final liquidations, so they are kept and flagged (txn_after_account_close).
8. **Imputed risk profiles.** 75 blank risk profiles were filled as Balanced because their benchmark is used only by Balanced clients. If the firm assigns that benchmark by default, these labels could be wrong; filter on risk_profile_imputed.
9. **is_trading_day means 'weekday'.** Market holidays (e.g. Dec 25) are marked as trading days. There is no holiday calendar in the data to correct it.
10. **Benchmark 6 (MSCI Emerging Markets) is unused.** Kept as reference data; no security or snapshot points to it.
