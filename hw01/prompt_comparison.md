## Homework 1, Part 3: Prompt Engineering Comparison

## QUESTION: What are the most important metrics for measuring credit risk in a consumer loan portfolio?

## Version 1: What are the most important metrics for measuring credit risk in a consumer loan portfolio?

Claude response: Consumer loan portfolio credit risk is typically measured across a few different dimensions: how likely borrowers are to default, how much is lost when they do, and how the portfolio's risk is
trending over time. Delinquency and default rates are the starting point. Lenders track delinquency buckets (30/60/90+ days past due) as leading indicators,
along with the default rate or charge-off rate, which shows what percentage of the portfolio has actually stopped paying and been written off as uncollectible. The roll rate — the percentage of accounts that 
move from one delinquency bucket to a worse one — helps show whether the problem is getting better or worse before it fully shows up in charge-offs. Loss severity matters alongside frequency. Loss given default
(LGD) captures what percentage of the outstanding balance is actually lost after recoveries, collateral liquidation, or collections efforts, while the recovery rate is its mirror image.

Evaluation: Claude's response does a good job of providing an overview of of credit risk basics, like indicating how often borrowers miss payments, how money is  lost when they default, and how loans move from minor 
late payments to major losses. However, the response lacks detail, some of which might've come after the 150 words. No context was provided in the prompt, and I found the response to be too generic to be truly beneficial for a BI analyst.


## Version 2: You are a senior credit risk analyst preparing for a quarterly report to the board and other key stakeholders. What are the most important metrics for measuring credit risk in a consumer loan portfolio?

Claude response: For a board-level credit risk report on a consumer loan portfolio, the metrics that matter fall into a few natural groups, and a good report usually shows trends over multiple quarters rather than single points in time, since direction and rate 
of change often matter more to the board than the absolute number. Portfolio performance and delinquency: the core health indicators are delinquency rates by bucket (30, 60, 90+ days past due), the net charge-off rate, and the non-performing loan ratio. Roll rate
analysis — what share of accounts in one delinquency bucket "roll" into the next — is especially useful because it's a leading indicator of where losses are headed before they show up in charge-offs. Recovery rate on charged-off accounts rounds this out. Reserve adequacy.
The allowance for credit losses (ACL) and its coverage ratio (reserves as a percentage of total loans or of non-performing loans) show whether

Evaluation: This approach does a great job of framing the question from an expert perspective. It organizes key metrics that would matter to stakeholders in a clear manner; for instance, it highlights that board members care far more about multi-quarter trends and direction than single data points,
highlights roll rates as leading indicators, and brings in key board-level concerns like reserve adequacy and allowance coverage. However, the response  lacks further detail about a BI Analyst role itself. This type of prompt is too specific; it is helpful for an analyst as they prepare presentations for executives and the board, but lacks details that would be beneficial to know while completing other day-to-day tasks.


## Version 3: What are the most important metrics for measuring credit risk in a consumer loan portfolio? State the full answer in 1-2 sentences up front, then go into detail with bullets thereafter.
Claude response: The most important credit risk metrics for a consumer loan portfolio fall into a few buckets: delinquency and default rates (which show current portfolio health), loss and recovery metrics (which show realized outcomes),
and forward-looking risk indicators (which show what's coming).Together these tell you how the portfolio is performing today, how much you're actually losing, and how much risk is building up for the future.

Delinquency and default indicators

Delinquency rate (30/60/90+ days past due), typically tracked as a percentage of total outstanding balance or number of accounts. This is the earliest warning sign of borrower stress.
Roll rates, which measure the percentage of accounts that move from one delinquency bucket to the next (e.g., 30-59 days to 60-89 days). These help predict where losses are headed before they show up in charge-offs.
Default rate, the share of loans that breach the contractual definition of default (often 90+ days past due or a specific

Evaluation: Claude's response does an excellent job following the structure that was requested in the prompt; it delivers a brief summary that answers all components of the question, meaning it addresses the key metrics for measuring credit risk up front. I found this to be especially helpful, as
I could understand the overall answer first and thereafter get into the details. The only addition that would enhance this prompt even more is providing the context that the user is a BI analyst. 


## Conclusion:
Overall, these three prompts took vastly different approaches to answering the same question. Prompt 1 was the most generic, as it somewhat answered the question but with little elaboration or context. Prompt 2 marked an
improvement, but still lacked a full response and was focused more so on what stakeholders would want to see rather than a thorough explanation of content. Prompt 3 produced the most useful output for a BI analyst, as it did the best job of
providing key metrics in a clear and actionable way that an analyst can use when running credit analyses and completing day-to-day tasks. 



## FACT CHECK:
In the long version of Claude's response to section 2, question 1, it noted that "Mortgage lenders in particular use front-end DTI (housing costs/income) and back-end DTI (all debt/income) against thresholds (commonly around 36-43%, with some programs allowing higher with compensating factors)."

Source: CFPB (consumerfinance.gov), page 2:https://files.consumerfinance.gov/f/documents/cfpb_your-money-your-goals_debt_income_calc_tool_2018-11_ADA.pdf

When it comes to mortgages for homeowners, CFPB says to "consider maintaining a debt-to income ratio for all debts of 36
percent or less. Some lenders will go up to 43 percent or higher. Your home mortgage is included in this ratio."

 CFPB and Claude's response agree; there is a strong possibility that Claude referenced this document when crafting the answer.
