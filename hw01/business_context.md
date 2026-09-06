## Homework 1, Part 2 — Business Context Exploration

## QUESTION 1
1. How are credit score, DTI ratio, and annual income typically used as credit risk metrics in consumer lending, and what combinations of these borrower attributes might signal elevated risk even when a borrower has a high credit score?
   
Claude Response: Credit score reflects repayment history, DTI measures current capacity to take on debt, and income indicates the borrower's financial cushion. Lenders combine all three since each captures something the others miss. A high score can mask risk when paired with high or recently spiking DTI (new debt or a financial disruption the score hasn't caught up to) or with income too thin relative to loan size to absorb a payment shock. The riskiest hidden profile combines a high score with both elevated DTI and limited income cushion: creditworthy on paper, but fragile in practice. 

Follow up question: When looking at borrowers with high credit scores but high DTI ratios, what specific threshold should trigger an automatic manual review instead of instant approval?

## QUESTION 2
2. What specific performance and credit risk metrics would a portfolio committee typically review quarterly across Auto, Personal, Home Improvement, Education, and Business loans, and how might the committee's focus differ across these five loan-purpose segments?
   
Claude response: Across all five segments, committees review a common core: delinquency and charge-off rates, vintage curves, reserve adequacy, credit score/DTI drift, concentration risk, and risk-adjusted yield. Focus then shifts by segment: Auto emphasizes loan-to-value and repossession recovery, Personal loans watch DTI drift and stacking risk given no collateral cushion, and Home Improvement tracks home-equity LTV or contractor/channel quality depending on structure. Education loans need a longer view (cohort default rates by school and time-to-first-payment, since losses surface years later) while Business loans draw scrutiny on industry concentration, guarantor strength, and cash-flow coverage given borrower heterogeneity.

Follow up question: How should our loan loss planning and strategies differ for Business loans with strong guarantors versus Personal loans that carry high debt-stacking risk?

## QUESTION 3
3. What is the difference between a loan categorized as "Delinquent" versus "Default," and how do these statuses differ from "Current" and "Paid Off" in a consumer lending portfolio? How should Wildcat think about establishing a policy or timeframe for transitioning a late account from Delinquent to Default?
   
Claude response: Current means payments are up to date; Delinquent means a missed payment (tracked in 30/60/90+ day buckets) with a reasonable chance of cure; Default is a formal status, usually triggered at 90-180 days past due, where repayment is no longer expected and charge-off/collections begin; Paid Off means the loan is fully satisfied. The key difference is that Delinquent is temporary and reversible, while Default treats the loan as a credit loss event. For Wildcat, the Delinquent-to-Default threshold should likely vary by segment — shorter for secured products like Auto where recovery takes time, longer for unsecured products where workouts may still recover value — and be set using cure-rate data (the delinquency bucket where cure rates drop off sharply), revisited as the portfolio matures.

Follow up question: What percentage of Delinquent loans historically return to Current status on their own versus transitioning into Default?
