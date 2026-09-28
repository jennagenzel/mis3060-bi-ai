## AI Usage Log

### Specification A
You are a BI analyst and are building a data extraction pipeline from scratch.
| Company | Ticker | SEC CIK |
|---|---|---|
| Apple Inc. | AAPL | 0000320193 |
| Microsoft Corporation | MSFT | 0000789019 |
| NVIDIA Corporation | NVDA | 0001045810 |
| JPMorgan Chase & Co. | JPM | 0000019617 |
| Walmart Inc. | WMT | 0000104169 |

 Write a python script that accurately does all of the following in one run:
Sets the SEC EDGAR `User-Agent` header to `"MIS3060 Villanova jgenzel@villanova.edu"` on all HTTP requests
2. For each of the five companies, queries the EDGAR submissions API at `https://data.sec.gov/submissions/CIK{cik}.json` and filters for 8-K filings where the `items` field contains `"2.02"` (Results of Operations)
3. Selects the most recent **four** such filings per company (one per quarter)
4. For each filing, constructs the filing index URL, identifies the earnings press release exhibit (`.htm` file), downloads it, and strips HTML to plain text
5. Extracts from the plain text: quarterly revenue (as a number in millions or billions), diluted EPS, net income, and the reporting period (e.g., "fourth quarter fiscal 2024")
6. Prints the extracted row for each filing as it is processed, in the format: `[Ticker] | [Period] | Revenue: $X | EPS: $X | Net Income: $X`
7. Saves all rows to `hw03/earnings_history.csv` with columns: `company`, `ticker`, `cik`, `filing_date`, `period`, `revenue_reported`, `eps_diluted`, `net_income`
8. Where a field cannot be extracted (regex returns no match), stores the string `"NOT_FOUND"` rather than leaving the cell blank — blank cells and missing data are two different things

Save the script to my hw03 folder and title it "hw03_earnings.py". 

### Specification B
You are a BI analyst and are building a data extraction pipeline from scratch.
| Company | Ticker | SEC CIK |
|---|---|---|
| Apple Inc. | AAPL | 0000320193 |
| Microsoft Corporation | MSFT | 0000789019 |
| NVIDIA Corporation | NVDA | 0001045810 |
| JPMorgan Chase & Co. | JPM | 0000019617 |
| Walmart Inc. | WMT | 0000104169 |

 Write a python script that accurately does all of the following in one run:
1. Sets the same EDGAR `User-Agent` header on all requests
2. For each of the five companies, queries the EDGAR submissions API and filters for 8-K filings where the `items` field contains `"5.02"` (Departure of Directors or Officers) and the `filingDate` is within the past 12 months
3. For each matching filing, downloads the full 8-K text, strips HTML, and extracts: event type (`"departure"` or `"appointment"` or `"both"`), the person's full name, their title, and the effective date of the change
4. If a filing reports multiple events (e.g., one departure and one appointment), creates a separate row for each event
5. Prints each extracted event as it is processed: `[Ticker] | [Date] | [Event Type] | [Name] | [Title]`
6. If no Item 5.02 filings are found for a company in the past 12 months, prints `[Ticker]: No executive events in past 12 months` — this is valid data, not an error
7. Saves all events to `hw03/executive_events.csv` with columns: `company`, `ticker`, `cik`, `filing_date`, `event_type`, `person_name`, `title`, `effective_date`

Save the script to my hw03 folder and title it "hw03_executives.py". 

### Specification C (Timeline Prompt)
Write a Python script that reads `hw03/earnings_history.csv` and `hw03/executive_events.csv`. Do the following:*
>
> *1. For each executive event in the events table, calculate the number of days between the executive event's `filing_date` and the nearest earnings filing date for the same company in the earnings table. Call this `days_to_nearest_earnings`.*
> *2. Add a column `event_timing` that categorizes each executive event as: `'before earnings'` if the event came before the nearest earnings filing, `'after earnings'` if it came after, or `'same week'` if within 7 days of an earnings filing.*
> *3. Save the combined table to `hw03/corporate_events_timeline.csv` with all columns from both source tables plus `days_to_nearest_earnings` and `event_timing`.*
> *4. Print a summary: for each company, list any executive events and whether they occurred before or after the nearest earnings announcement.*
> *5. Print a final count: how many events occurred before vs. after an earnings announcement across all five companies.

### Reflection
Specification A came back with many NOT_FOUND values at first, which prompted me to use Claude to correct it. I found that Walmart's data extractions specifically required iteration.

One thing that the generated script did that I wouldn't have thought to specify in Specification B is identifying and making note of a company with no official date for executive appointment/departure around earnings announcements; for Marianne Lake, it noted that the effective date was not stated in filing (announced 2026-06-25). This was correct and did not need adjustment.