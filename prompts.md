# Assessment Prompts (Mandatory Submission)

## 1. Raw Prompt
The original user prompt received for the assessment:

```text
Onelab — AI Fitness Assessment
Time: 2 hours | Tools: Any AI I Right answer: There isn't one
The Problem
A payments company's books don't balance at month end. They know every transaction their platform processed. They know what the bank says actually arrived. The two should match. They don't. Find out why. Show them where the gaps are.
Test Data
No files provided. Generate your own — that's part of the assessment. A payments platform records a transaction instantly when a customer pays. The bank batches and settles funds 1–2 days later. At month end every transaction should have a matching settlement.
Plant these gap types: a transaction that settled the following month · a rounding difference that only shows when summed · a duplicate entry in one dataset · a refund with no matching original transaction.
State your assumptions. There are no wrong ones as long as you name them.
What to Submit
1 Brainstorming thread Full LLM convo. Do not clean it up.
2 Distilled prompt and  Raw Prompt (mandatory )  The single prompt you fed into Claude Code or Cursor or any other AI coding tool.
3 Claude Code thread Full execution thread including wrong turns.
4 Test cases What you wrote to verify your solution works.
5 Working output Deployed link + code zip + Demo video + 3 sentences on what it 
would get wrong in production.
```

---

## 2. Distilled Prompt
The single engineered prompt fed into the AI coding assistant:

```text
Build a Python-based payment reconciliation application using Streamlit and Pandas.

1. CSV Upload: Upload platform transactions CSV and bank settlements CSV. Validate required columns and types, and show understandable errors.

2. Reconciliation Engine: Match records using transaction ID; compare amounts; detect missing bank settlements, settlements after the reconciliation month, duplicates in either dataset, orphan refunds without a corresponding original payment, and cumulative rounding differences even when individual differences are within tolerance.

3. Dashboard: Show total platform transactions, total bank settlements, matched and unmatched transactions, platform amount, bank amount, net difference and discrepancy breakdown.

4. Results: Show discrepancy category, transaction ID, platform amount, bank amount, difference and explanation. Allow CSV export.

5. Code Quality: Separate reconciliation logic from UI. Use clear functions, Decimal or integer paise for money, handle missing values and invalid CSVs, and comment non-obvious logic.

6. Testing: Write pytest tests for all four planted discrepancy types, normal matched transactions and edge cases.

Build a working MVP, not a production banking system. Do not invent test results or claim deployment has happened. Explain how to run locally.
```

