# Data Cleaning Report — Client Portfolio Data

**To:** Wildcat Capital Portfolio Committee  
**Scope:** 8 tables (advisors, benchmarks, clients, calendar, securities, fees, monthly portfolio snapshots, transactions)  
**Sources:** `decision_log.md` (29 issues) and `reports/data_quality_scorecard.csv` (raw vs clean)

## Executive summary

The raw data had problems that would have broken joins and produced wrong client counts, but the clean tables are now structurally reliable. In the clean data every table scores **100% completeness, 100% key uniqueness and 100% type validity**, plus **100% referential match** in every table that has foreign keys. Rule pass is **100%** in every table except `fact_transactions` (**98.002%**).

The biggest gains were in transactions: referential match rose from **81.95% to 100%** and type validity from **91.73% to 100%**, after **197,175** security IDs stored as `'45.0'` were converted and **200** rows for non-existent clients were quarantined. Client key uniqueness rose from **98.02% to 100%** after **25** duplicate clients were removed.

**Use with care:**

- **Returns:** `return_ytd` measures balance growth, including deposits and withdrawals, not investment performance.
- **Dividends:** dividend amounts equal the full position value, not a payout.
- **Advisory fees:** advisory fees disagree between the two tables that record them.

These are flagged, not fixed, because fixing them would mean inventing data.

## Cleaning summary

**Actions taken** (from the decision log; all other issues were reviewed and left as is):

| # | Table / column | Issue (evidence) | Decision |
|---|---|---|---|
| 1 | fact_portfolio_snapshot.return_ytd | 300 values written as text like `'9.28%'` | convert |
| 2 | fact_transactions.shares | 836 Buy rows with negative shares | convert |
| 3 | fact_transactions.client_id | 200 rows with client IDs (2702–3192) not in dim_client | quarantine |
| 4 | fact_transactions.security_id | 197,175 IDs stored as `'45.0'` instead of `'45'` | convert |
| 5 | dim_security.expense_ratio_bps | 219 values stored as `'17.0'` | convert |
| 6 | dim_client (IDs 2501–2525) | 25 clients recorded twice | quarantine |
| 7 | dim_client.state | 78 states spelled out instead of two-letter codes | standardize |
| 8 | dim_client.risk_profile | 76 blank | fill |
| 9 | fact_portfolio_snapshot.return_ytd | 817 returns below −75%, 373 above +300% | flag |
| 10 | fact_portfolio_snapshot.aum | $1,000 appears 420 times | flag |
| 11 | fact_fees.aum_basis | 386 fees charged on $1,000 AUM | flag |
| 12 | fact_transactions.amount (Dividend) | 53,864 dividends equal the full position value | flag |
| 13 | fact_transactions.txn_date | 2,410 transactions after the account's last snapshot | flag |
| 14 | fact_transactions.txn_date | 84,999 rows (28%) on weekends | flag |
| 15 | snapshot vs fees | 7,350 snapshot months with no fee row | flag |
| 16 | Advisory Fee transactions vs fact_fees | 2023: $63.7M vs $42.4M | flag |

Decisions across all 29 issues: convert 4 · standardize 1 · fill 1 · quarantine 2 · flag 8 · leave as is 13. No rows were deleted; removed rows sit in quarantine files.

**Data quality scorecard, raw → clean (%)** (tables that changed; the other four tables were 100% on every applicable metric at both stages):

| Table | Rows | Completeness | Key uniqueness | Type validity | Rule pass | Referential match |
|---|---|---|---|---|---|---|
| dim_client | 2,525 → 2,500 | 99.785 → 100 | 98.02 → 100 | 100 → 100 | 99.39 → 100 | 100 → 100 |
| dim_security | 500 → 500 | 100 → 100 | 100 → 100 | 93.743 → 100 | 91.946 → 100 | 100 → 100 |
| fact_portfolio_snapshot | 129,547 → 129,547 | 100 → 100 | 100 → 100 | 99.982 → 100 | 99.958 → 100 | 100 → 100 |
| fact_transactions | 298,772 → 298,572 | 100 → 100 | 100 → 100 | 91.73 → 100 | 97.908 → 98.002 | 81.95 → 100 |

## Key judgment calls

**1. Fill blank risk profiles as "Balanced" (#8).**

- **Decision:** fill the 76 blanks.
- **Evidence:** all 75 clients actually used in the data are on benchmark 3, which only Balanced clients use (757 of them).
- **Justification:** filling keeps these clients in risk-based analysis. A flag marks every value as filled in, so they can be excluded.
- **Risk:** if benchmark 3 is just a default for unknown clients, 75 clients carry a wrong risk label, which is a suitability and compliance problem.

**2. Quarantine duplicate clients instead of merging them (#6).**

- **Decision:** quarantine 25 clients (IDs 2501–2525).
- **Evidence:** each appears twice, with the last name off by one final letter (e.g. Collins/Collin, Pace/Pacen), and no fact row uses a copy.
- **Justification:** the same person counted twice inflates client counts and advisor books.
- **Risk:** if a copy is really a different person, a real client disappears from advisor books and client counts.

**3. Flag extreme returns instead of correcting them (#9).**

- **Decision:** flag 817 returns below −75% and 373 above +300%.
- **Evidence:** `return_ytd` equals AUM ÷ prior-December AUM − 1, so deposits and withdrawals count as gains and losses.
- **Justification:** the true return can't be rebuilt from this data, so changing values would mean inventing them.
- **Risk:** if flagged returns are used anyway, client performance and advisor alpha are badly misstated in reviews and compensation.

**4. Treat `fact_fees` as the source of truth for fee revenue (#16).**

- **Decision:** flag the advisory-fee transactions and report fee revenue from `fact_fees`.
- **Evidence:** advisory-fee transactions total more than all of `fact_fees` every year (2023: $63.7M vs $42.4M), and per-client yearly totals match only 1.1% of the time.
- **Justification:** nothing in the data shows which table is right.
- **Risk:** if the transactions are correct, fee revenue reported from `fact_fees` is understated (2023: $42.4M vs $63.7M in the transactions).

## Limitations

- **Performance figures:** `return_ytd` and alpha reflect balance growth, not investment skill (#9). Don't use them to rank advisors or report client performance.
- **Dividend income:** all 53,864 dividends equal the full position value (median $48,806) (#12). Exclude them from income and cash-flow totals.
- **Fee revenue:** the two fee sources disagree (#16), and 7,350 snapshot months have no fee row (#15). Revenue may be understated if these are billing gaps.
- **$1,000 balances:** 420 snapshots and 386 fees use a $1,000 balance that looks like a floor; the true balance is unknown (#10, #11).
- **Dates:** 84,999 transactions (28%) fall on weekends (#14), and 2,410 are dated after an account's last snapshot (#13). Holidays are marked as trading days (#27).
- **Residual rule failures:** `fact_transactions` scores 98.002% on rule pass after cleaning. The remaining failures are the advisory-fee rows that don't reconcile with `fact_fees` (#16), which are flagged rather than changed.

---

AI-assisted report — reviewed for factual accuracy on 10/21/2026 by Jenna Genzel
