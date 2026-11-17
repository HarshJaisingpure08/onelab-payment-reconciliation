# Assumptions & Domain Model

### 1. Accounting Period & Cutoff Timing
- **Target Accounting Window:** October 1, 2026 00:00:00 UTC through October 31, 2026 23:59:59 UTC.
- **Settlement Lag ($T+1$ to $T+2$ Business Days):** The platform logs customer transactions at instantaneous authorization time ($T_0$). The bank settles batches with a 1-to-2 day clearing window.
- **Timing Boundary Rollover:** Transactions executed during the closing hours of October (e.g., Oct 31, 22:50 UTC) settle on November 2, 2026. These are categorized as **In-Transit / Unsettled Assets** rather than missing funds or platform revenue leakage.

### 2. Monetary Precision & Currency Handling
- **Single Base Currency:** All monetary values are USD ($).
- **Exact Decimal Arithmetic:** Internal calculations use Python's fixed-point `decimal.Decimal` quantized to 2 decimal places (`0.01`). IEEE-754 binary floating-point (`float64`) arithmetic is strictly avoided for balance totals to prevent false phantom cent discrepancies.
- **Sub-Penny Rounding Tolerance:** An operational tolerance threshold ($\le \$0.02$) is applied per transaction. Any delta within tolerance is classified as **Rounding Drift**; the system aggregates these to verify whether micro-differences accumulate into a material portfolio-level variance.

### 3. Settlement Model (Gross vs. Net)
- **Gross Settlement Basis:** Platform payments and bank settlements match at the gross transaction level. Interchange, processor markup, and gateway fees are treated as separate debit events rather than deducted at source (which would turn a $100 payment into a $97.10 net settlement).

### 4. Shared Primary Keys & Remittance References
- Both datasets share a unique platform transaction identifier (`transaction_id`) passed in the bank settlement remittance line.
- For refund transactions, an `original_transaction_id` field tracks the parent payment. When a bank refund has an unknown or empty parent ID not present in the platform ledger, it is isolated as an **Orphan Refund** (e.g., manual bank clawback or out-of-period chargeback).

### 5. Idempotency & Duplicate Behavior
- Any `transaction_id` appearing $>1$ time in the platform dataset is flagged as a **Platform Duplicate** (e.g., webhook retry / double authorization).
- Any `transaction_id` appearing $>1$ time in the bank dataset is flagged as a **Bank Duplicate** (e.g., double clearing batch credit). The primary entry is reconciled, and subsequent duplicate entries are diverted to suspense.

