# 3 Sentences on What It Would Get Wrong in Production

1. In real-world banking, banks settle transactions as aggregated net lump sums (gross volume minus variable interchange, card scheme assessments, and gateway fees) rather than 1:1 gross line items, causing this engine to falsely flag normal fee deductions as unlinked amount mismatches.

2. It relies on a clean, preserved `transaction_id` in bank settlement records, whereas real settlement clearing files (e.g., MT940, BAI2, or ISO 20022 camt.053) routinely truncate, alter, or omit platform IDs, which would cause massive false-positive orphan classifications without fuzzy matching or reference token parsing.

3. It assumes a static calendar month boundary with simple T+1/T+2 settlement delays, completely ignoring multi-day bank holiday calendar matrices, weekend clearing blackout windows, and timezone cutoff differences (e.g., platform 23:59 UTC vs bank 17:00 EST cutoff) that shift legitimate settlements across month-end reconciliation borders.

