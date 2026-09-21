### 2A — Known-Answer Benchmarks
| Check | Expected | Your Script Produced | Match? | Notes | Claude Prompt & Output |
|---|---|---|---|---|---|
| Dataset shape | (298772, 9) | Rows x Columns: 298772 x 9 | Yes | N/A | N/A |
| Null count — `security_id` | 101,597 | Missing Values Per Column: 'security_id' 101,597 | Yes | N/A | N/A |
| Null count — `amount` | 0 | Missing Values Per Column: 'amount'  0 | Yes | N/A | N/A |
| Unique `txn_type` values | 6 | UNIQUE ENTITY COUNTS: Unique clients:2700 Unique advisors:25 Unique securities 500 | No | The script did not display the unique txn_type values | CLAUDE PROMPT: "I just looked at the output from the script. "Unique `txn_type` values" is 6. I do not see that reflected in the script."<br>OUTPUT:"Fixed and re-verified — hw02_eda.py on your computer now includes txn_type in the unique-count section (item 7), alongside clients, advisors, and securities:<br> UNIQUE ENTITY COUNTS<br>Unique clients:    2700<br>Unique advisors:   25<br>Unique securities: 500<br>Unique txn_types:  6<br>This is written to both the console output and hw02_profile.txt. Go ahead and re-run the script in your .venv — you should see the same result." |
| Count of `Buy` transactions | 83,556 | 83,556 | Yes | N/A | N/A |
| `txn_date` data type | object | 'txn_date' datetime64[us] | No | The script incorrectly classified the data type for 'txn_date' | CLAUDE PROMPT: "Under 'column names and data types', the values are wrong.For instance, txn_date should be object, not datetime64[us]."<br>OUTPUT: "That makes sense — the script currently converts txn_date to a real datetime type at load time (for convenience in the date-range calculation), which changes its dtype before item 3 reports it. Since item 3 should reflect the data as it actually comes from the CSV, I'll load it without forcing that conversion, and only parse dates separately for the min/max calculation in item 8. Let me fix that.txn_date now correctly shows as object under item 3, matching the raw CSV data (the date parsing for item 8's earliest/latest calculation is now done separately, without changing what item 3 reports). Let me quickly confirm item 8 still works correctly.Both fixed and verified. hw02_eda.py on your computer now reports txn_date as object in item 3 (matching the raw CSV), while item 8 (earliest/latest date) still correctly computes 2020-01-01 to 2024-12-30 by parsing dates on the fly without changing the reported dtype. Go ahead and re-run it — everything else stayed the same." |
| Earliest `txn_date` | 2020-01-01 | Earliest txn_date: 2020-01-01 00:00:00 | Yes | N/A | N/A |
| Latest `txn_date` | 2024-12-30 | Latest txn_date:   2024-12-30 00:00:00 | Yes | N/A | N/A |
| Duplicate `txn_id` count | 0 | Duplicate txn_id count: 0 | Yes | N/A | N/A |
| Mean `amount` | $54,075.17 | Mean amount: 54075.17 | Yes | N/A | N/A |
| Median `amount` | $41,220.48 | Median amount:41220.49 | Yes | Results differ by $0.01, which I assume is a rounding issue | N/A |
| Skewness of `amount` | 1.15 | Skewness amount: 1.1463 | Yes | The script did not round the result to 2 decimal places | N/A |
| Correlation `shares`–`amount` | 0.65 | 0.65 | Yes | N/A | N/A |
| Correlation `price`–`amount` | 0.64 | 0.64 | Yes | N/A | N/A |
| Correlation `shares`–`price` | 0.00 | 0.00 | Yes | N/A | N/A |
| Negative `shares` count (Buy only) | 836 | 836 | Yes | N/A | N/A |
| Profile file created | Yes | c:\MIS3060\mis3060-bi-ai\hw02\hw02_eda.py:270: MatplotlibDeprecationWarning: vert: bool was deprecated in Matplotlib 3.11 and will be removed in 3.13. Use orientation: {'vertical', 'horizontal'} instead.<br>  ax.boxplot(data_by_type, vert=False, tick_labels=type_order,<br>c:\MIS3060\mis3060-bi-ai\hw02\hw02_eda.py:297: UserWarning: Creating legend with loc="best" can be slow with large amounts of data.<br>  fig.tight_layout()<br>c:\MIS3060\mis3060-bi-ai\hw02\hw02_eda.py:298: UserWarning: Creating legend with loc="best" can be slow with large amounts of data.<br>  fig.savefig(os.path.join(CHARTS_DIR, "scatter_shares_amount.png"), dpi=150)<br>Charts saved to: c:\MIS3060\mis3060-bi-ai\hw02\charts | No | Script does not identify a list number (only goes up to 14) and does not display a yes or no value to indicate whether a profile file was created (on my end I can see that it was) | CLAUDE PROMPT:"It looks like the list items in the script stop at item 14. I do not see any item indicating the status of  "Profile file created" or the "Chart files created (3)" (yes or no). Please include all 17 items on the list, and make sure each are answered accurately and in its entirety."<br>OUTPUT: "Good catch — the script does perform all 17 steps, but items 1, 15, 16, and 17 don't get the same clearly labeled header/confirmation treatment as items 2–14. Let me restructure the whole output so every one of the 17 items has its own visible, consistently formatted section with an explicit status line.All 17 items now print with clear, consistently formatted headers and explicit status confirmations, updated directly on your computer at hw02_eda.py." |
| Chart files created (3) | Yes | c:\MIS3060\mis3060-bi-ai\hw02\hw02_eda.py:270: MatplotlibDeprecationWarning: vert: bool was deprecated in Matplotlib 3.11 and will be removed in 3.13. Use orientation: {'vertical', 'horizontal'} instead.<br>  ax.boxplot(data_by_type, vert=False, tick_labels=type_order,<br>c:\MIS3060\mis3060-bi-ai\hw02\hw02_eda.py:297: UserWarning: Creating legend with loc="best" can be slow with large amounts of data.<br>  fig.tight_layout()<br>c:\MIS3060\mis3060-bi-ai\hw02\hw02_eda.py:298: UserWarning: Creating legend with loc="best" can be slow with large amounts of data.<br>  fig.savefig(os.path.join(CHARTS_DIR, "scatter_shares_amount.png"), dpi=150)<br>Charts saved to: c:\MIS3060\mis3060-bi-ai\hw02\charts | No | Script does not identify a list number (only goes up to 14) and does not display a yes or no value to indicate whether the three charts were created and saved (on my end I can see that they were) | CLAUDE PROMPT: "It looks like the list items in the script stop at item 14.  For instance, I do not see any item indicating the status of  "Profile file created" or the "Chart files created (3)" (yes or no). Please include all 17 items on the list, and make sure each are answered accurately and in its entirety."<br>OUTPUT:"Good catch — the script does perform all 17 steps, but items 1, 15, 16, and 17 don't get the same clearly labeled header/confirmation treatment as items 2–14. Let me restructure the whole output so every one of the 17 items has its own visible, consistently formatted section with an explicit status line.All 17 items now print with clear, consistently formatted headers and explicit status confirmations, updated directly on your computer at hw02_eda.py." |

### 2B — Explain the Code and Output
1. Did Claude's predicted outputs (from Prompt 1) match what you actually saw in the terminal? List any discrepancies.

Surprisingly, Claude's predicted outputs from Prompt 1 mostly match what I saw in the terminal. The only discrepancies I noticed were the same ones that were in question 2A. For instance, items 1, 15, 16, and 17 were not present within the terminal output. I also noticed that Claude classified all of the column names as object, while not all were classified as object in the terminal output.

2. What did Claude flag as potentially unexpected or worth investigating (from Prompt 2)?

Claude flagged the negative shares on "buy" transactions. 836 of the 83,556 Buy rows had negative share counts (with a minimum of -499.63). Claude noted that logically a buy shouldn't have negative shares and recommended to pull those rows and check whether they're mislabeled reversals/corrections, a bug in how the data was generated, or something else. Claude also detected a skew in the Advisory Fee amount. The mean of $7,375 and median of only $859 for txn_type indicates a much bigger mean/median gap than any other category; Claude suggests that a handful of unusually large fee transactions are pulling the average up and to pull the max and top few Advisory Fee amounts directly to see if one or two rows are out of line (possible data entry error) before citing "average fee" anywhere. Claude also flagged the data shape, noting unusual uniform-looking ranges on shares (~±500), price ($10–$500), and security_id (1–500). Claude noticed that this pattern points to synthetic/simulated data rather than organic data. 

3. Did Claude mention the 101,597 null values in `security_id`? What explanation did it give?

Claude did mention the 101,597 null values in 'security_id', as well as in 'shares' and 'price'. Claude noticed that these three have exactly 101,597 nulls while every other column is 0. Claude says it's not random, and that it equals the combined row count of Deposit + Withdrawal + Advisory Fee transactions (35,981 + 29,850 + 35,766 = 101,597). It makes sense; those transaction types don't involve a security, so there's nothing to put in those three columns.

4. Did Claude flag the `txn_date` column as a concern? Why would that matter for a time-series analysis?

Claude did not flag the 'txn_date' column as a concern, although it should've. It would matter for a time-series analysis since the rows in the file aren't in date order, so in order to perform a time series analysis they would need to be sorted in chronological order. 

5. Open your three chart files. Does what you see in each image match Claude's explanation of that section of the output? Note any differences.

What I see in each image does match Claude's explanation of that section of the output. I cross-checked the paragraph that Claude provided when explaining each of the graphs, and it matches exactly what is on each graph.

6. Paste one follow-up question you asked Claude, and Claude's answer.

QUESTION:"What other information would be critical to know about this dataset before running an in depth analysis?"

CLAUDE'S RESPONSE: "Given everything we've found so far, here's what I'd want nailed down before treating this as ready for serious analysis:

A data dictionary or schema documentation. The fact_ prefix on the filename strongly suggests this came from a star-schema design with matching dimension tables (dim_clients, dim_advisors, dim_securities) somewhere else in the project. Right now you only have IDs — you can't tell what asset class a security is, what segment or risk tier a client falls into, or what team/branch an advisor belongs to. Any "who/what is driving this" business question needs those dimension tables joined in.

What negative shares actually means in this business's data model. We flagged 836 negative-share "Buy" rows earlier but never got a business explanation for them. Before deciding whether to exclude, correct, or interpret them, you need to know whether negative shares represent a sign convention for something specific (a correction, a reversal, a short-cover) or whether they're a genuine defect. That's not something the data alone can answer — it needs a source-system explanation or a documented business rule.

Whether amount is gross or net, and what currency it's in. We haven't confirmed the exact formula tying shares, price, and amount together (fees, taxes, rounding could all sit inside or outside that number), and there's no currency field — if this represents multiple markets or client jurisdictions, assuming a single currency could be wrong.

Trade date vs. settlement/booking date. txn_date is just one date field — for time-series or lag-sensitive analysis, whether that's the date the trade executed, the date it settled, or the date it was recorded in the system matters a lot, and can shift results by a day or more.

Whether this is real data, a sample, or synthetic/simulated. This one's important given what we've already seen: uniform value ranges capped at round numbers, transactions occurring on every single calendar day including weekends (real markets are closed then), and independence between shares and price. All of that points toward simulated data generated for the assignment rather than an organic extract. That's fine for a class exercise, but it means you shouldn't draw real-world market conclusions from patterns (or the lack of them) in this data — worth stating as an assumption up front in your report rather than discovering it as a surprise later.

Whether the extract is complete or a snapshot. Is this every transaction from 2020–2024, or a sample/subset? If it's a subset, sampling method matters for whether your summary stats generalize.

Data refresh/versioning. Is this a one-time static file for the assignment, or something that gets refreshed? If you're building anything meant to be reused (a dashboard, a repeatable script), knowing whether the underlying CSV will change matters for how you design it."

### 2C — Business Check & Cross-Validation
1. `security_id`, `shares`, and `price` are all null in exactly 101,597 rows. Looking at the `txn_type` value counts, which three transaction types would you expect to have no security — and why? Do the counts add up to 101,597?

Looking at the 'txn_type' value counts, I would expect Deposit, Withdrawal, and Advisory Fee to have no security; none of these categories involve buying or selling a specific holding. A deposit or withdrawal is simply moving cash in or out of the account, and an advisory fee is a charge for the advisor's services (not a trade). However, buy, sell, and dividend are tied to a specific security, meaning security_id, shares, and price should be populated. Deposit (35,981) + Withdrawal (29,850) + Advisory Fee (35,766) = 101,597, and it matches the null count of security_id, shares, and price.


2. There are 83,556 Buy transactions and 59,755 Sell transactions. What does it mean for a wealth management firm to have significantly more Buys than Sells over a five-year period?

A wealth management firm having significantly more Buys than Sells over a five year period means there is net portfolio growth, or that clients put more money into their investments than they withdrew. This also would make sense in context of the dataset; it matches deposits being higher than withdrawals, since more cash coming in leads to more buying. 

3. The `txn_date` column is stored as a string (type `object`) rather than a date. If Claude Cowork generated code to compute the average number of days between transactions, what would go wrong if the dates remained as strings?

If Claude generated code to compute the average number of days between transactions and the dates remained as strings, there would be an error message. If the dates stay as plain text then the code can't perform mathematical commands on it, as trying to subtract one date from another would cause an error. The fix to this would be to convert the column to real dates, which allows Claude to correctly calculate the average number of days between transactions.

4. Wildcat Capital has 2,700 clients served by 25 advisors. Is that ratio — roughly 108 clients per advisor — plausible for a registered investment advisory firm?

No, 108 clients per advisor is likely not plausible for a registered investment advisory firm. Having over 100 clients does not allow the advisor to have enough time to properly monitor each account, provide personalized and ongoing advice, and to truly have the client's best interest in mind. 108 clients is simply too many for one advisor to properly manage on their own on a day-to-day basis.

5. 836 `Buy` transactions have negative `shares` values (as low as −499.63), while every other transaction type in the dataset has only positive share values. What are two plausible business explanations for a negative share count on a Buy transaction (for example, a data-entry sign error versus a legitimate correction or reversal entry), and what would you do next to determine which explanation is more likely?

One plausible business explanation for the negative share count on a Buy transaction is an error with data entry. It is possible that whatever process is used to input data, whether that be manual or automated, accidentally recorded some transactions with a negative sign where it shouldn't be. The sign would either need to be flipped on these records or these records would need to be excluded before analysis.

Another plausible explanation is that these records are intentional and are a reversal entry to fix existing mistakes. These negative values may be netting out a firm's mistake, such as if an entry was accidentally recorded twice (and the negative record is eliminating the duplicate entry).

To determine which explanation is more likely, I would first check if each negative row has a matching positive one nearby (same client, same security, around the same time, etc.); if it does, the record is probably a correction. I would also check to see if the negative values are spread across the dataset randomly or grouped together by advisor, security, or date. Random and scattered points indicate that a data entry error is more likely.

**Cross-validation.** The count of `Buy` transactions (83,556) is a central metric in any portfolio activity analysis. Verify it using two independent approaches:

- **Prompt A:** *"Write Python to count rows in fact_transactions.csv where txn_type equals exactly 'Buy'."*
- **Prompt B:** *"Write Python to count the total rows in fact_transactions.csv, then subtract the count of rows where txn_type is Sell, Deposit, Withdrawal, Dividend, or Advisory Fee."*

Run both scripts from the VS Code terminal. In `hw02/validation.md`:

6. What did each script return?

PROMPT A: *"Write Python to count rows in fact_transactions.csv where txn_type equals exactly 'Buy'."*
Claude Output: "I found fact_transactions.csv in your 02_Data/raw folder and saved count_buy_transactions.py at the root of your hw02 folder. It uses csv.DictReader to check txn_type == 'Buy' exactly (case-sensitive, no partial matches)."

Script Output: Number of 'Buy' transactions: 83556

PROMPT B: *"Write Python to count the total rows in fact_transactions.csv, then subtract the count of rows where txn_type is Sell, Deposit, Withdrawal, Dividend, or Advisory Fee."*
Claude Output: "Saved as count_buy_by_subtraction.py in your hw02 folder. Results: Total rows: 298,772. Excluded (Sell/Deposit/Withdrawal/Dividend/Advisory Fee): 215,216. Remaining: 83,556 — which matches the direct 'Buy' count from before, confirming there are no other/unexpected txn_type values in the file."

Script Output: Total rows: 298772
Excluded rows (Sell/Deposit/Withdrawal/Dividend/Advisory Fee): 215216
Remaining rows (should equal 'Buy' count): 83556


7. Do the results agree? If not, which one is wrong and why?

The results agree; both prompts yielded an output of 83556. 

8. Why is it useful to verify a count using subtraction rather than direct filtering?

Verifying a count using subtraction rather than direct filtering is useful since it serves as a verification method to ensure the answer is correct; if direct filtering is used, there is a chance of an error in filtering the data and/or calculating the answer. Subtraction uses a completely different approach to arrive at the same answer, which creates confidence that the answer is correct.

