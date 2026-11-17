"""
app.py - Streamlit Payment Reconciliation Dashboard

Interactive UI for uploading platform & bank settlement datasets,
running multi-pass reconciliation, inspecting the mathematical reconciliation bridge,
filtering discrepancy exceptions, and exporting audit reports.
"""

import io
import json
from decimal import Decimal
import pandas as pd
import streamlit as st

from reconciliation import (
    ReconciliationEngine,
    validate_platform_data,
    validate_bank_data,
)

# Page configuration
st.set_page_config(
    page_title="Payment Reconciliation Engine | Onelab",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Styling
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #F8FAFC;
        border-radius: 8px;
        padding: 16px;
        border: 1px solid #E2E8F0;
    }
    .bridge-table {
        font-family: monospace;
        font-size: 1.05rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_csv_data(uploaded_file, default_path):
    """Loads dataframe from either an uploaded file or the local default sample."""
    if uploaded_file is not None:
        try:
            return pd.read_csv(uploaded_file), None
        except Exception as e:
            return None, f"Failed to parse uploaded CSV: {str(e)}"
    else:
        try:
            return pd.read_csv(default_path), None
        except Exception as e:
            return None, f"Default dataset not found at '{default_path}': {str(e)}"


# Sidebar: Data Inputs & Configuration
st.sidebar.header("📁 Data Source & Settings")

data_mode = st.sidebar.radio(
    "Data Source Mode",
    ["Use Default Synthetic Test Data (Oct 2026)", "Upload Custom CSVs"],
    index=0,
)

uploaded_platform = None
uploaded_bank = None

if data_mode == "Upload Custom CSVs":
    st.sidebar.markdown("---")
    st.sidebar.subheader("Upload Datasets")
    uploaded_platform = st.sidebar.file_uploader(
        "Platform Transactions CSV",
        type=["csv"],
        help="Columns: transaction_id, transaction_date, amount, transaction_type, original_transaction_id",
    )
    uploaded_bank = st.sidebar.file_uploader(
        "Bank Settlements CSV",
        type=["csv"],
        help="Columns: settlement_id, transaction_id, settlement_date, amount, entry_type, original_transaction_id",
    )

st.sidebar.markdown("---")
st.sidebar.subheader("Reconciliation Parameters")
recon_month = st.sidebar.text_input(
    "Target Accounting Month (YYYY-MM)",
    value="2026-10",
    help="Transactions settled after this month are classified as late/in-transit rollover.",
)

rounding_tolerance_val = st.sidebar.number_input(
    "Rounding Tolerance ($)",
    min_value=0.00,
    max_value=1.00,
    value=0.02,
    step=0.01,
    help="Differences within this threshold are evaluated for cumulative precision drift.",
)

# Header
st.markdown("<div class='main-header'>⚖️ Payment Reconciliation System</div>", unsafe_allow_html=True)
st.markdown(
    "<div class='sub-header'>Automated Multi-Pass Transaction Matching, In-Transit Rollover Detection & Exception Attribution</div>",
    unsafe_allow_html=True,
)

# Load datasets
platform_df, p_err = load_csv_data(uploaded_platform, "data/platform_transactions.csv")
bank_df, b_err = load_csv_data(uploaded_bank, "data/bank_settlements.csv")

# Input error handling
if p_err or bank_df is None:
    st.error(f"⚠️ Error loading Platform dataset: {p_err}")
    st.stop()

if b_err or bank_df is None:
    st.error(f"⚠️ Error loading Bank dataset: {b_err}")
    st.stop()

# Schema Validation
is_p_valid, p_val_err = validate_platform_data(platform_df)
if not is_p_valid:
    st.error(f"❌ Platform Data Validation Failed: {p_val_err}")
    st.stop()

is_b_valid, b_val_err = validate_bank_data(bank_df)
if not is_b_valid:
    st.error(f"❌ Bank Data Validation Failed: {b_val_err}")
    st.stop()

# Run Reconciliation Engine
engine = ReconciliationEngine(
    platform_df=platform_df,
    bank_df=bank_df,
    recon_month=recon_month,
    rounding_tolerance=Decimal(str(rounding_tolerance_val)),
)
result = engine.reconcile()
summary = result["summary"]
discrepancies_df = result["discrepancies_df"]
matches = result["matches"]

# KPI Metrics Strip
st.subheader("📊 Executive Overview")
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

with kpi1:
    st.metric(
        label="Platform Book Net",
        value=f"${summary['platform_net_amount']:,.2f}",
        help=f"Gross Payments: ${summary['platform_gross_payment']:,.2f} | Gross Refunds: ${summary['platform_gross_refund']:,.2f}",
    )

with kpi2:
    st.metric(
        label=f"Bank Settled Net ({recon_month})",
        value=f"${summary['bank_target_month_net']:,.2f}",
        help=f"Bank Total In File: ${summary['bank_total_net_amount']:,.2f} (includes next-month settlements)",
    )

with kpi3:
    raw_var = summary["raw_net_variance"]
    st.metric(
        label="Raw Unadjusted Variance",
        value=f"${raw_var:,.2f}",
        delta=f"{raw_var:+.2f}",
        delta_color="inverse",
        help="Initial imbalance before gap attribution.",
    )

with kpi4:
    gap = summary["unreconciled_gap"]
    status_label = "✅ Balanced ($0.00)" if gap == 0.0 else f"⚠️ Unexplained: ${gap:,.2f}"
    st.metric(
        label="Reconciled Net Gap",
        value=status_label,
        help="Unexplained residual variance after adjusting for all identified anomalies.",
    )

# Transaction Count Metrics
c1, c2, c3, c4 = st.columns(4)
c1.caption(f"Platform Records: **{summary['platform_total_count']}**")
c2.caption(f"Bank Settlement Records: **{summary['bank_total_count']}**")
c3.caption(f"Clean Matched: **{summary['matched_count']}**")
c4.caption(f"Flagged Discrepancies: **{summary['discrepancy_count']}**")

st.markdown("---")

# The Reconciliation Waterfall Bridge
st.subheader("🌉 The Accounting Reconciliation Bridge")
st.markdown(
    "How the Platform Book Balance reconciles mathematically to the actual cash at the bank:"
)

bridge_data = [
    ("1. Platform Net Book Balance", f"${summary['platform_net_amount']:,.2f}", "Starting balance from platform ledger"),
]

if summary["total_timing_rollover"] > 0:
    bridge_data.append(("  - Less: Month-End Timing Rollover", f"-${summary['total_timing_rollover']:,.2f}", "Customer paid late in target month; bank settles in next month"))

if summary.get("total_missing_bank_settlements", 0) > 0:
    bridge_data.append(("  - Less: Missing Bank Settlements", f"-${summary['total_missing_bank_settlements']:,.2f}", "Platform recorded transactions that never settled"))

if summary.get("total_platform_duplicates", 0) > 0:
    bridge_data.append(("  - Less: Platform Duplicate Entries", f"-${summary['total_platform_duplicates']:,.2f}", "Double-booked transaction records on platform"))

if summary.get("total_amount_mismatches", 0) != 0:
    diff_val = summary["total_amount_mismatches"]
    sign_str = "-" if diff_val > 0 else "+"
    bridge_data.append((f"  {sign_str} Delta: Material Amount Mismatches", f"{sign_str}${abs(diff_val):,.2f}", "Differences exceeding rounding tolerance threshold"))

if summary["cumulative_rounding_drift"] != 0:
    drift_val = summary["cumulative_rounding_drift"]
    sign_str = "-" if drift_val > 0 else "+"
    bridge_data.append((f"  {sign_str} Net: Cumulative Rounding Drift", f"{sign_str}${abs(drift_val):,.2f}", "Sub-penny rate rounding accumulated across rows"))

if summary["total_bank_duplicates"] > 0:
    bridge_data.append(("  + Plus: Bank Duplicate Settlement", f"+${summary['total_bank_duplicates']:,.2f}", "Bank duplicated credit into cash account"))

if summary.get("total_unmatched_bank_payments", 0) > 0:
    bridge_data.append(("  + Plus: Unmatched Bank Credits", f"+${summary['total_unmatched_bank_payments']:,.2f}", "Bank received funds for transactions not in platform"))

if summary["total_orphan_refunds"] > 0:
    bridge_data.append(("  - Less: Orphan Bank Refund Deducted", f"-${summary['total_orphan_refunds']:,.2f}", "Bank clawback/refund with no platform original"))

bridge_data.extend([
    ("= Adjusted Expected Bank Balance", f"${summary['adjusted_expected_bank']:,.2f}", "Calculated expected cash position"),
    ("Actual Bank Settlement in Target Month", f"${summary['bank_target_month_net']:,.2f}", "Total settled funds according to bank statement"),
    ("Final Unreconciled Gap", f"${summary['unreconciled_gap']:,.2f}", "Target is $0.00 (Fully Reconciled)"),
])

bridge_df = pd.DataFrame(bridge_data, columns=["Accounting Line Item", "Amount ($)", "Financial Context"])
st.table(bridge_df)

if summary["unreconciled_gap"] == 0.0:
    st.success("🎉 Books balance completely! 100% of the variance is mathematically accounted for.")
else:
    st.warning(f"⚠️ Unexplained residual gap of ${summary['unreconciled_gap']:,.2f} requires further investigation.")

st.markdown("---")

# Discrepancy Investigation Table
st.subheader("🔍 Discrepancy Investigator & Audit Log")

col_filter1, col_filter2 = st.columns([1, 2])
categories = ["ALL"] + sorted(list(discrepancies_df["category"].unique())) if not discrepancies_df.empty else ["ALL"]

with col_filter1:
    selected_cat = st.selectbox("Filter by Category", categories)

with col_filter2:
    search_term = st.text_input("Search by Transaction ID or Settlement ID", "")

filtered_df = discrepancies_df.copy()
if selected_cat != "ALL":
    filtered_df = filtered_df[filtered_df["category"] == selected_cat]

if search_term.strip():
    term = search_term.strip().lower()
    filtered_df = filtered_df[
        filtered_df["transaction_id"].str.lower().str.contains(term)
        | filtered_df["settlement_id"].str.lower().str.contains(term)
    ]

# Display table
st.dataframe(
    filtered_df,
    use_container_width=True,
    column_config={
        "category": st.column_config.TextColumn("Anomaly Category"),
        "transaction_id": st.column_config.TextColumn("Platform Txn ID"),
        "settlement_id": st.column_config.TextColumn("Bank Settlement ID"),
        "platform_amount": st.column_config.NumberColumn("Platform ($)", format="$%.2f"),
        "bank_amount": st.column_config.NumberColumn("Bank ($)", format="$%.2f"),
        "difference": st.column_config.NumberColumn("Delta ($)", format="$%+.2f"),
        "explanation": st.column_config.TextColumn("Audit Explanation"),
    },
    hide_index=True,
)

# Export options
st.markdown("---")
st.subheader("📥 Export Reports")

exp_col1, exp_col2 = st.columns(2)

with exp_col1:
    csv_buffer = io.StringIO()
    discrepancies_df.to_csv(csv_buffer, index=False)
    st.download_button(
        label="Download Discrepancies CSV",
        data=csv_buffer.getvalue(),
        file_name="reconciliation_discrepancies.csv",
        mime="text/csv",
    )

with exp_col2:
    audit_json = json.dumps(summary, indent=2)
    st.download_button(
        label="Download Full Audit Summary (JSON)",
        data=audit_json,
        file_name="reconciliation_audit_summary.json",
        mime="application/json",
    )

