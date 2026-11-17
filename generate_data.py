"""
generate_data.py - Synthetic Dataset Generator for Payment Reconciliation

Generates realistic CSV datasets for October 2026:
1. platform_transactions.csv
2. bank_settlements.csv

Plants 4 specific reconciliation anomalies:
1. Timing Rollover (Transaction created late in October settling in November)
2. Cumulative Rounding Differences (Multiple sub-penny discrepancies summing to visible drift)
3. Duplicate Bank Settlement (Single platform transaction settled twice)
4. Orphan Bank Refund (Bank refund referencing a non-existent platform transaction)
"""

import os
import csv
import argparse
from decimal import Decimal
from typing import List, Tuple


def generate_synthetic_data(output_dir: str = "data"):
    """Generates synthetic datasets with deterministic planted anomalies."""
    os.makedirs(output_dir, exist_ok=True)

    platform_rows = [
        # Normal Clean Matched Transactions (Payments)
        ("TXN-2026-1001-001", "2026-10-01 09:12:00", "150.00", "PAYMENT", ""),
        ("TXN-2026-1002-002", "2026-10-02 11:30:00", "245.50", "PAYMENT", ""),
        ("TXN-2026-1003-003", "2026-10-03 14:15:00", "89.99", "PAYMENT", ""),
        ("TXN-2026-1004-004", "2026-10-04 16:45:00", "520.00", "PAYMENT", ""),
        ("TXN-2026-1005-005", "2026-10-05 08:20:00", "12.50", "PAYMENT", ""),
        ("TXN-2026-1006-006", "2026-10-06 10:05:00", "310.00", "PAYMENT", ""),
        ("TXN-2026-1007-007", "2026-10-07 13:40:00", "75.25", "PAYMENT", ""),
        ("TXN-2026-1008-008", "2026-10-08 15:55:00", "980.00", "PAYMENT", ""),
        ("TXN-2026-1009-009", "2026-10-09 17:10:00", "42.00", "PAYMENT", ""),
        ("TXN-2026-1010-010", "2026-10-10 12:00:00", "630.75", "PAYMENT", ""),
        ("TXN-2026-1011-011", "2026-10-11 18:25:00", "115.00", "PAYMENT", ""),
        # Target of Bank Duplicate
        ("TXN-2026-1012-012", "2026-10-12 09:50:00", "320.00", "PAYMENT", ""),
        ("TXN-2026-1013-013", "2026-10-13 14:35:00", "850.00", "PAYMENT", ""),
        ("TXN-2026-1014-014", "2026-10-14 11:15:00", "64.90", "PAYMENT", ""),
        ("TXN-2026-1015-015", "2026-10-15 16:05:00", "410.00", "PAYMENT", ""),
        ("TXN-2026-1016-016", "2026-10-16 10:45:00", "195.00", "PAYMENT", ""),
        ("TXN-2026-1017-017", "2026-10-17 13:20:00", "275.50", "PAYMENT", ""),
        ("TXN-2026-1018-018", "2026-10-18 15:00:00", "50.00", "PAYMENT", ""),
        ("TXN-2026-1019-019", "2026-10-19 12:10:00", "720.00", "PAYMENT", ""),
        ("TXN-2026-1020-020", "2026-10-20 17:40:00", "135.25", "PAYMENT", ""),
        # Clean Matched Refunds
        ("TXN-2026-1021-021", "2026-10-21 11:00:00", "42.00", "REFUND", "TXN-2026-1009-009"),
        ("TXN-2026-1022-022", "2026-10-22 14:50:00", "50.00", "REFUND", "TXN-2026-1018-018"),
        ("TXN-2026-1023-023", "2026-10-23 09:30:00", "880.00", "PAYMENT", ""),
        ("TXN-2026-1024-024", "2026-10-24 16:15:00", "210.00", "PAYMENT", ""),
        # Planted Gap 2: Rounding Drift Group (Sub-penny rounding producing +$0.12 aggregate drift)
        ("TXN-2026-1025-025", "2026-10-25 10:20:00", "100.55", "PAYMENT", ""),
        ("TXN-2026-1026-026", "2026-10-26 12:45:00", "230.48", "PAYMENT", ""),
        ("TXN-2026-1027-027", "2026-10-27 15:10:00", "345.82", "PAYMENT", ""),
        ("TXN-2026-1028-028", "2026-10-28 09:05:00", "180.36", "PAYMENT", ""),
        ("TXN-2026-1029-029", "2026-10-28 14:20:00", "420.94", "PAYMENT", ""),
        ("TXN-2026-1030-030", "2026-10-29 11:55:00", "75.66", "PAYMENT", ""),
        ("TXN-2026-1031-031", "2026-10-29 16:30:00", "560.73", "PAYMENT", ""),
        ("TXN-2026-1032-032", "2026-10-30 10:15:00", "290.88", "PAYMENT", ""),
        # Planted Gap 1: Timing Rollover (Settles on Nov 2)
        ("TXN-2026-1033-033", "2026-10-31 22:50:00", "450.00", "PAYMENT", ""),
        ("TXN-2026-1034-034", "2026-10-30 15:40:00", "315.00", "PAYMENT", ""),
        ("TXN-2026-1035-035", "2026-10-31 08:15:00", "125.00", "PAYMENT", ""),
    ]

    bank_rows = [
        # Corresponding settlements for clean matched
        ("STL-2026-1003-001", "TXN-2026-1001-001", "2026-10-03 04:30:00", "150.00", "PAYMENT", ""),
        ("STL-2026-1004-002", "TXN-2026-1002-002", "2026-10-04 05:00:00", "245.50", "PAYMENT", ""),
        ("STL-2026-1005-003", "TXN-2026-1003-003", "2026-10-05 04:15:00", "89.99", "PAYMENT", ""),
        ("STL-2026-1006-004", "TXN-2026-1004-004", "2026-10-06 06:10:00", "520.00", "PAYMENT", ""),
        ("STL-2026-1007-005", "TXN-2026-1005-005", "2026-10-07 04:45:00", "12.50", "PAYMENT", ""),
        ("STL-2026-1008-006", "TXN-2026-1006-006", "2026-10-08 05:20:00", "310.00", "PAYMENT", ""),
        ("STL-2026-1009-007", "TXN-2026-1007-007", "2026-10-09 04:50:00", "75.25", "PAYMENT", ""),
        ("STL-2026-1010-008", "TXN-2026-1008-008", "2026-10-10 05:40:00", "980.00", "PAYMENT", ""),
        ("STL-2026-1011-009", "TXN-2026-1009-009", "2026-10-11 04:30:00", "42.00", "PAYMENT", ""),
        ("STL-2026-1012-010", "TXN-2026-1010-010", "2026-10-12 06:00:00", "630.75", "PAYMENT", ""),
        ("STL-2026-1013-011", "TXN-2026-1011-011", "2026-10-13 04:40:00", "115.00", "PAYMENT", ""),
        # Planted Gap 3: Duplicate Bank settlement lines for TXN-2026-1012-012
        ("STL-2026-1014-012", "TXN-2026-1012-012", "2026-10-14 05:15:00", "320.00", "PAYMENT", ""),
        ("STL-2026-1014-013", "TXN-2026-1012-012", "2026-10-14 05:15:00", "320.00", "PAYMENT", ""),
        ("STL-2026-1015-014", "TXN-2026-1013-013", "2026-10-15 05:50:00", "850.00", "PAYMENT", ""),
        ("STL-2026-1016-015", "TXN-2026-1014-014", "2026-10-16 04:25:00", "64.90", "PAYMENT", ""),
        ("STL-2026-1017-016", "TXN-2026-1015-015", "2026-10-17 06:30:00", "410.00", "PAYMENT", ""),
        ("STL-2026-1018-017", "TXN-2026-1016-016", "2026-10-18 04:55:00", "195.00", "PAYMENT", ""),
        ("STL-2026-1019-018", "TXN-2026-1017-017", "2026-10-19 05:10:00", "275.50", "PAYMENT", ""),
        ("STL-2026-1020-019", "TXN-2026-1018-018", "2026-10-20 04:35:00", "50.00", "PAYMENT", ""),
        ("STL-2026-1021-020", "TXN-2026-1019-019", "2026-10-21 06:15:00", "720.00", "PAYMENT", ""),
        ("STL-2026-1022-021", "TXN-2026-1020-020", "2026-10-22 04:45:00", "135.25", "PAYMENT", ""),
        # Matched refunds
        ("STL-2026-1023-022", "TXN-2026-1021-021", "2026-10-23 05:00:00", "42.00", "REFUND", "TXN-2026-1009-009"),
        ("STL-2026-1024-023", "TXN-2026-1022-022", "2026-10-24 05:25:00", "50.00", "REFUND", "TXN-2026-1018-018"),
        ("STL-2026-1025-024", "TXN-2026-1023-023", "2026-10-25 06:05:00", "880.00", "PAYMENT", ""),
        ("STL-2026-1026-025", "TXN-2026-1024-024", "2026-10-26 04:40:00", "210.00", "PAYMENT", ""),
        # Planted Gap 2: Settlements with 1-2 cent sub-penny rounding
        ("STL-2026-1027-026", "TXN-2026-1025-025", "2026-10-27 05:10:00", "100.54", "PAYMENT", ""),
        ("STL-2026-1028-027", "TXN-2026-1026-026", "2026-10-28 05:30:00", "230.47", "PAYMENT", ""),
        ("STL-2026-1029-028", "TXN-2026-1027-027", "2026-10-29 05:55:00", "345.80", "PAYMENT", ""),
        ("STL-2026-1030-029", "TXN-2026-1028-028", "2026-10-30 04:35:00", "180.35", "PAYMENT", ""),
        ("STL-2026-1031-030", "TXN-2026-1029-029", "2026-10-31 06:10:00", "420.92", "PAYMENT", ""),
        ("STL-2026-1031-031", "TXN-2026-1030-030", "2026-10-31 06:40:00", "75.65", "PAYMENT", ""),
        ("STL-2026-1031-032", "TXN-2026-1031-031", "2026-10-31 07:15:00", "560.71", "PAYMENT", ""),
        ("STL-2026-1031-033", "TXN-2026-1032-032", "2026-10-31 07:50:00", "290.86", "PAYMENT", ""),
        ("STL-2026-1031-034", "TXN-2026-1034-034", "2026-10-31 08:30:00", "315.00", "PAYMENT", ""),
        ("STL-2026-1031-035", "TXN-2026-1035-035", "2026-10-31 09:00:00", "125.00", "PAYMENT", ""),
        # Planted Gap 4: Orphan bank refund referencing out-of-period original ID
        ("STL-2026-1028-036", "TXN-2026-ORPHAN-REF", "2026-10-28 14:00:00", "185.00", "REFUND", "TXN-2026-0815-999"),
        # Planted Gap 1: Timing Rollover settling on Nov 2
        ("STL-2026-1102-037", "TXN-2026-1033-033", "2026-11-02 04:30:00", "450.00", "PAYMENT", ""),
    ]

    p_path = os.path.join(output_dir, "platform_transactions.csv")
    b_path = os.path.join(output_dir, "bank_settlements.csv")

    with open(p_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["transaction_id", "transaction_date", "amount", "transaction_type", "original_transaction_id"])
        for r in platform_rows:
            writer.writerow(r)

    with open(b_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["settlement_id", "transaction_id", "settlement_date", "amount", "entry_type", "original_transaction_id"])
        for r in bank_rows:
            writer.writerow(r)

    print(f"Generated {len(platform_rows)} platform records -> {p_path}")
    print(f"Generated {len(bank_rows)} bank records -> {b_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic payment reconciliation test data.")
    parser.add_argument("--output-dir", default="data", help="Output directory for CSV files")
    args = parser.parse_args()
    generate_synthetic_data(args.output_dir)

