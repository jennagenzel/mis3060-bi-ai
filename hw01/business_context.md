## Homework 1, Part 2 — Business Context Exploration

## QUESTION 1
1. How are credit score, DTI ratio, and annual income typically used as credit risk metrics in consumer lending, and what combinations of these borrower attributes might signal elevated risk even when a borrower has a high credit score?
   
Claude Response: Credit score reflects repayment history, DTI measures current capacity to take on debt, and income indicates the borrower's financial cushion. Lenders combine all three since each captures something the others miss. A high score can mask risk when paired with high or recently spiking DTI (new debt or a financial disruption the score hasn't caught up to) or with income too thin relative to loan size to absorb a payment shock. The riskiest hidden profile combines a high score with both elevated DTI and limited income cushion: creditworthy on paper, but fragile in practice. 

Follow up question: When looking at borrowers with high credit scores but high DTI ratios, what specific threshold should initiate an automatic manual review instead of instant approval?

## QUESTION 2
2. What specific performance and credit risk metrics would a portfolio committee typically review quarterly across Auto, Personal, Home Improvement, Education, and Business loans, and how might the committee's focus differ across these five loan-purpose segments?
   
Claude response: Across all five segments, committees review a common core: delinquency and charge-off rates, vintage curves, reserve adequacy, credit score/DTI drift, concentration risk, and risk-adjusted yield. Focus then shifts by segment: Auto emphasizes loan-to-value and repossession recovery, Personal loans watch DTI drift and stacking risk given no collateral cushion, and Home Improvement tracks home-equity LTV or contractor/channel quality depending on structure. Education loans need a longer view (cohort default rates by school and time-to-first-payment, since losses surface years later) while Business loans draw scrutiny on industry concentration, guarantor strength, and cash-flow coverage given borrower heterogeneity.

Follow up question: How should  loan loss planning and strategies differ for Business loans with strong guarantors versus Personal loans that carry high debt-stacking risk?

## QUESTION 3
3. What is the difference between a loan categorized as "Delinquent" versus "Default," and how do these statuses differ from "Current" and "Paid Off" in a consumer lending portfolio? How should Wildcat think about establishing a policy or timeframe for transitioning a late account from Delinquent to Default?
   
Claude response: Current means payments are up to date; Delinquent means a missed payment (tracked in 30/60/90+ day buckets) with a reasonable chance of cure; Default is a formal status, usually triggered at 90-180 days past due, where repayment is no longer expected and charge-off/collections begin; Paid Off means the loan is fully satisfied. The key difference is that Delinquent is temporary and reversible, while Default treats the loan as a credit loss event. For Wildcat, the Delinquent-to-Default threshold should likely vary by segment — shorter for secured products like Auto where recovery takes time, longer for unsecured products where workouts may still recover value — and be set using cure-rate data (the delinquency bucket where cure rates drop off sharply), revisited as the portfolio matures.

Follow up question: What percentage of Delinquent loans historically return to Current status on their own versus transitioning into Default?

## QUESTION 4
4. What percentage of the typical portfolio is concentrated in top states like California, Texas, or New York, and what indicates elevated regional risk?

Claude response: Lenders measure geographic concentration by tracking each state's share of total outstanding balances against risk-appetite limits, often paired with a concentration index (like an HHI) and state-level default/loss-severity rates to see whether exposure is unevenly spread. They manage it through formal state-exposure caps in credit policy, underwriting overlays that tighten in overexposed or weakening states, and diversification targets in origination. A regional downturn typically shows up as a cluster of signals moving together in one state: delinquency and default rates rising faster than the portfolio-wide trend, roll rates accelerating, and loss-given-default widening due to weaker collateral recovery. These credit signals are usually cross-checked against local macro data — rising unemployment, falling home prices, sector-specific shocks — since the combination of both is what confirms a genuine downturn rather than noise.

Follow up question: How do lenders determine the exact threshold for a state risk exposure cap, and what steps are taken if a single state exceeds its risk limit?

## QUESTION 5
5. The portfolio includes loan terms ranging from 36 to 120 months with varying interest rates. From a risk management perspective, why do longer-term fixed-rate consumer loans carry different credit and interest rate risks compared to shorter-term loans, and how should a lender evaluate whether rate pricing covers the multi-year risk exposure?

Claude response: Longer-term fixed-rate loans carry more credit risk since a longer horizon gives more time for a borrower's finances to deteriorate, and early defaults are costlier since less principal has amortized. They also carry more interest rate risk, since locking in today's rate for up to 120 months exposes the lender to rising funding costs if rates climb mid-term, unlike shorter loans that reprice sooner. To evaluate pricing adequacy, lenders build the rate from funding cost, a term-adjusted expected-loss component (cumulative PD/LGD over the full life), a duration premium, and a target margin — then stress-test that margin under rising-rate scenarios and check it against actual vintage performance by term bucket.

Follow up question: When it gets more expensive for a bank to borrow money, how do they decide when it's time to raise interest rates on new 10-year loans?


