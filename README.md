# Onelab — Payment Reconciliation System

An automated multi-pass payment reconciliation application built with Python, Pandas, Streamlit, and Pytest.

Reconciles instantaneous platform transaction ledgers against delayed, batched bank settlement statements, isolates financial anomalies, and bridges the book balance to actual cash at the bank with exact mathematical precision ($0.00 unreconciled gap).

---

## 🚀 Quickstart: Running Locally

### 1. Prerequisites
- Python 3.10+ installed
- Git

### 2. Installation
Clone or unzip the repository and install dependencies:
```bash
cd onelab
pip install -r requirements.txt
```

### 3. Generate Test Data (Optional)
The repository comes pre-populated with October 2026 synthetic data in `data/`. To re-generate:
```bash
python generate_data.py
```

### 4. Run Automated Tests
Execute the comprehensive 17-case automated test suite:
```bash
pytest tests/ -v
```
All 17 tests pass, covering:
- 1:1 clean transaction matching
- All 4 planted gap types (Timing rollover, Cumulative rounding, Bank duplicates, Orphan refunds)
- Schema validations (missing columns, invalid types)
- Real-world edge cases:
  - Messy transaction IDs (trailing/leading whitespace, mixed casing)
  - Stringified nulls (`'NULL'`, `'NaN'`, `'None'`) in parent references
  - Timezone mismatches (UTC tz-aware vs naive timestamps)
- Stress test combining all 7 anomaly types into a mathematically closed bridge ($0.00 unreconciled gap)

### 5. Launch the Interactive Dashboard
Start the Streamlit application:
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 🧩 The 4 Planted Anomaly Types & Expected Results

| Gap Type | Transaction / Settlement ID | Financial Impact | Detection Logic |
| :--- | :--- | :--- | :--- |
| **1. Timing Rollover (Settled Next Month)** | `TXN-2026-1033-033` / `STL-2026-1102-037` | **+$450.00** | Platform record in Oct 2026, settled by bank in Nov 2026. Flagged as In-Transit Asset. |
| **2. Cumulative Rounding Drift** | `TXN-2026-1025-025` to `TXN-2026-1032-032` | **+$0.12** | 8 rows with individually tolerable $0.01–$0.02 delta accumulating into a visible imbalance. |
| **3. Bank Duplicate Entry** | `TXN-2026-1012-012` (`STL-2026-1014-012` & `STL-2026-1014-013`) | **+$320.00** | Transaction ID appears twice in bank settlements feed; secondary row isolated to suspense. |
| **4. Orphan Bank Refund** | `TXN-2026-ORPHAN-REF` (`STL-2026-1028-036`) | **-$185.00** | Bank debited refund for parent `TXN-2026-0815-999` which does not exist in platform ledger. |

### The Reconciliation Bridge
```
Platform Net Book Balance:             $10,285.06
  - Less: Month-End Timing Rollover:     -$450.00
  + Plus: Bank Duplicate Settlement:     +$320.00
  - Less: Orphan Bank Refund Deducted:   -$185.00
  - Less: Cumulative Rounding Drift:       -$0.12
-------------------------------------------------
= Adjusted Expected Bank Balance:       $9,969.94
Actual Bank Settlement in October:      $9,969.94
-------------------------------------------------
FINAL UNRECONCILED GAP:                    $0.00  (Fully Balanced)
```

---

## 📁 Repository Structure
```
onelab/
├── README.md                      # Project setup and documentation
├── assumptions.md                 # Explicit financial & engineering assumptions
├── prompts.md                     # Raw & Distilled prompts (mandatory submission)
├── production_limitations.md      # 3 sentences on what it would get wrong in production
├── requirements.txt               # Dependencies (pandas, streamlit, pytest)
├── reconciliation.py              # Pure-python core reconciliation engine (Decimal math)
├── generate_data.py               # Deterministic synthetic test dataset generator
├── app.py                         # Streamlit interactive UI dashboard
├── data/
│   ├── platform_transactions.csv  # 35 platform records (Oct 2026)
│   └── bank_settlements.csv       # 37 bank settlement records (Oct/Nov 2026)
└── tests/
    └── test_reconciliation.py     # 8 comprehensive pytest test cases
```

---

## ⚠️ What It Would Get Wrong in Production (3 Sentences)

1. In real-world banking, banks settle transactions as aggregated net lump sums (gross volume minus variable interchange, card scheme assessments, and gateway fees) rather than 1:1 gross line items, causing this engine to falsely flag normal fee deductions as unlinked amount mismatches.
2. It relies on a clean, preserved `transaction_id` in bank settlement records, whereas real settlement clearing files (e.g., MT940, BAI2, or ISO 20022 camt.053) routinely truncate, alter, or omit platform IDs, which would cause massive false-positive orphan classifications without fuzzy matching or reference token parsing.
3. It assumes a static calendar month boundary with simple T+1/T+2 settlement delays, completely ignoring multi-day bank holiday calendar matrices, weekend clearing blackout windows, and timezone cutoff differences (e.g., platform 23:59 UTC vs bank 17:00 EST cutoff) that shift legitimate settlements across month-end reconciliation borders.

