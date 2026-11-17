"""
reconciliation.py - Core Payment Reconciliation Engine

Implements high-precision financial reconciliation between:
1. Platform Transactions Ledger (instantaneous recording at transaction time)
2. Bank Settlement Feed (batched, delayed settlement)

Uses Python's Decimal library for exact fixed-point currency math,
preventing IEEE-754 floating-point errors.
"""

from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Dict, List, Tuple, Any, Optional
import pandas as pd


# Expected schemas
REQUIRED_PLATFORM_COLS = [
    "transaction_id",
    "transaction_date",
    "amount",
    "transaction_type",
    "original_transaction_id",
]

REQUIRED_BANK_COLS = [
    "settlement_id",
    "transaction_id",
    "settlement_date",
    "amount",
    "entry_type",
    "original_transaction_id",
]

VALID_TRANSACTION_TYPES = {"PAYMENT", "REFUND"}


def clean_id(val: Any) -> str:
    """Normalize identifier: strip whitespace, handle stringified nulls ('NULL', 'NaN', 'None')."""
    if val is None or pd.isna(val):
        return ""
    s = str(val).strip()
    if s.upper() in {"NAN", "NULL", "NONE", "<NA>", "UNDEFINED", ""}:
        return ""
    return s


def normalize_txn_id(val: Any) -> str:
    """Normalize transaction ID with uppercase and whitespace trimming for robust matching."""
    s = clean_id(val)
    return s.upper()


def extract_year_month(val: Any) -> str:
    """
    Extract YYYY-MM safely from string, tz-aware Timestamp, or naive datetime.
    Avoids TypeError when comparing tz-aware and tz-naive objects.
    """
    if val is None or pd.isna(val):
        return ""
    try:
        ts = pd.to_datetime(val)
        return ts.strftime("%Y-%m")
    except Exception:
        s = str(val).strip()
        return s[:7]


def to_decimal(val: Any) -> Decimal:
    """Safely convert numeric/string value (including '$' or commas) to 2-decimal-place Decimal."""
    if val is None or pd.isna(val) or str(val).strip() == "":
        return Decimal("0.00")
    try:
        # Clean currency symbols and thousands commas
        cleaned = str(val).strip().replace("$", "").replace(",", "")
        d = Decimal(cleaned)
        return d.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        raise ValueError(f"Cannot parse '{val}' as valid currency amount.")


def validate_platform_data(df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
    """
    Validates required columns, non-empty records, and data types for platform ledger.
    """
    if df is None or df.empty:
        return False, "Platform transactions file is empty."

    missing = [c for c in REQUIRED_PLATFORM_COLS if c not in df.columns]
    if missing:
        return False, f"Platform transactions missing required columns: {missing}"

    # Validate types
    for idx, row in df.iterrows():
        # Check transaction_type
        ttype = str(row["transaction_type"]).strip().upper()
        if ttype not in VALID_TRANSACTION_TYPES:
            return (
                False,
                f"Row {idx}: invalid transaction_type '{row['transaction_type']}'. Expected PAYMENT or REFUND.",
            )

        # Check amount parsability
        try:
            to_decimal(row["amount"])
        except ValueError as e:
            return False, f"Row {idx}: invalid amount value. {str(e)}"

        # Check date parsability
        try:
            pd.to_datetime(row["transaction_date"])
        except Exception:
            return (
                False,
                f"Row {idx}: invalid transaction_date '{row['transaction_date']}'.",
            )

    return True, None


def validate_bank_data(df: pd.DataFrame) -> Tuple[bool, Optional[str]]:
    """
    Validates required columns, non-empty records, and data types for bank settlements feed.
    """
    if df is None or df.empty:
        return False, "Bank settlements file is empty."

    missing = [c for c in REQUIRED_BANK_COLS if c not in df.columns]
    if missing:
        return False, f"Bank settlements missing required columns: {missing}"

    for idx, row in df.iterrows():
        etype = str(row["entry_type"]).strip().upper()
        if etype not in VALID_TRANSACTION_TYPES:
            return (
                False,
                f"Row {idx}: invalid entry_type '{row['entry_type']}'. Expected PAYMENT or REFUND.",
            )

        try:
            to_decimal(row["amount"])
        except ValueError as e:
            return False, f"Row {idx}: invalid amount value. {str(e)}"

        try:
            pd.to_datetime(row["settlement_date"])
        except Exception:
            return (
                False,
                f"Row {idx}: invalid settlement_date '{row['settlement_date']}'.",
            )

    return True, None


class ReconciliationEngine:
    """
    Multi-pass Payment Reconciliation Engine.
    
    Identifies:
    1. Duplicates in Platform and Bank feeds.
    2. Timing Rollovers (Transactions settling in the following month).
    3. Orphan Refunds (Bank refunds referencing non-existent platform transactions).
    4. Rounding Differences (Single penny and cumulative drift).
    5. Missing Bank Settlements.
    6. Clean 1:1 Matched records.
    """

    def __init__(
        self,
        platform_df: pd.DataFrame,
        bank_df: pd.DataFrame,
        recon_month: str = "2026-10",
        rounding_tolerance: Decimal = Decimal("0.02"),
    ):
        self.platform_df = platform_df.copy()
        self.bank_df = bank_df.copy()
        self.recon_month = recon_month
        self.rounding_tolerance = rounding_tolerance

        # Normalization
        self.platform_df["transaction_id"] = (
            self.platform_df["transaction_id"].apply(normalize_txn_id)
        )
        self.bank_df["transaction_id"] = (
            self.bank_df["transaction_id"].apply(normalize_txn_id)
        )
        self.bank_df["settlement_id"] = (
            self.bank_df["settlement_id"].astype(str).str.strip()
        )
        if "original_transaction_id" in self.platform_df.columns:
            self.platform_df["original_transaction_id"] = (
                self.platform_df["original_transaction_id"].apply(normalize_txn_id)
            )
        if "original_transaction_id" in self.bank_df.columns:
            self.bank_df["original_transaction_id"] = (
                self.bank_df["original_transaction_id"].apply(normalize_txn_id)
            )

        self.discrepancies: List[Dict[str, Any]] = []
        self.matches: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}

    def reconcile(self) -> Dict[str, Any]:
        """Runs the complete reconciliation pipeline and returns report."""
        # 1. Calculate raw ledger sums
        p_gross_pay = Decimal("0.00")
        p_gross_ref = Decimal("0.00")
        for _, row in self.platform_df.iterrows():
            amt = to_decimal(row["amount"])
            if str(row["transaction_type"]).strip().upper() == "PAYMENT":
                p_gross_pay += amt
            else:
                p_gross_ref += amt
        platform_net = p_gross_pay - p_gross_ref

        b_gross_pay = Decimal("0.00")
        b_gross_ref = Decimal("0.00")
        b_target_month_net = Decimal("0.00")
        for _, row in self.bank_df.iterrows():
            amt = to_decimal(row["amount"])
            is_target_month = extract_year_month(row["settlement_date"]) == self.recon_month
            if str(row["entry_type"]).strip().upper() == "PAYMENT":
                b_gross_pay += amt
                if is_target_month:
                    b_target_month_net += amt
            else:
                b_gross_ref += amt
                if is_target_month:
                    b_target_month_net -= amt
        bank_total_net = b_gross_pay - b_gross_ref

        # 2. Check for Platform Duplicates
        p_counts = self.platform_df["transaction_id"].value_counts()
        platform_dupe_ids = set(p_counts[p_counts > 1].index)
        for dupe_id in platform_dupe_ids:
            rows = self.platform_df[self.platform_df["transaction_id"] == dupe_id]
            for _, r in rows.iloc[1:].iterrows():
                amt = to_decimal(r["amount"])
                self.discrepancies.append(
                    {
                        "category": "PLATFORM_DUPLICATE",
                        "transaction_id": dupe_id,
                        "settlement_id": "N/A",
                        "platform_amount": float(amt),
                        "bank_amount": 0.0,
                        "difference": float(amt),
                        "explanation": f"Duplicate transaction entry recorded on platform. ID '{dupe_id}' appears {p_counts[dupe_id]} times.",
                    }
                )

        # 3. Check for Bank Duplicates
        b_counts = self.bank_df["transaction_id"].value_counts()
        bank_dupe_ids = set(b_counts[b_counts > 1].index)
        for dupe_id in bank_dupe_ids:
            rows = self.bank_df[self.bank_df["transaction_id"] == dupe_id]
            # Primary row is treated as primary; secondary rows flagged as bank duplicates
            for _, r in rows.iloc[1:].iterrows():
                amt = to_decimal(r["amount"])
                self.discrepancies.append(
                    {
                        "category": "BANK_DUPLICATE",
                        "transaction_id": dupe_id,
                        "settlement_id": str(r["settlement_id"]),
                        "platform_amount": 0.0,
                        "bank_amount": float(amt),
                        "difference": float(-amt),
                        "explanation": f"Duplicate settlement line by bank. Transaction ID '{dupe_id}' settled {b_counts[dupe_id]} times.",
                    }
                )

        # Build lookup dictionaries
        platform_lookup = {}
        for _, r in self.platform_df.iterrows():
            tid = r["transaction_id"]
            if tid not in platform_lookup:
                platform_lookup[tid] = r

        # Track first seen bank record by transaction_id to prevent duplicate matching
        bank_first_records = {}
        seen_bank_txns = set()

        # 4. Check Bank Records for Orphan Refunds and Matches
        for _, b_row in self.bank_df.iterrows():
            tid = b_row["transaction_id"]
            b_type = str(b_row["entry_type"]).strip().upper()
            b_amt = to_decimal(b_row["amount"])
            b_date_str = str(b_row["settlement_date"])
            orig_id = clean_id(b_row.get("original_transaction_id"))

            # Check if this is an orphan refund
            if b_type == "REFUND":
                has_orig_in_platform = (
                    orig_id in platform_lookup if orig_id != "" else False
                )
                has_tid_in_platform = tid in platform_lookup

                if not has_orig_in_platform and not has_tid_in_platform:
                    self.discrepancies.append(
                        {
                            "category": "ORPHAN_REFUND",
                            "transaction_id": tid,
                            "settlement_id": str(b_row["settlement_id"]),
                            "platform_amount": 0.0,
                            "bank_amount": float(b_amt),
                            "difference": float(-b_amt),
                            "explanation": f"Bank refund of ${b_amt} references original ID '{orig_id or 'NONE'}', which does not exist in platform records.",
                        }
                    )
                    continue

            # Secondary bank duplicates are skipped from 1:1 matching (already logged in Step 3)
            if tid in seen_bank_txns:
                continue
            seen_bank_txns.add(tid)
            bank_first_records[tid] = b_row

            # Compare with platform
            if tid in platform_lookup:
                p_row = platform_lookup[tid]
                p_amt = to_decimal(p_row["amount"])
                p_date_str = str(p_row["transaction_date"])
                diff = p_amt - b_amt

                b_ym = extract_year_month(b_date_str)
                p_ym = extract_year_month(p_date_str)

                # Check if settled in following month (Timing Rollover)
                if b_ym != self.recon_month and p_ym == self.recon_month:
                    self.discrepancies.append(
                        {
                            "category": "LATE_SETTLEMENT_NEXT_MONTH",
                            "transaction_id": tid,
                            "settlement_id": str(b_row["settlement_id"]),
                            "platform_amount": float(p_amt),
                            "bank_amount": float(b_amt),
                            "difference": float(p_amt),
                            "explanation": f"Timing Rollover: Authorized in {self.recon_month} ({p_date_str[:10]}), but settled by bank in next month ({b_date_str[:10]}).",
                        }
                    )
                # Check for rounding difference vs material amount mismatch
                elif diff != Decimal("0.00"):
                    if abs(diff) <= self.rounding_tolerance:
                        self.discrepancies.append(
                            {
                                "category": "ROUNDING_DIFFERENCE",
                                "transaction_id": tid,
                                "settlement_id": str(b_row["settlement_id"]),
                                "platform_amount": float(p_amt),
                                "bank_amount": float(b_amt),
                                "difference": float(diff),
                                "explanation": f"Sub-penny/fee rounding variance: Platform=${p_amt}, Bank=${b_amt} (Delta = ${diff:+.2f} within ${self.rounding_tolerance} tolerance).",
                            }
                        )
                    else:
                        self.discrepancies.append(
                            {
                                "category": "AMOUNT_MISMATCH",
                                "transaction_id": tid,
                                "settlement_id": str(b_row["settlement_id"]),
                                "platform_amount": float(p_amt),
                                "bank_amount": float(b_amt),
                                "difference": float(diff),
                                "explanation": f"Material amount mismatch: Platform=${p_amt}, Bank=${b_amt} (Delta = ${diff:+.2f} exceeds ${self.rounding_tolerance} tolerance).",
                            }
                        )
                else:
                    self.matches.append(
                        {
                            "transaction_id": tid,
                            "settlement_id": str(b_row["settlement_id"]),
                            "amount": float(p_amt),
                            "status": "CLEAN_MATCH",
                        }
                    )
            else:
                # Bank settlement exists with no platform transaction at all
                if b_type != "REFUND":
                    self.discrepancies.append(
                        {
                            "category": "UNMATCHED_BANK_PAYMENT",
                            "transaction_id": tid,
                            "settlement_id": str(b_row["settlement_id"]),
                            "platform_amount": 0.0,
                            "bank_amount": float(b_amt),
                            "difference": float(-b_amt),
                            "explanation": f"Bank received settlement of ${b_amt} for unknown transaction ID '{tid}'.",
                        }
                    )
                else:
                    # Bank processed a refund referencing a known platform parent, but platform never logged the refund row
                    self.discrepancies.append(
                        {
                            "category": "UNRECORDED_BANK_REFUND",
                            "transaction_id": tid,
                            "settlement_id": str(b_row["settlement_id"]),
                            "platform_amount": 0.0,
                            "bank_amount": float(b_amt),
                            "difference": float(-b_amt),
                            "explanation": f"Bank debited refund of ${b_amt} referencing parent ID '{orig_id}', but refund entry '{tid}' was never recorded on platform.",
                        }
                    )

        # 5. Check for Platform Transactions never settled in bank dataset
        for _, p_row in self.platform_df.iterrows():
            tid = p_row["transaction_id"]
            if tid not in bank_first_records:
                p_amt = to_decimal(p_row["amount"])
                p_date_str = str(p_row["transaction_date"])
                self.discrepancies.append(
                    {
                        "category": "MISSING_BANK_SETTLEMENT",
                        "transaction_id": tid,
                        "settlement_id": "N/A",
                        "platform_amount": float(p_amt),
                        "bank_amount": 0.0,
                        "difference": float(p_amt),
                        "explanation": f"Platform recorded payment on {p_date_str[:10]} for ${p_amt}, but no settlement was received from bank.",
                    }
                )

        # 6. Aggregate calculations & Category breakdown
        category_sums: Dict[str, Dict[str, Any]] = {}
        cumulative_rounding_drift = Decimal("0.00")
        total_timing_rollover = Decimal("0.00")
        total_bank_duplicates = Decimal("0.00")
        total_orphan_refunds = Decimal("0.00")
        total_platform_duplicates = Decimal("0.00")
        total_missing_bank_settlements = Decimal("0.00")
        total_amount_mismatches = Decimal("0.00")
        total_unmatched_bank_payments = Decimal("0.00")
        total_unrecorded_bank_refunds = Decimal("0.00")

        for d in self.discrepancies:
            cat = d["category"]
            diff_dec = Decimal(str(d["difference"]))
            if cat not in category_sums:
                category_sums[cat] = {"count": 0, "net_difference": Decimal("0.00")}
            category_sums[cat]["count"] += 1
            category_sums[cat]["net_difference"] += diff_dec

            if cat == "ROUNDING_DIFFERENCE":
                cumulative_rounding_drift += diff_dec
            elif cat == "LATE_SETTLEMENT_NEXT_MONTH":
                total_timing_rollover += Decimal(str(d["platform_amount"]))
            elif cat == "BANK_DUPLICATE":
                total_bank_duplicates += Decimal(str(d["bank_amount"]))
            elif cat == "ORPHAN_REFUND":
                total_orphan_refunds += Decimal(str(d["bank_amount"]))
            elif cat == "PLATFORM_DUPLICATE":
                total_platform_duplicates += Decimal(str(d["platform_amount"]))
            elif cat == "MISSING_BANK_SETTLEMENT":
                total_missing_bank_settlements += Decimal(str(d["platform_amount"]))
            elif cat == "AMOUNT_MISMATCH":
                total_amount_mismatches += diff_dec
            elif cat == "UNMATCHED_BANK_PAYMENT":
                total_unmatched_bank_payments += Decimal(str(d["bank_amount"]))
            elif cat == "UNRECORDED_BANK_REFUND":
                total_unrecorded_bank_refunds += Decimal(str(d["bank_amount"]))

        # Universal Generalized Reconciliation Bridge calculation:
        # Starting from Platform Net Book Balance to reach Bank Target Month Net:
        # - Deduct Platform amounts not in Bank Oct: Late settlements, missing settlements, platform duplicates, positive rate differences
        # + Add Bank amounts not in Platform: Bank duplicates, unmatched bank payments
        # - Deduct Bank debits not in Platform: Orphan refunds, unrecorded bank refunds
        adjusted_expected_bank = (
            platform_net
            - total_timing_rollover
            - total_missing_bank_settlements
            - total_platform_duplicates
            - cumulative_rounding_drift
            - total_amount_mismatches
            + total_bank_duplicates
            + total_unmatched_bank_payments
            - total_orphan_refunds
            - total_unrecorded_bank_refunds
        )
        unreconciled_gap = adjusted_expected_bank - b_target_month_net

        discrepancy_df = pd.DataFrame(self.discrepancies)
        if discrepancy_df.empty:
            discrepancy_df = pd.DataFrame(
                columns=[
                    "category",
                    "transaction_id",
                    "settlement_id",
                    "platform_amount",
                    "bank_amount",
                    "difference",
                    "explanation",
                ]
            )

        self.summary = {
            "platform_total_count": len(self.platform_df),
            "bank_total_count": len(self.bank_df),
            "matched_count": len(self.matches),
            "discrepancy_count": len(self.discrepancies),
            "platform_gross_payment": float(p_gross_pay),
            "platform_gross_refund": float(p_gross_ref),
            "platform_net_amount": float(platform_net),
            "bank_gross_payment": float(b_gross_pay),
            "bank_gross_refund": float(b_gross_ref),
            "bank_total_net_amount": float(bank_total_net),
            "bank_target_month_net": float(b_target_month_net),
            "raw_net_variance": float(platform_net - b_target_month_net),
            "cumulative_rounding_drift": float(cumulative_rounding_drift),
            "total_timing_rollover": float(total_timing_rollover),
            "total_bank_duplicates": float(total_bank_duplicates),
            "total_orphan_refunds": float(total_orphan_refunds),
            "total_platform_duplicates": float(total_platform_duplicates),
            "total_missing_bank_settlements": float(total_missing_bank_settlements),
            "total_amount_mismatches": float(total_amount_mismatches),
            "total_unmatched_bank_payments": float(total_unmatched_bank_payments),
            "adjusted_expected_bank": float(adjusted_expected_bank),
            "unreconciled_gap": float(unreconciled_gap),
            "category_breakdown": {
                k: {"count": v["count"], "net_difference": float(v["net_difference"])}
                for k, v in category_sums.items()
            },
        }

        return {
            "summary": self.summary,
            "discrepancies_df": discrepancy_df,
            "matches": self.matches,
        }

