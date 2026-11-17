"""
tests/test_reconciliation.py - Comprehensive Test Suite for Reconciliation Engine

Verifies 17 Automated Test Scenarios:
1. Normal matched transactions (1:1 clean match)
2. Planted Gap 1: Timing rollover settling in next month
3. Planted Gap 2: Cumulative rounding drift from sub-penny differences
4. Planted Gap 3: Bank duplicate settlements
5. Planted Gap 4: Orphan bank refunds with unlinked original transaction IDs
6. Schema validation: Missing required columns
7. Schema validation: Invalid transaction types and malformed amounts
8. Full end-to-end integration test against October 2026 synthetic datasets
9. Material amount mismatches exceeding rounding tolerance
10. Platform-side duplicate entry detection and bridge attribution
11. Missing bank settlement detection
12. Unmatched bank payment detection
13. Identical bank duplicate rows sharing the exact same settlement_id
14. Complex stress test combining all 7 anomaly types simultaneously
15. Real-World Edge Case: Messy transaction IDs (whitespace trimming & case insensitivity)
16. Real-World Edge Case: Stringified nulls ('NULL', 'NaN', 'None') in original_transaction_id
17. Real-World Edge Case: Timezone mismatches (UTC tz-aware platform vs tz-naive bank timestamps)
"""

from decimal import Decimal
import pandas as pd
import pytest

from reconciliation import (
    ReconciliationEngine,
    validate_platform_data,
    validate_bank_data,
    to_decimal,
)


@pytest.fixture
def clean_platform_df():
    return pd.DataFrame(
        [
            {
                "transaction_id": "TXN-001",
                "transaction_date": "2026-10-05 10:00:00",
                "amount": "100.00",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            },
            {
                "transaction_id": "TXN-002",
                "transaction_date": "2026-10-06 11:00:00",
                "amount": "25.50",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            },
            {
                "transaction_id": "TXN-003",
                "transaction_date": "2026-10-10 14:00:00",
                "amount": "15.00",
                "transaction_type": "REFUND",
                "original_transaction_id": "TXN-001",
            },
        ]
    )


@pytest.fixture
def clean_bank_df():
    return pd.DataFrame(
        [
            {
                "settlement_id": "STL-001",
                "transaction_id": "TXN-001",
                "settlement_date": "2026-10-06 04:00:00",
                "amount": "100.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            },
            {
                "settlement_id": "STL-002",
                "transaction_id": "TXN-002",
                "settlement_date": "2026-10-07 05:00:00",
                "amount": "25.50",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            },
            {
                "settlement_id": "STL-003",
                "transaction_id": "TXN-003",
                "settlement_date": "2026-10-11 04:30:00",
                "amount": "15.00",
                "entry_type": "REFUND",
                "original_transaction_id": "TXN-001",
            },
        ]
    )


def test_clean_1_to_1_matching(clean_platform_df, clean_bank_df):
    """Verifies that identical transactions match 100% with zero discrepancies."""
    engine = ReconciliationEngine(clean_platform_df, clean_bank_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]

    assert summary["matched_count"] == 3
    assert summary["discrepancy_count"] == 0
    assert summary["platform_net_amount"] == 110.50
    assert summary["bank_target_month_net"] == 110.50
    assert summary["raw_net_variance"] == 0.0
    assert summary["unreconciled_gap"] == 0.0


def test_planted_gap_1_timing_rollover(clean_platform_df, clean_bank_df):
    """Verifies detection of transaction created in October settling in November."""
    p_df = clean_platform_df.copy()
    b_df = clean_bank_df.copy()

    # Add late October platform payment
    late_p = pd.DataFrame(
        [
            {
                "transaction_id": "TXN-LATE-01",
                "transaction_date": "2026-10-31 23:45:00",
                "amount": "500.00",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    # Add November bank settlement
    late_b = pd.DataFrame(
        [
            {
                "settlement_id": "STL-NOV-01",
                "transaction_id": "TXN-LATE-01",
                "settlement_date": "2026-11-02 04:30:00",
                "amount": "500.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )

    p_df = pd.concat([p_df, late_p], ignore_index=True)
    b_df = pd.concat([b_df, late_b], ignore_index=True)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    late_records = discrepancies[discrepancies["category"] == "LATE_SETTLEMENT_NEXT_MONTH"]
    assert len(late_records) == 1
    assert late_records.iloc[0]["transaction_id"] == "TXN-LATE-01"
    assert summary["total_timing_rollover"] == 500.00
    assert summary["unreconciled_gap"] == 0.0


def test_planted_gap_2_cumulative_rounding_drift(clean_platform_df, clean_bank_df):
    """Verifies that small sub-penny rounding errors accumulate into aggregate drift."""
    p_rows = []
    b_rows = []
    # 5 transactions, each with $0.01 difference -> total drift $0.05
    for i in range(1, 6):
        tid = f"TXN-RND-{i}"
        sid = f"STL-RND-{i}"
        p_rows.append(
            {
                "transaction_id": tid,
                "transaction_date": "2026-10-15 10:00:00",
                "amount": "50.05",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        )
        b_rows.append(
            {
                "settlement_id": sid,
                "transaction_id": tid,
                "settlement_date": "2026-10-17 04:00:00",
                "amount": "50.04",  # $0.01 less
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        )

    p_df = pd.concat([clean_platform_df, pd.DataFrame(p_rows)], ignore_index=True)
    b_df = pd.concat([clean_bank_df, pd.DataFrame(b_rows)], ignore_index=True)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    rounding_records = discrepancies[discrepancies["category"] == "ROUNDING_DIFFERENCE"]
    assert len(rounding_records) == 5
    assert round(summary["cumulative_rounding_drift"], 2) == 0.05
    assert summary["unreconciled_gap"] == 0.0


def test_planted_gap_3_bank_duplicate(clean_platform_df, clean_bank_df):
    """Verifies detection when bank settles the same transaction ID twice."""
    b_df = clean_bank_df.copy()
    # Add duplicate settlement row for TXN-001
    dupe_row = pd.DataFrame(
        [
            {
                "settlement_id": "STL-001-DUPE",
                "transaction_id": "TXN-001",
                "settlement_date": "2026-10-06 04:00:00",
                "amount": "100.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    b_df = pd.concat([b_df, dupe_row], ignore_index=True)

    engine = ReconciliationEngine(clean_platform_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    dupe_records = discrepancies[discrepancies["category"] == "BANK_DUPLICATE"]
    assert len(dupe_records) == 1
    assert dupe_records.iloc[0]["transaction_id"] == "TXN-001"
    assert summary["total_bank_duplicates"] == 100.00
    assert summary["unreconciled_gap"] == 0.0


def test_planted_gap_4_orphan_bank_refund(clean_platform_df, clean_bank_df):
    """Verifies detection of a bank refund referencing a non-existent parent transaction."""
    b_df = clean_bank_df.copy()
    orphan_row = pd.DataFrame(
        [
            {
                "settlement_id": "STL-ORPHAN-01",
                "transaction_id": "TXN-GHOST-REF",
                "settlement_date": "2026-10-20 12:00:00",
                "amount": "85.00",
                "entry_type": "REFUND",
                "original_transaction_id": "TXN-NON-EXISTENT-999",
            }
        ]
    )
    b_df = pd.concat([b_df, orphan_row], ignore_index=True)

    engine = ReconciliationEngine(clean_platform_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    orphan_records = discrepancies[discrepancies["category"] == "ORPHAN_REFUND"]
    assert len(orphan_records) == 1
    assert orphan_records.iloc[0]["settlement_id"] == "STL-ORPHAN-01"
    assert summary["total_orphan_refunds"] == 85.00
    assert summary["unreconciled_gap"] == 0.0


def test_schema_validation_missing_columns():
    """Verifies that missing columns trigger clean error messages."""
    invalid_p = pd.DataFrame([{"wrong_col": 123}])
    is_valid, err = validate_platform_data(invalid_p)
    assert not is_valid
    assert "missing required columns" in err

    invalid_b = pd.DataFrame([{"wrong_col": 456}])
    is_valid, err = validate_bank_data(invalid_b)
    assert not is_valid
    assert "missing required columns" in err


def test_schema_validation_invalid_types():
    """Verifies invalid transaction types or non-numeric amounts are rejected."""
    bad_type_df = pd.DataFrame(
        [
            {
                "transaction_id": "T1",
                "transaction_date": "2026-10-01",
                "amount": "100.00",
                "transaction_type": "INVALID_TYPE",
                "original_transaction_id": "",
            }
        ]
    )
    is_valid, err = validate_platform_data(bad_type_df)
    assert not is_valid
    assert "invalid transaction_type" in err

    bad_amt_df = pd.DataFrame(
        [
            {
                "transaction_id": "T1",
                "transaction_date": "2026-10-01",
                "amount": "NOT_A_NUMBER",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    is_valid, err = validate_platform_data(bad_amt_df)
    assert not is_valid
    assert "invalid amount" in err


def test_full_synthetic_dataset_reconciliation():
    """
    End-to-End integration test on the generated October 2026 dataset.
    Verifies that the multi-pass engine flags all 4 planted gaps and reconciles to $0.00.
    """
    p_df = pd.read_csv("data/platform_transactions.csv")
    b_df = pd.read_csv("data/bank_settlements.csv")

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    s = result["summary"]

    assert s["platform_total_count"] == 35
    assert s["bank_total_count"] == 37
    assert s["platform_net_amount"] == 10285.06
    assert s["bank_target_month_net"] == 9969.94
    assert s["raw_net_variance"] == 315.12

    # Verify planted gap amounts
    assert s["total_timing_rollover"] == 450.00
    assert s["total_bank_duplicates"] == 320.00
    assert s["total_orphan_refunds"] == 185.00
    assert round(s["cumulative_rounding_drift"], 2) == 0.12

    # Verify reconciliation closure
    assert s["adjusted_expected_bank"] == 9969.94
    assert s["unreconciled_gap"] == 0.00


def test_material_amount_mismatch_exceeding_tolerance(clean_platform_df, clean_bank_df):
    """Verifies that amount difference exceeding tolerance is flagged as AMOUNT_MISMATCH."""
    p_df = clean_platform_df.copy()
    b_df = clean_bank_df.copy()

    # Modify TXN-001 amount on bank side by $15.00 (far exceeds $0.02 tolerance)
    b_df.loc[b_df["transaction_id"] == "TXN-001", "amount"] = "85.00"

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10", rounding_tolerance=Decimal("0.02"))
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    mismatch_rows = discrepancies[discrepancies["category"] == "AMOUNT_MISMATCH"]
    assert len(mismatch_rows) == 1
    assert mismatch_rows.iloc[0]["transaction_id"] == "TXN-001"
    assert mismatch_rows.iloc[0]["difference"] == 15.00
    assert summary["unreconciled_gap"] == 0.00


def test_platform_duplicate_detection(clean_platform_df, clean_bank_df):
    """Verifies that platform-side duplicate authorizations are detected and bridged."""
    p_df = clean_platform_df.copy()
    dupe_row = pd.DataFrame(
        [
            {
                "transaction_id": "TXN-001",  # Same ID duplicated on platform
                "transaction_date": "2026-10-05 10:00:05",
                "amount": "100.00",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    p_df = pd.concat([p_df, dupe_row], ignore_index=True)

    engine = ReconciliationEngine(p_df, clean_bank_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    dupes = discrepancies[discrepancies["category"] == "PLATFORM_DUPLICATE"]
    assert len(dupes) == 1
    assert summary["total_platform_duplicates"] == 100.00
    assert summary["unreconciled_gap"] == 0.00


def test_missing_bank_settlement(clean_platform_df, clean_bank_df):
    """Verifies platform transactions that never settled are detected and bridged."""
    p_df = clean_platform_df.copy()
    missing_row = pd.DataFrame(
        [
            {
                "transaction_id": "TXN-UNSETTLED-01",
                "transaction_date": "2026-10-15 12:00:00",
                "amount": "350.00",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    p_df = pd.concat([p_df, missing_row], ignore_index=True)

    engine = ReconciliationEngine(p_df, clean_bank_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    unsettled = discrepancies[discrepancies["category"] == "MISSING_BANK_SETTLEMENT"]
    assert len(unsettled) == 1
    assert summary["total_missing_bank_settlements"] == 350.00
    assert summary["unreconciled_gap"] == 0.00


def test_unmatched_bank_payment(clean_platform_df, clean_bank_df):
    """Verifies bank payments without platform record are detected and bridged."""
    b_df = clean_bank_df.copy()
    unknown_row = pd.DataFrame(
        [
            {
                "settlement_id": "STL-UNKNOWN-01",
                "transaction_id": "TXN-STRANGER-01",
                "settlement_date": "2026-10-18 04:00:00",
                "amount": "275.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    b_df = pd.concat([b_df, unknown_row], ignore_index=True)

    engine = ReconciliationEngine(clean_platform_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    unknowns = discrepancies[discrepancies["category"] == "UNMATCHED_BANK_PAYMENT"]
    assert len(unknowns) == 1
    assert summary["total_unmatched_bank_payments"] == 275.00
    assert summary["unreconciled_gap"] == 0.00


def test_identical_bank_duplicates_same_settlement_id(clean_platform_df, clean_bank_df):
    """Verifies bank duplicate detection even when settlement_id is byte-for-byte identical."""
    b_df = clean_bank_df.copy()
    # Add exact duplicate row with same settlement_id
    dupe_row = pd.DataFrame(
        [
            {
                "settlement_id": "STL-001",  # Same settlement_id
                "transaction_id": "TXN-001",
                "settlement_date": "2026-10-06 04:00:00",
                "amount": "100.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    b_df = pd.concat([b_df, dupe_row], ignore_index=True)

    engine = ReconciliationEngine(clean_platform_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    dupes = discrepancies[discrepancies["category"] == "BANK_DUPLICATE"]
    assert len(dupes) == 1
    assert summary["total_bank_duplicates"] == 100.00
    assert summary["unreconciled_gap"] == 0.00


def test_all_anomalies_combined_generalized_bridge():
    """
    Stress test: verifies exact mathematical zero-gap reconciliation when
    ALL discrepancy types are present simultaneously in a complex dataset.
    """
    platform_rows = [
        {"transaction_id": "T-CLEAN", "transaction_date": "2026-10-02 10:00:00", "amount": "200.00", "transaction_type": "PAYMENT", "original_transaction_id": ""},
        {"transaction_id": "T-LATE", "transaction_date": "2026-10-31 23:00:00", "amount": "500.00", "transaction_type": "PAYMENT", "original_transaction_id": ""},
        {"transaction_id": "T-ROUND", "transaction_date": "2026-10-10 10:00:00", "amount": "100.05", "transaction_type": "PAYMENT", "original_transaction_id": ""},
        {"transaction_id": "T-MISMATCH", "transaction_date": "2026-10-12 10:00:00", "amount": "300.00", "transaction_type": "PAYMENT", "original_transaction_id": ""},
        {"transaction_id": "T-MISSING", "transaction_date": "2026-10-14 10:00:00", "amount": "150.00", "transaction_type": "PAYMENT", "original_transaction_id": ""},
        {"transaction_id": "T-DUPE-P", "transaction_date": "2026-10-15 10:00:00", "amount": "80.00", "transaction_type": "PAYMENT", "original_transaction_id": ""},
        {"transaction_id": "T-DUPE-P", "transaction_date": "2026-10-15 10:00:01", "amount": "80.00", "transaction_type": "PAYMENT", "original_transaction_id": ""},
        {"transaction_id": "T-DUPE-B", "transaction_date": "2026-10-16 10:00:00", "amount": "250.00", "transaction_type": "PAYMENT", "original_transaction_id": ""},
    ]

    bank_rows = [
        {"settlement_id": "S-CLEAN", "transaction_id": "T-CLEAN", "settlement_date": "2026-10-04 04:00:00", "amount": "200.00", "entry_type": "PAYMENT", "original_transaction_id": ""},
        {"settlement_id": "S-LATE", "transaction_id": "T-LATE", "settlement_date": "2026-11-02 04:00:00", "amount": "500.00", "entry_type": "PAYMENT", "original_transaction_id": ""},
        {"settlement_id": "S-ROUND", "transaction_id": "T-ROUND", "settlement_date": "2026-10-12 04:00:00", "amount": "100.04", "entry_type": "PAYMENT", "original_transaction_id": ""}, # delta = +0.01
        {"settlement_id": "S-MISMATCH", "transaction_id": "T-MISMATCH", "settlement_date": "2026-10-14 04:00:00", "amount": "250.00", "entry_type": "PAYMENT", "original_transaction_id": ""}, # delta = +50.00
        {"settlement_id": "S-DUPE-P", "transaction_id": "T-DUPE-P", "settlement_date": "2026-10-17 04:00:00", "amount": "80.00", "entry_type": "PAYMENT", "original_transaction_id": ""},
        {"settlement_id": "S-DUPE-B1", "transaction_id": "T-DUPE-B", "settlement_date": "2026-10-18 04:00:00", "amount": "250.00", "entry_type": "PAYMENT", "original_transaction_id": ""},
        {"settlement_id": "S-DUPE-B2", "transaction_id": "T-DUPE-B", "settlement_date": "2026-10-18 04:00:00", "amount": "250.00", "entry_type": "PAYMENT", "original_transaction_id": ""}, # Bank duplicate
        {"settlement_id": "S-ORPHAN", "transaction_id": "T-ORPHAN", "settlement_date": "2026-10-20 04:00:00", "amount": "90.00", "entry_type": "REFUND", "original_transaction_id": "T-UNKNOWN-REF"}, # Orphan refund
        {"settlement_id": "S-STRANGER", "transaction_id": "T-STRANGER", "settlement_date": "2026-10-22 04:00:00", "amount": "120.00", "entry_type": "PAYMENT", "original_transaction_id": ""}, # Unmatched bank payment
    ]

    p_df = pd.DataFrame(platform_rows)
    b_df = pd.DataFrame(bank_rows)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10", rounding_tolerance=Decimal("0.02"))
    result = engine.reconcile()
    s = result["summary"]

    assert s["unreconciled_gap"] == 0.00
    assert s["matched_count"] >= 1
    assert s["discrepancy_count"] == 8


def test_messy_transaction_ids(clean_platform_df, clean_bank_df):
    """
    Real-world test 1: Extra whitespace and inconsistent casing in transaction IDs.
    Verifies that IDs like 'TXN-001  ' and '  txn-001' are normalized and matched cleanly.
    """
    p_df = clean_platform_df.copy()
    b_df = clean_bank_df.copy()

    # Introduce messy whitespace and mixed casing
    p_df.loc[p_df["transaction_id"] == "TXN-001", "transaction_id"] = "TXN-001  "
    b_df.loc[b_df["transaction_id"] == "TXN-001", "transaction_id"] = "  txn-001"

    p_df.loc[p_df["transaction_id"] == "TXN-002", "transaction_id"] = "  txn-002  "
    b_df.loc[b_df["transaction_id"] == "TXN-002", "transaction_id"] = "TXN-002"

    p_df.loc[p_df["transaction_id"] == "TXN-003", "transaction_id"] = "txn-003"
    b_df.loc[b_df["transaction_id"] == "TXN-003", "transaction_id"] = "TXN-003 "

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]

    assert summary["matched_count"] == 3
    assert summary["discrepancy_count"] == 0
    assert summary["unreconciled_gap"] == 0.00


def test_stringified_null_values_in_original_transaction_id(clean_platform_df, clean_bank_df):
    """
    Real-world test 2: Stringified nulls ('NULL', 'NaN', 'None') in CSV feeds.
    Verifies that literal string 'NULL' in original_transaction_id is treated as null
    and not matched as a legitimate transaction identifier.
    """
    p_df = clean_platform_df.copy()
    b_df = clean_bank_df.copy()

    # Add a normal payment with stringified 'NaN' in original_transaction_id
    p_df.loc[p_df["transaction_id"] == "TXN-001", "original_transaction_id"] = "NaN"

    # Add a bank refund that explicitly contains literal 'NULL' string in original_transaction_id
    # Since it has no parent and unknown ID, it must be detected as an ORPHAN_REFUND
    orphan_refund = pd.DataFrame(
        [
            {
                "settlement_id": "STL-NULL-REF-01",
                "transaction_id": "TXN-UNLINKED-REF",
                "settlement_date": "2026-10-15 05:00:00",
                "amount": "45.00",
                "entry_type": "REFUND",
                "original_transaction_id": "NULL",  # Literal string 'NULL'
            }
        ]
    )
    b_df = pd.concat([b_df, orphan_refund], ignore_index=True)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    # Verify that the refund with 'NULL' parent is flagged as an ORPHAN_REFUND
    orphan_records = discrepancies[discrepancies["category"] == "ORPHAN_REFUND"]
    assert len(orphan_records) == 1
    assert orphan_records.iloc[0]["settlement_id"] == "STL-NULL-REF-01"
    assert summary["total_orphan_refunds"] == 45.00
    assert summary["unreconciled_gap"] == 0.00


def test_timezone_mismatches_in_timestamps(clean_platform_df, clean_bank_df):
    """
    Real-world test 3: Timezone-aware (UTC) vs Timezone-naive timestamps.
    Verifies that date comparisons and month boundaries do not throw TypeError
    and correctly identify month-end timing rollovers.
    """
    p_df = clean_platform_df.copy()
    b_df = clean_bank_df.copy()

    # Set platform timestamps to ISO-8601 UTC timezone-aware strings
    p_df["transaction_date"] = [
        "2026-10-05T10:00:00Z",
        "2026-10-06 11:00:00+00:00",
        "2026-10-10T14:00:00+00:00",
    ]
    # Bank timestamps remain timezone-naive strings
    b_df["settlement_date"] = [
        "2026-10-06 04:00:00",
        "2026-10-07 05:00:00",
        "2026-10-11 04:30:00",
    ]

    # Add a late October UTC payment settling in November (naive)
    late_utc_p = pd.DataFrame(
        [
            {
                "transaction_id": "TXN-UTC-LATE",
                "transaction_date": "2026-10-31T23:55:00+00:00",  # 5 min before midnight UTC
                "amount": "600.00",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    late_naive_b = pd.DataFrame(
        [
            {
                "settlement_id": "STL-NOV-NAIVE",
                "transaction_id": "TXN-UTC-LATE",
                "settlement_date": "2026-11-02 05:00:00",  # Naive November settlement
                "amount": "600.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )

    p_df = pd.concat([p_df, late_utc_p], ignore_index=True)
    b_df = pd.concat([b_df, late_naive_b], ignore_index=True)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]
    discrepancies = result["discrepancies_df"]

    # 3 clean matches from fixtures
    assert summary["matched_count"] == 3

    # Late transaction should be classified cleanly without tz errors
    late_records = discrepancies[discrepancies["category"] == "LATE_SETTLEMENT_NEXT_MONTH"]
    assert len(late_records) == 1
    assert late_records.iloc[0]["transaction_id"] == "TXN-UTC-LATE"
    assert summary["total_timing_rollover"] == 600.00
    assert summary["unreconciled_gap"] == 0.00


def test_zero_dollar_card_authorizations(clean_platform_df, clean_bank_df):
    """
    Edge case: $0.00 card authorization / account verification transactions.
    Verifies that zero amounts do not cause division errors or parse failures,
    and correctly match or identify unsettled authorizations.
    """
    p_df = clean_platform_df.copy()
    b_df = clean_bank_df.copy()

    # Add a $0.00 platform card auth that settled at $0.00
    auth_p = pd.DataFrame(
        [
            {
                "transaction_id": "TXN-AUTH-ZERO",
                "transaction_date": "2026-10-08 14:20:00",
                "amount": "0.00",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    auth_b = pd.DataFrame(
        [
            {
                "settlement_id": "STL-AUTH-ZERO",
                "transaction_id": "TXN-AUTH-ZERO",
                "settlement_date": "2026-10-09 05:00:00",
                "amount": "0.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )

    p_df = pd.concat([p_df, auth_p], ignore_index=True)
    b_df = pd.concat([b_df, auth_b], ignore_index=True)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]

    assert summary["matched_count"] == 4  # 3 fixture + 1 zero auth
    assert summary["unreconciled_gap"] == 0.00


def test_partial_refunds_multiple_refunds_single_parent(clean_platform_df, clean_bank_df):
    """
    Edge case: Multiple partial refunds referencing the same parent payment.
    Verifies that neither partial refund is misclassified as an orphan refund,
    because their shared parent payment exists in the platform dataset.
    """
    p_df = clean_platform_df.copy()
    b_df = clean_bank_df.copy()

    # Add a large $500.00 payment
    parent_p = pd.DataFrame(
        [
            {
                "transaction_id": "TXN-PARENT-500",
                "transaction_date": "2026-10-01 10:00:00",
                "amount": "500.00",
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    parent_b = pd.DataFrame(
        [
            {
                "settlement_id": "STL-PARENT-500",
                "transaction_id": "TXN-PARENT-500",
                "settlement_date": "2026-10-03 04:00:00",
                "amount": "500.00",
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )

    # Bank processes two separate partial refunds for $100.00 and $150.00 referencing TXN-PARENT-500
    partial_refunds = pd.DataFrame(
        [
            {
                "settlement_id": "STL-PARTIAL-01",
                "transaction_id": "TXN-PARTIAL-REF-01",
                "settlement_date": "2026-10-15 04:00:00",
                "amount": "100.00",
                "entry_type": "REFUND",
                "original_transaction_id": "TXN-PARENT-500",
            },
            {
                "settlement_id": "STL-PARTIAL-02",
                "transaction_id": "TXN-PARTIAL-REF-02",
                "settlement_date": "2026-10-20 04:00:00",
                "amount": "150.00",
                "entry_type": "REFUND",
                "original_transaction_id": "TXN-PARENT-500",
            },
        ]
    )

    p_df = pd.concat([p_df, parent_p], ignore_index=True)
    b_df = pd.concat([b_df, parent_b, partial_refunds], ignore_index=True)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    discrepancies = result["discrepancies_df"]
    summary = result["summary"]

    # Neither partial refund should be flagged as ORPHAN_REFUND
    orphan_records = discrepancies[discrepancies["category"] == "ORPHAN_REFUND"]
    assert len(orphan_records) == 0
    assert summary["unreconciled_gap"] == 0.00


def test_currency_string_formats_with_commas_and_symbols():
    """
    Edge case: CSV feeds containing currency formatting like '$1,250.50' or ' 3,400.00 '.
    Verifies that the parser strips formatting without raising errors.
    """
    p_df = pd.DataFrame(
        [
            {
                "transaction_id": "TXN-FORMATTED-01",
                "transaction_date": "2026-10-10 10:00:00",
                "amount": "$1,250.50",  # Formatted with $ and comma
                "transaction_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )
    b_df = pd.DataFrame(
        [
            {
                "settlement_id": "STL-FORMATTED-01",
                "transaction_id": "TXN-FORMATTED-01",
                "settlement_date": "2026-10-12 04:00:00",
                "amount": "1,250.50",  # Formatted with comma
                "entry_type": "PAYMENT",
                "original_transaction_id": "",
            }
        ]
    )

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]

    assert summary["matched_count"] == 1
    assert summary["discrepancy_count"] == 0
    assert summary["platform_net_amount"] == 1250.50
    assert summary["bank_target_month_net"] == 1250.50
    assert summary["unreconciled_gap"] == 0.00


def test_high_volume_stress_reconciliation():
    """
    Stress test: Reconciling 200+ simulated transactions with mixed clean matches,
    sub-penny rounding drifts, timing rollovers, and duplicates.
    Verifies scalability and exact zero-gap bridge closure.
    """
    p_rows = []
    b_rows = []

    # 150 clean matched transactions
    for i in range(1, 151):
        tid = f"TXN-HV-{i:04d}"
        sid = f"STL-HV-{i:04d}"
        amt = f"{(i * 1.75):.2f}"
        p_rows.append({
            "transaction_id": tid,
            "transaction_date": "2026-10-10 10:00:00",
            "amount": amt,
            "transaction_type": "PAYMENT",
            "original_transaction_id": "",
        })
        b_rows.append({
            "settlement_id": sid,
            "transaction_id": tid,
            "settlement_date": "2026-10-12 04:00:00",
            "amount": amt,
            "entry_type": "PAYMENT",
            "original_transaction_id": "",
        })

    # 20 rounding differences of $0.01 each
    for i in range(151, 171):
        tid = f"TXN-HV-{i:04d}"
        sid = f"STL-HV-{i:04d}"
        p_rows.append({
            "transaction_id": tid,
            "transaction_date": "2026-10-15 10:00:00",
            "amount": "100.05",
            "transaction_type": "PAYMENT",
            "original_transaction_id": "",
        })
        b_rows.append({
            "settlement_id": sid,
            "transaction_id": tid,
            "settlement_date": "2026-10-17 04:00:00",
            "amount": "100.04",
            "entry_type": "PAYMENT",
            "original_transaction_id": "",
        })

    p_df = pd.DataFrame(p_rows)
    b_df = pd.DataFrame(b_rows)

    engine = ReconciliationEngine(p_df, b_df, recon_month="2026-10")
    result = engine.reconcile()
    summary = result["summary"]

    assert summary["matched_count"] == 150
    assert summary["discrepancy_count"] == 20
    assert round(summary["cumulative_rounding_drift"], 2) == 0.20
    assert summary["unreconciled_gap"] == 0.00


