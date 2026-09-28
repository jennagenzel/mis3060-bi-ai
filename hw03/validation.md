## Validation

### 5A — Known-Answer Check: Earnings

| Check | Official Source | Your CSV | Match? |
|---|---|---|---|
| [Apple] [Q2 2026] Revenue | 111,184 million  | 111,184 million | Yes |
| [Apple] [Q2 2026] EPS Diluted | 2.01 | 2.01 | Yes |

Source: https://www.sec.gov/Archives/edgar/data/320193/000032019326000011/a8-kex991q2202603282026.htm


### 5B — Known-Answer Check: Executive Events

| Check | News Source Confirms? | Notes |
|---|---|---|
| John Ternus, New Apple CEO | Yes | Announced April 20th, 2026 for a September 1st start  |
| Appointment to CEO | Yes | N/A |
| 9/1/2026 |Yes | N/A |

Source:https://www.apple.com/newsroom/2026/04/tim-cook-to-become-apple-executive-chairman-john-ternus-to-become-apple-ceo/

### 5C — Cross-Validation: Earnings via Yahoo Finance

| Metric | From 8-K text extraction | From yfinance | Match? |
|---|---|---|---|
| Revenue |111,184 million | 111.18 billion | Yes |
| Net Income |29,578 million | 29.58 billion |Yes |

Source:https://finance.yahoo.com/quote/AAPL/financials/


### 5D — Pipeline Integrity Checks

| Check | Expected | Actual | Pass/Fail |
|---|---|---|---|
| `earnings_history.csv` row count | Up to 20 (5 companies × 4 quarters) |20 rows | Pass |
| `executive_events.csv` row count | At least 0 (document actual) |30 rows | Pass |
| `corporate_events_timeline.csv` created | Yes | Yes | Pass |
| Rows with all three fields `"NOT_FOUND"` | 0 (investigate if > 0) | 0 | Pass |