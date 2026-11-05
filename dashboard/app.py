"""
Financial Data Quality & Cross-Source Reconciliation Investigation Workspace
Entrypoint: dashboard/app.py

A calm, analytical Streamlit workspace backed by the local SQLite snapshot
(`data/financial_data.db`). Preserves all existing database schemas, quality rules,
thresholds, reconciliation formulas, and helper functions while providing:
  1. Dataset Overview (coverage, snapshot vs. live ingestion metadata, reported vs. derived metrics)
  2. Quality Investigations (explicit dataset vs. filtered scope, observation framing, enriched context)
  3. Cross-Source Reconciliation (overlapping coverage, matched/mismatched/unmatched, test vs. saved-snapshot separation)
  4. Record Detail & Lineage (reported vs. derived badges, multi-period context, collapsible filing metadata)
  5. Methodology & Limitations (all 12 rule definitions, thresholds, case studies, and 14 documented limitations)
"""

from contextlib import closing
from datetime import datetime, timezone
import html
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest_market import MARKET_CLOSE_TOLERANCE_PERCENT, compare_market_closes
from src.quality import (
    ANOMALY_EXPLANATION,
    EXPECTED_FINANCIAL_METRICS,
    IQR_MULTIPLIER,
    check_market_close_reconciliation,
)

DATABASE_PATH = PROJECT_ROOT / "data" / "financial_data.db"

st.set_page_config(
    page_title="Financial Data Quality & Reconciliation Workspace",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Minimal, compatible CSS using semantic workspace classes only (no brittle emotion selectors,
# no pulsing/animated badges, and high-contrast light/slate surfaces with blue & teal accents).
APP_CSS = """
<style>
.stApp {
    background-color: #F8FAFC;
    color: #0F172A;
}
.ws-header {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-top: 3px solid #1E40AF;
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 14px;
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
}
.ws-brand-row {
    display: flex;
    align-items: center;
    gap: 12px;
}
.ws-brand-mark {
    width: 38px;
    height: 38px;
    border-radius: 6px;
    background-color: #1E40AF;
    color: #FFFFFF;
    font-weight: 700;
    font-size: 14px;
    letter-spacing: 0.04em;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
}
.ws-brand-title {
    margin: 0;
    font-size: 18px;
    font-weight: 700;
    color: #0F172A;
    line-height: 1.25;
}
.ws-brand-subtitle {
    margin: 2px 0 0 0;
    font-size: 13px;
    color: #475569;
    line-height: 1.35;
}
.ws-header-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
}
.ws-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: 0.02em;
    border: 1px solid transparent;
    white-space: nowrap;
}
.tone-healthy, .tone-green, .tone-positive {
    background-color: #ECFDF5;
    color: #065F46;
    border-color: #A7F3D0;
}
.tone-warning, .tone-amber {
    background-color: #FFFBEB;
    color: #92400E;
    border-color: #FDE68A;
}
.tone-failed, .tone-critical, .tone-red {
    background-color: #FEF2F2;
    color: #991B1B;
    border-color: #FECACA;
}
.tone-unavailable, .tone-neutral {
    background-color: #F1F5F9;
    color: #334155;
    border-color: #CBD5E1;
}
.tone-info, .tone-blue {
    background-color: #EFF6FF;
    color: #1E40AF;
    border-color: #BFDBFE;
}
.tone-teal {
    background-color: #F0FDFA;
    color: #0F766E;
    border-color: #99F6E4;
}
.ws-page-heading {
    margin: 6px 0 14px 0;
    padding-bottom: 10px;
    border-bottom: 1px solid #E2E8F0;
}
.ws-eyebrow {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: #0F766E;
    margin-bottom: 3px;
}
.ws-page-title {
    margin: 0;
    font-size: 22px;
    font-weight: 700;
    color: #0F172A;
    line-height: 1.25;
}
.ws-page-description {
    margin: 5px 0 0 0;
    font-size: 13.5px;
    color: #334155;
    line-height: 1.45;
}
.ws-scope-banner {
    background-color: #F1F5F9;
    border: 1px solid #CBD5E1;
    border-left: 4px solid #0F766E;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 8px 0 14px 0;
    font-size: 13px;
    color: #1E293B;
    line-height: 1.45;
}
.ws-scope-banner strong {
    color: #0F172A;
}
.ws-callout {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-left: 4px solid #1E40AF;
    border-radius: 6px;
    padding: 11px 14px;
    margin: 8px 0 14px 0;
    font-size: 13px;
    color: #1E293B;
    line-height: 1.45;
}
.ws-callout-warn {
    border-left-color: #B45309;
    background-color: #FFFBEB;
    border-color: #FDE68A;
    color: #78350F;
}
.ws-metric-card {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 7px;
    padding: 12px 14px;
    margin-bottom: 10px;
    height: 100%;
}
.ws-metric-topline {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-start;
    gap: 6px;
    margin-bottom: 6px;
}
.ws-metric-label {
    font-size: 11.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #475569;
}
.ws-metric-value {
    font-size: 22px;
    font-weight: 700;
    color: #0F172A;
    line-height: 1.2;
    margin-bottom: 6px;
    font-variant-numeric: tabular-nums;
}
.ws-metric-bar {
    height: 4px;
    background-color: #E2E8F0;
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 7px;
}
.ws-metric-bar > span {
    display: block;
    height: 100%;
    border-radius: 2px;
}
.fill-healthy, .fill-green, .fill-positive { background-color: #0D9488; }
.fill-warning, .fill-amber { background-color: #D97706; }
.fill-failed, .fill-critical, .fill-red { background-color: #DC2626; }
.fill-unavailable, .fill-neutral { background-color: #64748B; }
.fill-info, .fill-blue { background-color: #2563EB; }
.fill-teal { background-color: #0F766E; }
.ws-metric-note {
    font-size: 12px;
    color: #475569;
    line-height: 1.35;
}
.ws-section-heading {
    margin-top: 16px;
    margin-bottom: 2px;
    font-size: 16px;
    font-weight: 700;
    color: #0F172A;
}
.ws-section-note {
    margin-bottom: 10px;
    font-size: 12.5px;
    color: #475569;
    line-height: 1.4;
}
.ws-detail-card {
    background-color: #FFFFFF;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 8px;
}
.ws-detail-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #475569;
    margin-bottom: 3px;
}
.ws-detail-value {
    font-size: 13.5px;
    font-weight: 600;
    color: #0F172A;
    line-height: 1.35;
    word-break: break-word;
    font-variant-numeric: tabular-nums;
}
.ws-message-card {
    background-color: #F8FAFC;
    border: 1px solid #CBD5E1;
    border-left: 4px solid #1E40AF;
    border-radius: 6px;
    padding: 11px 14px;
    margin: 8px 0 12px 0;
    font-size: 13px;
    color: #0F172A;
    line-height: 1.45;
}
.ws-message-card strong {
    display: block;
    font-size: 11.5px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #334155;
    margin-bottom: 3px;
}
@media (max-width: 768px) {
    .ws-header {
        flex-direction: column;
        align-items: flex-start;
    }
    .ws-metric-value {
        font-size: 19px;
    }
    .ws-badge {
        white-space: normal;
        line-height: 1.25;
    }
}
</style>
"""

RULE_CATALOG = {
    "missing_financial_metric": {
        "domain": "SEC Financials",
        "table": "financial_metric",
        "dimension": "Completeness",
        "severity": "CRITICAL",
        "classification": "Deterministic Rule",
        "threshold": "All 6 canonical metrics present per company & annual period",
        "expected_text": "All six required annual metrics (Revenue, Assets, Liabilities, Equity, Net Income, Operating Income) present",
        "notes": "Evaluated after transparent derivation of Liabilities (Assets - Equity) where plain Liabilities tag is omitted.",
    },
    "duplicate_financial_metric": {
        "domain": "SEC Financials",
        "table": "financial_metric",
        "dimension": "Uniqueness",
        "severity": "MEDIUM",
        "classification": "Deterministic Rule",
        "threshold": "Exactly 1 record per (ticker, metric_name, period_end)",
        "expected_text": "One canonical record per company, metric, and period_end",
        "notes": "Flags duplicate period-end observations remaining after annual deduplication.",
    },
    "balance_sheet_equation": {
        "domain": "SEC Financials",
        "table": "financial_metric",
        "dimension": "Consistency",
        "severity": "CRITICAL",
        "classification": "Deterministic Rule",
        "threshold": "|Assets - (Liabilities + Equity)| / |Assets| <= 5.0% (0.05)",
        "expected_text": "Difference between Assets and (Liabilities + Equity) at or below 5% of Assets",
        "notes": "Skipped when Liabilities was derived from Assets - Equity (is_derived = 1) to prevent circular validation.",
    },
    "unusual_financial_growth_iqr": {
        "domain": "SEC Financials",
        "table": "financial_metric",
        "dimension": "Consistency",
        "severity": "MEDIUM",
        "classification": "Statistical Anomaly (IQR)",
        "threshold": "|YoY Change| <= Q3 + 1.5 x IQR (pooled by metric across companies)",
        "expected_text": "Year-over-year Revenue or Net Income change within pooled IQR upper fence (Q3 + 1.5 x IQR)",
        "notes": "Investigation prompt only; large earnings swings (e.g., AMZN FY2022 to FY2023 turnaround) can be genuine filing events.",
    },
    "stale_financial_data": {
        "domain": "SEC Financials",
        "table": "financial_metric",
        "dimension": "Timeliness",
        "severity": "LOW",
        "classification": "Deterministic Rule",
        "threshold": "Latest annual period_end age <= 550 calendar days as of the quality-run date",
        "expected_text": "Latest annual period no more than 550 calendar days old as of the quality-run date",
        "notes": "Detects companies missing recent annual 10-K filings in the stored snapshot.",
    },
    "nonpositive_price": {
        "domain": "Market Prices",
        "table": "market_price",
        "dimension": "Validity",
        "severity": "CRITICAL",
        "classification": "Deterministic Rule",
        "threshold": "Open > 0, High > 0, Low > 0, Close > 0",
        "expected_text": "Every daily OHLC price strictly greater than zero",
        "notes": "Validates basic positivity across primary Yahoo Finance daily bars.",
    },
    "negative_volume": {
        "domain": "Market Prices",
        "table": "market_price",
        "dimension": "Validity",
        "severity": "CRITICAL",
        "classification": "Deterministic Rule",
        "threshold": "Volume >= 0",
        "expected_text": "Daily trading volume zero or greater",
        "notes": "Flags corrupted negative volume integers.",
    },
    "high_below_low": {
        "domain": "Market Prices",
        "table": "market_price",
        "dimension": "Consistency",
        "severity": "CRITICAL",
        "classification": "Deterministic Rule",
        "threshold": "High >= Low",
        "expected_text": "Daily high price at or above daily low price",
        "notes": "Checks internal intraday range ordering.",
    },
    "ohlc_consistency": {
        "domain": "Market Prices",
        "table": "market_price",
        "dimension": "Consistency",
        "severity": "CRITICAL",
        "classification": "Deterministic Rule",
        "threshold": "Low <= Open <= High and Low <= Close <= High",
        "expected_text": "Daily open and close prices within the [Low, High] interval",
        "notes": "Flags bars where open or close falls outside the reported day range.",
    },
    "unusual_daily_return_iqr": {
        "domain": "Market Prices",
        "table": "market_price",
        "dimension": "Consistency",
        "severity": "LOW",
        "classification": "Statistical Anomaly (IQR)",
        "threshold": "|Daily Close Return| <= Q3 + 1.5 x IQR (computed per ticker)",
        "expected_text": "Daily absolute close-to-close return within ticker-specific IQR upper fence (Q3 + 1.5 x IQR)",
        "notes": "Statistical volatility observation for review; earnings-day or macro jumps are not automatic feed errors.",
    },
    "stale_market_data": {
        "domain": "Market Prices",
        "table": "market_price",
        "dimension": "Timeliness",
        "severity": "MEDIUM",
        "classification": "Deterministic Rule",
        "threshold": "Ticker latest price_date age <= 7 calendar days as of the quality-run date",
        "expected_text": "Latest market trading date no more than 7 calendar days old as of the quality-run date",
        "notes": "Age is measured against date.today() when src/quality.py runs; opening this dashboard does not rerun checks.",
    },
    "market_close_reconciliation": {
        "domain": "Cross-Source Reconciliation",
        "table": "reconciliation_result",
        "dimension": "Consistency",
        "severity": "MEDIUM",
        "classification": "Deterministic Rule",
        "threshold": f"|Close_A - Close_B| / |Close_A| * 100 <= {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%",
        "expected_text": f"Yahoo Finance and Nasdaq closing prices agree within {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% tolerance",
        "notes": "Filters out minor decimal-precision noise between providers while flagging material breaks.",
    },
}

STATISTICAL_RULES = {"unusual_financial_growth_iqr", "unusual_daily_return_iqr"}


def _connect_readonly():
    """Open SQLite in read-only mode so UI interactions never mutate the snapshot."""
    uri = DATABASE_PATH.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def read_query(query, parameters=()):
    """Execute a read-only SQL query and return a pandas DataFrame."""
    with closing(_connect_readonly()) as connection:
        return pd.read_sql_query(query, connection, params=parameters)


def get_single_value(query, parameters=()):
    """Execute a scalar read-only SQL query and return the first value."""
    with closing(_connect_readonly()) as connection:
        row = connection.execute(query, parameters).fetchone()
        return row[0] if row is not None else None


def safe_text(value):
    """HTML-escape a value and explicitly display 'Not available' when missing."""
    if value is None:
        return "Not available"
    try:
        if pd.isna(value):
            return "Not available"
    except Exception:
        pass
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return "Not available"
    return html.escape(text)


def format_currency_compact(value, unit="USD"):
    """Format large financial values in readable billions/millions alongside unit."""
    if value is None or pd.isna(value):
        return "Not available"
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)
    sign = "-" if num < 0 else ""
    abs_num = abs(num)
    prefix = "$" if str(unit).upper() == "USD" else ""
    suffix = "" if str(unit).upper() == "USD" else f" {unit}"
    if abs_num >= 1e9:
        return f"{sign}{prefix}{abs_num / 1e9:,.3f}B{suffix}"
    if abs_num >= 1e6:
        return f"{sign}{prefix}{abs_num / 1e6:,.2f}M{suffix}"
    return f"{sign}{prefix}{abs_num:,.2f}{suffix}"


def classify_flag_type(rule_name):
    """Distinguish statistical IQR anomaly observations from deterministic rule breaches."""
    if str(rule_name) in STATISTICAL_RULES:
        return "Statistical Anomaly (IQR)"
    return "Deterministic Rule"


def format_severity_label(severity):
    """Always pair severity level with an explicit state label."""
    sev = str(severity or "").upper()
    if sev == "CRITICAL":
        return "CRITICAL · Failed / Action Required"
    if sev == "MEDIUM":
        return "MEDIUM · Warning / Analyst Review"
    if sev == "LOW":
        return "LOW · Observation / Informational"
    return "UNAVAILABLE · Not available"


def severity_tone(severity):
    sev = str(severity or "").upper()
    if sev == "CRITICAL":
        return "failed"
    if sev == "MEDIUM":
        return "warning"
    if sev == "LOW":
        return "teal"
    return "unavailable"


def get_snapshot_metadata():
    """Inspect SQLite snapshot file and internal timestamps without fabricating missing fields."""
    meta = {
        "db_path_rel": "data/financial_data.db",
        "db_exists": DATABASE_PATH.exists(),
        "db_size_kb": "Not available",
        "db_modified_utc": "Not available",
        "sec_period_range": "Not available",
        "sec_latest_filing_date": "Not available",
        "market_date_range": "Not available",
        "recon_date_range": "Not available",
        "dq_latest_detected_at": "Not available",
        "live_ingestion_status": "Saved SQLite Snapshot · Read-Only UI (No live ingestion)",
        "secondary_fundamentals_source": "Not available (Single-source SEC EDGAR Company Facts)",
    }
    if DATABASE_PATH.exists():
        stat = DATABASE_PATH.stat()
        meta["db_size_kb"] = f"{stat.st_size / 1024:.1f} KB ({stat.st_size:,} bytes)"
        meta["db_modified_utc"] = datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

    sec_dates = read_query(
        """
        SELECT
            MIN(fiscal_year) AS min_fy,
            MAX(fiscal_year) AS max_fy,
            MIN(period_end) AS min_period,
            MAX(period_end) AS max_period,
            MAX(filing_date) AS max_filing
        FROM financial_metric
        """
    )
    if not sec_dates.empty and pd.notna(sec_dates.loc[0, "min_fy"]):
        r = sec_dates.loc[0]
        meta["sec_period_range"] = (
            f"FY {int(r['min_fy'])}–FY {int(r['max_fy'])} "
            f"(period end {r['min_period']} to {r['max_period']})"
        )
        meta["sec_latest_filing_date"] = str(r["max_filing"] or "Not available")

    mkt_dates = read_query(
        "SELECT MIN(price_date) AS min_d, MAX(price_date) AS max_d FROM market_price"
    )
    if not mkt_dates.empty and pd.notna(mkt_dates.loc[0, "min_d"]):
        r = mkt_dates.loc[0]
        meta["market_date_range"] = f"{r['min_d']} to {r['max_d']}"

    rec_dates = read_query(
        "SELECT MIN(price_date) AS min_d, MAX(price_date) AS max_d FROM reconciliation_result"
    )
    if not rec_dates.empty and pd.notna(rec_dates.loc[0, "min_d"]):
        r = rec_dates.loc[0]
        meta["recon_date_range"] = f"{r['min_d']} to {r['max_d']}"

    dq_dates = read_query("SELECT MAX(detected_at) AS max_det FROM dq_issue")
    if not dq_dates.empty and pd.notna(dq_dates.loc[0, "max_det"]):
        meta["dq_latest_detected_at"] = str(dq_dates.loc[0, "max_det"])

    return meta


def render_app_header():
    """Render calm analyst workspace header with static snapshot status (no animated live badges)."""
    meta = get_snapshot_metadata()
    total_companies = get_single_value("SELECT COUNT(*) FROM company") or 0
    total_issues = get_single_value("SELECT COUNT(*) FROM dq_issue") or 0
    critical_issues = (
        get_single_value("SELECT COUNT(*) FROM dq_issue WHERE severity = 'CRITICAL'") or 0
    )
    if critical_issues > 0:
        status_tone = "failed"
        status_text = f"FAILED · {critical_issues} Critical Flag(s)"
    elif total_issues > 0:
        status_tone = "warning"
        status_text = f"WARNING · {total_issues} Open Investigation Flag(s)"
    else:
        status_tone = "healthy"
        status_text = "HEALTHY · 0 Open Flags"

    st.markdown(
        f"""
        <div class="ws-header">
            <div class="ws-brand-row">
                <div class="ws-brand-mark">DQ</div>
                <div>
                    <p class="ws-brand-title">Financial Data Quality &amp; Reconciliation Investigation Workspace</p>
                    <p class="ws-brand-subtitle">
                        SEC EDGAR 10-K Fundamentals · Yahoo Finance &amp; Nasdaq Close Reconciliation · Explainable Rule &amp; IQR Diagnostics
                    </p>
                </div>
            </div>
            <div class="ws-header-meta">
                <span class="ws-badge tone-info">MODE · Saved SQLite Snapshot (Read-Only)</span>
                <span class="ws-badge tone-teal">COVERAGE · {int(total_companies)} Companies ({safe_text(meta["sec_period_range"].split("(")[0].strip())})</span>
                <span class="ws-badge tone-{status_tone}">{safe_text(status_text)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_heading(kicker, title, description):
    st.markdown(
        f"""
        <div class="ws-page-heading">
            <div class="ws-eyebrow">{safe_text(kicker)}</div>
            <h1 class="ws-page-title">{safe_text(title)}</h1>
            <p class="ws-page-description">{safe_text(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_scope_banner(scope_label, message, warn=False):
    css_class = "ws-callout ws-callout-warn" if warn else "ws-scope-banner"
    st.markdown(
        f"""
        <div class="{css_class}">
            <strong>{safe_text(scope_label)}:</strong> {safe_text(message)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label, value, badge, tone, note, indicator_width=100):
    width = max(4.0, min(float(indicator_width), 100.0))
    st.markdown(
        f"""
        <div class="ws-metric-card">
            <div class="ws-metric-topline">
                <div class="ws-metric-label">{safe_text(label)}</div>
                <div class="ws-badge tone-{safe_text(tone)}">{safe_text(badge)}</div>
            </div>
            <div class="ws-metric-value">{safe_text(value)}</div>
            <div class="ws-metric-bar">
                <span class="fill-{safe_text(tone)}" style="width:{width:.1f}%"></span>
            </div>
            <div class="ws-metric-note">{safe_text(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_heading(title, note):
    st.markdown(
        f"""
        <div class="ws-section-heading">{safe_text(title)}</div>
        <div class="ws-section-note">{safe_text(note)}</div>
        """,
        unsafe_allow_html=True,
    )


def render_detail_card(label, value):
    st.markdown(
        f"""
        <div class="ws-detail-card">
            <div class="ws-detail-label">{safe_text(label)}</div>
            <div class="ws-detail-value">{safe_text(value)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_message_card(label, message):
    st.markdown(
        f"""
        <div class="ws-message-card">
            <strong>{safe_text(label)}</strong>
            {safe_text(message)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_score_chart(scores):
    """Build horizontal bar chart of company DQ scores with calm blue/teal/amber/red styling."""
    fig = go.Figure()
    if scores is None or scores.empty:
        fig.update_layout(
            height=260,
            margin=dict(l=16, r=16, t=24, b=16),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#FFFFFF",
            annotations=[
                dict(
                    text="No company score records available",
                    showarrow=False,
                    font=dict(size=13, color="#475569"),
                )
            ],
        )
        return fig

    chart_data = scores.sort_values("dq_score", ascending=True).copy()
    colors = [
        "#0D9488" if score >= 80 else "#D97706" if score >= 70 else "#DC2626"
        for score in chart_data["dq_score"]
    ]
    labels = [
        f"{row.dq_score:.0f}/100 ({int(row.total_issues)} flags)"
        for row in chart_data.itertuples(index=False)
    ]
    fig.add_trace(
        go.Bar(
            x=chart_data["dq_score"],
            y=[f"{r.ticker} · {r.company_name}" for r in chart_data.itertuples(index=False)],
            orientation="h",
            marker=dict(color=colors, line=dict(color="#CBD5E1", width=0.5)),
            text=labels,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "<b>%{y}</b><br>"
                "DQ Score: %{x}/100<br>"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=275,
        margin=dict(l=10, r=85, t=12, b=24),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="sans-serif", size=12, color="#0F172A"),
        xaxis=dict(
            range=[0, 112],
            title="Composite Quality Score (0–100 scale)",
            gridcolor="#E2E8F0",
            zeroline=False,
        ),
        yaxis=dict(title="", automargin=True),
        showlegend=False,
    )
    return fig


def build_severity_chart(severity_counts):
    """Build horizontal bar breakdown of open flags by severity with explicit text labels."""
    severity_order = ["CRITICAL", "MEDIUM", "LOW"]
    label_map = {
        "CRITICAL": "CRITICAL · Failed / Action",
        "MEDIUM": "MEDIUM · Warning / Review",
        "LOW": "LOW · Statistical / Info",
    }
    color_map = {
        "CRITICAL": "#DC2626",
        "MEDIUM": "#D97706",
        "LOW": "#0284C7",
    }
    count_lookup = {}
    if severity_counts is not None and not severity_counts.empty:
        val_col = (
            "issue_count"
            if "issue_count" in severity_counts.columns
            else "count"
            if "count" in severity_counts.columns
            else severity_counts.columns[-1]
        )
        count_lookup = dict(zip(severity_counts["severity"], severity_counts[val_col]))

    values = [int(count_lookup.get(sev, 0)) for sev in severity_order]
    display_labels = [label_map[sev] for sev in severity_order]
    colors = [color_map[sev] for sev in severity_order]
    max_val = max(values + [1])

    fig = go.Figure(
        go.Bar(
            x=values,
            y=display_labels,
            orientation="h",
            marker=dict(color=colors),
            text=[f"{v:,} flag(s)" for v in values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="<b>%{y}</b><br>Count: %{x}<extra></extra>",
        )
    )
    fig.update_layout(
        height=275,
        margin=dict(l=10, r=80, t=12, b=24),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        font=dict(family="sans-serif", size=12, color="#0F172A"),
        xaxis=dict(
            range=[0, max_val * 1.25 + 2],
            title="Stored Investigation Flags (dq_issue)",
            gridcolor="#E2E8F0",
            zeroline=False,
        ),
        yaxis=dict(title="", autorange="reversed", automargin=True),
        showlegend=False,
    )
    return fig


def get_company_scores():
    """
    Compute per-company issue counts, unchanged DQ score formula, and coverage statistics.
    Preserves required columns: ticker, company_name, low_issues, medium_issues,
    critical_issues, total_issues, dq_score.
    """
    scores = read_query(
        """
        SELECT
            c.ticker,
            c.company_name,
            c.cik,
            SUM(CASE WHEN d.severity = 'LOW' THEN 1 ELSE 0 END) AS low_issues,
            SUM(CASE WHEN d.severity = 'MEDIUM' THEN 1 ELSE 0 END) AS medium_issues,
            SUM(CASE WHEN d.severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_issues,
            SUM(CASE WHEN d.rule_name IN ('unusual_financial_growth_iqr', 'unusual_daily_return_iqr') THEN 1 ELSE 0 END) AS statistical_flags,
            SUM(CASE WHEN d.issue_id IS NOT NULL AND d.rule_name NOT IN ('unusual_financial_growth_iqr', 'unusual_daily_return_iqr') THEN 1 ELSE 0 END) AS deterministic_flags,
            COUNT(d.issue_id) AS total_issues
        FROM company AS c
        LEFT JOIN dq_issue AS d ON c.ticker = d.ticker
        GROUP BY c.ticker, c.company_name, c.cik
        ORDER BY c.ticker
        """
    )
    if scores.empty:
        return scores

    # Unchanged DQ score formula: 100 - (LOW * 2 + MEDIUM * 5 + CRITICAL * 10), clipped at 0
    scores["dq_score"] = (
        100
        - scores["low_issues"] * 2
        - scores["medium_issues"] * 5
        - scores["critical_issues"] * 10
    ).clip(lower=0)

    fin_cov = read_query(
        """
        SELECT
            ticker,
            COUNT(*) AS financial_rows,
            SUM(CASE WHEN is_derived = 0 THEN 1 ELSE 0 END) AS reported_financial_rows,
            SUM(CASE WHEN is_derived = 1 THEN 1 ELSE 0 END) AS derived_financial_rows,
            COUNT(DISTINCT metric_name) AS distinct_metrics,
            MIN(fiscal_year) || '–' || MAX(fiscal_year) AS fiscal_year_span
        FROM financial_metric
        GROUP BY ticker
        """
    )
    mkt_cov = read_query(
        """
        SELECT
            ticker,
            COUNT(*) AS market_rows,
            MIN(price_date) || ' to ' || MAX(price_date) AS market_date_span
        FROM market_price
        GROUP BY ticker
        """
    )
    rec_cov = read_query(
        """
        SELECT
            ticker,
            COUNT(*) AS reconciled_rows,
            SUM(CASE WHEN status = 'BREAK' THEN 1 ELSE 0 END) AS recon_breaks
        FROM reconciliation_result
        GROUP BY ticker
        """
    )

    scores = scores.merge(fin_cov, on="ticker", how="left")
    scores = scores.merge(mkt_cov, on="ticker", how="left")
    scores = scores.merge(rec_cov, on="ticker", how="left")

    for col in [
        "financial_rows",
        "reported_financial_rows",
        "derived_financial_rows",
        "distinct_metrics",
        "market_rows",
        "reconciled_rows",
        "recon_breaks",
    ]:
        scores[col] = scores[col].fillna(0).astype(int)

    scores["fiscal_year_span"] = scores["fiscal_year_span"].fillna("Not available")
    scores["market_date_span"] = scores["market_date_span"].fillna("Not available")

    def _company_status(row):
        if row["critical_issues"] > 0 or row["recon_breaks"] > 0 or row["deterministic_flags"] > 0:
            return "FAILED · Deterministic Rule Breach"
        if row["total_issues"] > 0:
            return "WARNING · Statistical Observations Only"
        return "HEALTHY · No Flags"

    scores["status_label"] = scores.apply(_company_status, axis=1)
    return scores


def get_related_record(record_type, related_record_id):
    """Fetch the linked source row from financial_metric, market_price, or reconciliation_result."""
    if not record_type or related_record_id is None or pd.isna(related_record_id):
        return None
    table_keys = {
        "financial_metric": ("financial_metric", "metric_id"),
        "market_price": ("market_price", "price_id"),
        "reconciliation_result": ("reconciliation_result", "reconciliation_id"),
    }
    if record_type not in table_keys:
        return None
    table_name, key_column = table_keys[record_type]
    try:
        rec_id = int(related_record_id)
    except (TypeError, ValueError):
        return None
    related = read_query(
        f"SELECT * FROM {table_name} WHERE {key_column} = ?",
        parameters=(rec_id,),
    )
    if related.empty:
        return None
    return related.iloc[0]


def describe_observed_and_expected(issue, related_record):
    """
    Return human-readable (observed, expected) strings for any quality issue.
    Preserves regex extraction and rule mappings for all 12 rules in src/quality.py.
    """
    description = str(issue["description"] or "")
    rule_name = str(issue["rule_name"] or "")
    record_type = str(issue["record_type"] or "")

    observed_match = re.search(r"changed ([+-]?[0-9.]+)%", description)
    threshold_match = re.search(r"threshold is ([0-9.]+)%", description)
    if observed_match and threshold_match:
        return (
            f"{observed_match.group(1)}% observed change",
            f"<= {threshold_match.group(1)}% IQR upper fence (Q3 + {IQR_MULTIPLIER} x IQR)",
        )

    if rule_name == "market_close_reconciliation" and related_record is not None:
        return (
            f"{float(related_record['difference_percent']):.6f}% close difference",
            f"<= {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% close tolerance",
        )

    expected_by_rule = {
        "missing_financial_metric": "All six required metrics should be present",
        "duplicate_financial_metric": "One record per company, metric, and period",
        "balance_sheet_equation": "Difference should be at or below 5% of Assets",
        "stale_financial_data": "Latest annual period should be no more than 550 days old",
        "nonpositive_price": "Every OHLC price should be greater than zero",
        "negative_volume": "Volume should be zero or greater",
        "high_below_low": "Daily high should be at or above daily low",
        "ohlc_consistency": "Open and close should fall between daily low and high",
        "stale_market_data": "Latest market date should be no more than 7 days old",
    }
    expected = expected_by_rule.get(
        rule_name,
        RULE_CATALOG.get(rule_name, {}).get(
            "expected_text", "Within configured quality rule threshold"
        ),
    )

    if related_record is not None:
        if record_type == "financial_metric":
            origin = (
                "Derived: Assets - Equity"
                if int(related_record.get("is_derived", 0) or 0) == 1
                else "Reported: SEC XBRL"
            )
            observed = (
                f"{related_record['metric_name']}: "
                f"{format_currency_compact(related_record['value'], related_record['unit'])} "
                f"({origin})"
            )
            return observed, expected
        if record_type == "market_price":
            observed = (
                f"Close ${float(related_record['close']):.2f} · "
                f"Volume {int(related_record['volume']):,}"
            )
            return observed, expected

    return description or "See the stored issue description", expected


def get_issue_source(issue, related_record):
    """Return data source identifier for a quality flag."""
    record_type = str(issue["record_type"] or "")
    if record_type == "financial_metric":
        return "SEC Company Facts"
    if record_type == "market_price" and related_record is not None:
        return str(related_record.get("source") or "Not available")
    if record_type == "reconciliation_result" and related_record is not None:
        return f"{related_record['source_a']} vs {related_record['source_b']}"
    return "Not available"


def get_alerts():
    """
    Fetch all quality investigation flags joined with company and linked record context.
    Preserves standard columns (issue_id, ticker, company_name, severity, dimension,
    rule_name, description, status, record_type, related_record_id, detected_at)
    and adds contextual columns for investigation filtering and display.
    """
    alerts = read_query(
        """
        SELECT
            d.issue_id,
            d.ticker,
            c.company_name,
            d.severity,
            d.dimension,
            d.rule_name,
            d.description,
            d.status,
            d.record_type,
            d.related_record_id,
            d.detected_at,
            fm.metric_name AS fin_metric_name,
            fm.fiscal_year AS fin_fiscal_year,
            fm.period_end AS fin_period_end,
            fm.value AS fin_value,
            fm.unit AS fin_unit,
            fm.is_derived AS fin_is_derived,
            fm.derivation AS fin_derivation,
            fm.form AS fin_form,
            fm.filing_date AS fin_filing_date,
            fm.source_tag AS fin_source_tag,
            mp.price_date AS mkt_price_date,
            mp.close AS mkt_close,
            mp.volume AS mkt_volume,
            mp.source AS mkt_source,
            rr.price_date AS rec_price_date,
            rr.source_a AS rec_source_a,
            rr.source_b AS rec_source_b,
            rr.difference_percent AS rec_diff_pct
        FROM dq_issue AS d
        JOIN company AS c ON d.ticker = c.ticker
        LEFT JOIN financial_metric AS fm
            ON d.record_type = 'financial_metric' AND d.related_record_id = fm.metric_id
        LEFT JOIN market_price AS mp
            ON d.record_type = 'market_price' AND d.related_record_id = mp.price_id
        LEFT JOIN reconciliation_result AS rr
            ON d.record_type = 'reconciliation_result' AND d.related_record_id = rr.reconciliation_id
        ORDER BY
            CASE d.severity WHEN 'CRITICAL' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END,
            d.ticker,
            d.issue_id
        """
    )
    if alerts.empty:
        return alerts

    def _build_metric_or_date(row):
        rtype = row["record_type"]
        if rtype == "financial_metric" and pd.notna(row["fin_metric_name"]):
            fy = f"FY {int(row['fin_fiscal_year'])}" if pd.notna(row["fin_fiscal_year"]) else ""
            pend = str(row["fin_period_end"] or "")
            return f"{row['fin_metric_name']} · {fy} ({pend})".strip(" ·")
        if rtype == "market_price" and pd.notna(row["mkt_price_date"]):
            return f"Daily Close · {row['mkt_price_date']} (${float(row['mkt_close']):.2f})"
        if rtype == "reconciliation_result" and pd.notna(row["rec_price_date"]):
            return f"Close Comparison · {row['rec_price_date']}"
        return "Dataset-level / Period Check"

    def _build_origin(row):
        rtype = row["record_type"]
        if rtype == "financial_metric":
            if pd.notna(row["fin_is_derived"]) and int(row["fin_is_derived"]) == 1:
                return f"DERIVED · {row['fin_derivation'] or 'Assets - Equity'}"
            if pd.notna(row["fin_is_derived"]):
                return "REPORTED · Direct SEC XBRL"
            return "SEC Company Facts"
        if rtype == "market_price":
            return f"REPORTED · {row['mkt_source'] or 'Yahoo Finance'}"
        if rtype == "reconciliation_result":
            return f"CROSS-SOURCE · {row['rec_source_a'] or 'Yahoo'} vs {row['rec_source_b'] or 'Nasdaq'}"
        return "Not available"

    def _build_observed_short(row):
        desc = str(row["description"] or "")
        m_chg = re.search(r"changed ([+-]?[0-9.]+)%", desc)
        m_thr = re.search(r"threshold is ([0-9.]+)%", desc)
        if m_chg and m_thr:
            return f"{m_chg.group(1)}% change (fence: {m_thr.group(1)}%)"
        if row["rule_name"] == "market_close_reconciliation" and pd.notna(row["rec_diff_pct"]):
            return f"{float(row['rec_diff_pct']):.6f}% diff (tol: {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%)"
        return desc

    alerts["flag_classification"] = alerts["rule_name"].map(classify_flag_type)
    alerts["severity_label"] = alerts["severity"].map(format_severity_label)
    alerts["metric_or_date_context"] = alerts.apply(_build_metric_or_date, axis=1)
    alerts["value_origin_label"] = alerts.apply(_build_origin, axis=1)
    alerts["observed_vs_threshold"] = alerts.apply(_build_observed_short, axis=1)
    return alerts


def show_dataset_health():
    """
    Tab 1: Dataset Overview — companies, periods, sources, available coverage,
    snapshot/freshness information, and reported vs. derived financial values.
    """
    render_page_heading(
        "1 · DATASET OVERVIEW & COVERAGE INVENTORY",
        "Dataset Overview, Snapshot Freshness & Reported vs. Derived Coverage",
        "Queried snapshot row counts, source coverage across SEC EDGAR (10-K/10-K/A) and Yahoo/Nasdaq market series, "
        "snapshot provenance, and explicit separation of directly reported versus derived financial values.",
    )

    # Query current database counts dynamically (never hardcode older 60/61 claims)
    company_count = int(get_single_value("SELECT COUNT(*) FROM company") or 0)
    financial_count = int(get_single_value("SELECT COUNT(*) FROM financial_metric") or 0)
    reported_fin_count = int(
        get_single_value("SELECT COUNT(*) FROM financial_metric WHERE is_derived = 0") or 0
    )
    derived_fin_count = int(
        get_single_value("SELECT COUNT(*) FROM financial_metric WHERE is_derived = 1") or 0
    )
    market_count = int(get_single_value("SELECT COUNT(*) FROM market_price") or 0)
    issue_count = int(get_single_value("SELECT COUNT(*) FROM dq_issue") or 0)
    critical_count = int(
        get_single_value("SELECT COUNT(*) FROM dq_issue WHERE severity = 'CRITICAL'") or 0
    )
    medium_count = int(
        get_single_value("SELECT COUNT(*) FROM dq_issue WHERE severity = 'MEDIUM'") or 0
    )
    low_count = int(
        get_single_value("SELECT COUNT(*) FROM dq_issue WHERE severity = 'LOW'") or 0
    )
    stat_flag_count = int(
        get_single_value(
            "SELECT COUNT(*) FROM dq_issue WHERE rule_name IN ('unusual_financial_growth_iqr', 'unusual_daily_return_iqr')"
        )
        or 0
    )
    det_flag_count = issue_count - stat_flag_count
    comparison_count = int(
        get_single_value("SELECT COUNT(*) FROM reconciliation_result") or 0
    )
    break_count = int(
        get_single_value(
            "SELECT COUNT(*) FROM reconciliation_result WHERE status = 'BREAK'"
        )
        or 0
    )
    max_variance = float(
        get_single_value(
            "SELECT COALESCE(MAX(difference_percent), 0.0) FROM reconciliation_result"
        )
        or 0.0
    )

    meta = get_snapshot_metadata()

    render_scope_banner(
        "METRIC SCOPE — FULL SAVED DATABASE SNAPSHOT",
        f"All overview KPI cards below reflect dynamic SQLite queries across the full saved dataset "
        f"({company_count} companies, {financial_count:,} financial metric rows, {market_count:,} daily market price rows, "
        f"{comparison_count:,} overlapping close comparisons, and {issue_count:,} stored quality flags). "
        f"Filtered counts are scoped separately inside interactive table explorers. "
        f"Newest stored flag timestamp: {meta['dq_latest_detected_at']}. Opening this dashboard does not rerun quality checks or refresh prices.",
    )

    row1 = st.columns(3)
    with row1[0]:
        render_metric_card(
            "Monitored Companies",
            f"{company_count}",
            "HEALTHY · Universe Loaded" if company_count > 0 else "UNAVAILABLE · Empty",
            "healthy" if company_count > 0 else "unavailable",
            f"Tracked US issuers in company table · {meta['sec_period_range']}",
            100 if company_count > 0 else 5,
        )
    with row1[1]:
        derived_pct = (derived_fin_count / financial_count * 100.0) if financial_count else 0.0
        render_metric_card(
            "Annual Financial Metric Rows",
            f"{financial_count:,}",
            f"REPORTED: {reported_fin_count:,} · DERIVED: {derived_fin_count:,}",
            "info",
            f"SEC EDGAR 10-K/10-K/A facts · {reported_fin_count:,} directly reported + "
            f"{derived_fin_count:,} derived ({derived_pct:.1f}% Liabilities = Assets - Equity)",
            100,
        )
    with row1[2]:
        render_metric_card(
            "Daily Market Price Rows",
            f"{market_count:,}",
            "REPORTED · Primary OHLCV",
            "teal",
            f"Yahoo Finance daily OHLCV series · Date span: {meta['market_date_range']}",
            100,
        )

    row2 = st.columns(3)
    with row2[0]:
        render_metric_card(
            "Overlapping Close Comparisons",
            f"{comparison_count:,}",
            f"MATCH: {comparison_count - break_count:,} · BREAK: {break_count:,}",
            "healthy" if break_count == 0 else "failed",
            f"Inner join on (ticker, price_date) between Yahoo & Nasdaq · "
            f"Tolerance: {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% · Max variance: {max_variance:.6f}%",
            100 if break_count == 0 else 40,
        )
    with row2[1]:
        flag_tone = "failed" if critical_count > 0 else "warning" if issue_count > 0 else "healthy"
        flag_badge = (
            f"FAILED · {critical_count} Critical"
            if critical_count > 0
            else f"WARNING · {issue_count} Review Flags"
            if issue_count > 0
            else "HEALTHY · 0 Flags"
        )
        render_metric_card(
            "Stored Investigation Flags (Snapshot)",
            f"{issue_count:,}",
            flag_badge,
            flag_tone,
            f"Queried from dq_issue · CRITICAL: {critical_count} · MEDIUM: {medium_count} · LOW: {low_count} "
            f"({stat_flag_count} statistical IQR observations, {det_flag_count} deterministic rule breaches)",
            max(15, 100 - critical_count * 15 - medium_count * 4),
        )
    with row2[2]:
        render_metric_card(
            "Actual Source Reconciliation Breaks",
            f"{break_count:,}",
            "HEALTHY · 0 Actual Breaks" if break_count == 0 else f"FAILED · {break_count} Break(s)",
            "healthy" if break_count == 0 else "failed",
            f"Saved SQLite snapshot breaks > {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% "
            f"(Isolated 10% injected-break unit test is not stored in saved snapshot)",
            100 if break_count == 0 else 20,
        )

    # Snapshot & Freshness Inventory Panel
    render_section_heading(
        "Snapshot Provenance, Data Sources & Freshness Boundaries",
        "Explicit distinction between the saved SQLite snapshot and offline batch ingestion scripts. "
        "Fields not recorded in the database schema are shown as 'Not available'.",
    )
    snap_cols = st.columns(4)
    with snap_cols[0]:
        render_detail_card("Execution Mode", meta["live_ingestion_status"])
        render_detail_card("SQLite Snapshot File", f"{meta['db_path_rel']} ({meta['db_size_kb']})")
    with snap_cols[1]:
        render_detail_card("File Modified (UTC; not ingestion time)", meta["db_modified_utc"])
        render_detail_card("Newest Stored Flag Timestamp (UTC)", meta["dq_latest_detected_at"])
    with snap_cols[2]:
        render_detail_card("SEC Annual Period Coverage", meta["sec_period_range"])
        render_detail_card("Latest SEC Filing Date in DB", meta["sec_latest_filing_date"])
    with snap_cols[3]:
        render_detail_card("Market & Recon Date Coverage", meta["market_date_range"])
        render_detail_card("Secondary Fundamentals Feed", meta["secondary_fundamentals_source"])

    # Company Coverage & Quality Matrix
    scores = get_company_scores()
    severity_counts = read_query(
        "SELECT severity, COUNT(*) AS issue_count FROM dq_issue GROUP BY severity"
    )

    chart_cols = st.columns([1.15, 1.0])
    with chart_cols[0]:
        render_section_heading(
            "Company Composite Quality Scores (Full Dataset Scope)",
            "Formula: DQ Score = max(0, 100 - 2×LOW - 5×MEDIUM - 10×CRITICAL). "
            "Scores reflect observation density and should be interpreted alongside flag type.",
        )
        st.plotly_chart(build_score_chart(scores), use_container_width=True)
    with chart_cols[1]:
        render_section_heading(
            "Stored Investigation Flags by Severity (Full Dataset Scope)",
            f"Stored count in dq_issue: {issue_count:,} flags ({stat_flag_count:,} statistical IQR outliers, "
            f"{det_flag_count:,} deterministic rule failures).",
        )
        st.plotly_chart(build_severity_chart(severity_counts), use_container_width=True)

    render_section_heading(
        "Company Coverage, Value Provenance & Investigation Summary Matrix",
        "Scope: All 5 monitored companies in the saved snapshot. Preserves reported versus derived financial row counts.",
    )
    matrix_display = scores[
        [
            "ticker",
            "company_name",
            "cik",
            "status_label",
            "dq_score",
            "fiscal_year_span",
            "distinct_metrics",
            "financial_rows",
            "reported_financial_rows",
            "derived_financial_rows",
            "market_rows",
            "reconciled_rows",
            "recon_breaks",
            "critical_issues",
            "medium_issues",
            "low_issues",
            "statistical_flags",
            "deterministic_flags",
            "total_issues",
        ]
    ].rename(
        columns={
            "ticker": "Ticker",
            "company_name": "Company",
            "cik": "SEC CIK",
            "status_label": "Investigation State",
            "dq_score": "DQ Score",
            "fiscal_year_span": "Fiscal Years",
            "distinct_metrics": "Metrics (/6)",
            "financial_rows": "Total Fin Rows",
            "reported_financial_rows": "Reported Rows",
            "derived_financial_rows": "Derived Rows",
            "market_rows": "Yahoo Market Rows",
            "reconciled_rows": "Overlapping Recon Pairs",
            "recon_breaks": "Recon Breaks",
            "critical_issues": "CRITICAL",
            "medium_issues": "MEDIUM",
            "low_issues": "LOW",
            "statistical_flags": "Statistical (IQR)",
            "deterministic_flags": "Deterministic",
            "total_issues": "Total Flags",
        }
    )
    st.dataframe(matrix_display, use_container_width=True, hide_index=True)

    # Interactive Fundamental Metrics Explorer (Reported vs Derived)
    st.markdown("---")
    render_section_heading(
        "Annual Financial Metrics Explorer — Reported vs. Derived Values",
        "Inspect canonical SEC annual figures and explicitly filter between directly reported XBRL values "
        "(is_derived = 0) and derived values (is_derived = 1, where Liabilities = Assets - Equity for AMZN, WMT, and KO).",
    )
    fin_df = read_query(
        """
        SELECT
            fm.metric_id,
            fm.ticker,
            c.company_name,
            fm.metric_name,
            fm.fiscal_year,
            fm.value,
            fm.unit,
            fm.is_derived,
            fm.derivation,
            fm.period_start,
            fm.period_end,
            fm.filing_date,
            fm.form,
            fm.accession_number,
            fm.source_tag
        FROM financial_metric AS fm
        JOIN company AS c ON fm.ticker = c.ticker
        ORDER BY fm.ticker, fm.fiscal_year DESC, fm.metric_name
        """
    )
    if not fin_df.empty:
        fin_df["value_formatted"] = [
            format_currency_compact(v, u) for v, u in zip(fin_df["value"], fin_df["unit"])
        ]
        fin_df["value_origin"] = fin_df.apply(
            lambda r: (
                f"DERIVED · {r['derivation'] or 'Assets - Equity'}"
                if int(r["is_derived"] or 0) == 1
                else "REPORTED · Direct SEC XBRL"
            ),
            axis=1,
        )
        fin_df["period_start_display"] = fin_df["period_start"].apply(
            lambda x: str(x) if pd.notna(x) and str(x).strip() else "Not available (Instant/Balance Sheet)"
        )
        fin_df["derivation_display"] = fin_df["derivation"].apply(
            lambda x: str(x) if pd.notna(x) and str(x).strip() else "Not available (Directly reported)"
        )

        f_cols = st.columns(4)
        company_opts = ["All companies"] + sorted(fin_df["ticker"].unique().tolist())
        metric_opts = ["All metrics"] + sorted(fin_df["metric_name"].unique().tolist())
        year_opts = ["All fiscal years"] + [
            str(y) for y in sorted(fin_df["fiscal_year"].unique().tolist(), reverse=True)
        ]
        origin_opts = [
            "All value origins",
            "Directly Reported Only (is_derived = 0)",
            "Derived Only (is_derived = 1 · Assets - Equity)",
        ]

        sel_comp = f_cols[0].selectbox("Company", company_opts, key="ov_fin_company")
        sel_met = f_cols[1].selectbox("Financial Metric", metric_opts, key="ov_fin_metric")
        sel_yr = f_cols[2].selectbox("Fiscal Year", year_opts, key="ov_fin_year")
        sel_orig = f_cols[3].selectbox("Value Origin", origin_opts, key="ov_fin_origin")

        show_sec_meta = st.checkbox(
            "Show SEC filing metadata columns (accession number, form, source XBRL tag, period start, raw value)",
            value=False,
            key="ov_show_sec_meta",
        )

        filtered_fin = fin_df.copy()
        if sel_comp != "All companies":
            filtered_fin = filtered_fin[filtered_fin["ticker"] == sel_comp]
        if sel_met != "All metrics":
            filtered_fin = filtered_fin[filtered_fin["metric_name"] == sel_met]
        if sel_yr != "All fiscal years":
            filtered_fin = filtered_fin[filtered_fin["fiscal_year"] == int(sel_yr)]
        if sel_orig.startswith("Directly Reported"):
            filtered_fin = filtered_fin[filtered_fin["is_derived"] == 0]
        elif sel_orig.startswith("Derived Only"):
            filtered_fin = filtered_fin[filtered_fin["is_derived"] == 1]

        filt_rep = int((filtered_fin["is_derived"] == 0).sum())
        filt_der = int((filtered_fin["is_derived"] == 1).sum())

        render_scope_banner(
            "FILTERED TABLE SCOPE vs. OVERALL SNAPSHOT",
            f"Showing {len(filtered_fin):,} filtered financial metric rows ({filt_rep:,} Reported, {filt_der:,} Derived) "
            f"out of {len(fin_df):,} total financial_metric records in the saved SQLite database "
            f"({reported_fin_count:,} Reported, {derived_fin_count:,} Derived).",
        )

        if filtered_fin.empty:
            st.info("No financial metric records match the current filter selection. Reset one or more filters above.")
        else:
            base_cols = [
                "metric_id",
                "ticker",
                "company_name",
                "fiscal_year",
                "metric_name",
                "value_formatted",
                "value_origin",
                "period_end",
                "filing_date",
            ]
            meta_cols = [
                "period_start_display",
                "form",
                "accession_number",
                "source_tag",
                "derivation_display",
                "value",
                "unit",
            ]
            cols_to_show = base_cols + (meta_cols if show_sec_meta else [])
            rename_map = {
                "metric_id": "Metric ID",
                "ticker": "Ticker",
                "company_name": "Company",
                "fiscal_year": "Fiscal Year",
                "metric_name": "Metric",
                "value_formatted": "Formatted Value",
                "value_origin": "Value Origin Status",
                "period_end": "Period End",
                "filing_date": "Filing Date",
                "period_start_display": "Period Start",
                "form": "SEC Form",
                "accession_number": "Accession Number",
                "source_tag": "XBRL Concept / Tag",
                "derivation_display": "Derivation Formula",
                "value": "Raw Value",
                "unit": "Unit",
            }
            st.dataframe(
                filtered_fin[cols_to_show].rename(columns=rename_map),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                label=f"Download Filtered Financial Metrics CSV ({len(filtered_fin):,} rows)",
                data=filtered_fin[cols_to_show].rename(columns=rename_map).to_csv(index=False).encode("utf-8"),
                file_name="filtered_sec_financial_metrics.csv",
                mime="text/csv",
                key="dl_filtered_fin_csv",
            )


def show_alerts_explorer():
    """
    Tab 2: Quality Investigations — filterable flags with rule, company, metric/date,
    supporting context, explicit dataset vs. filtered scope, and epistemic framing.
    """
    render_page_heading(
        "2 · QUALITY INVESTIGATIONS & ANOMALY QUEUE",
        "Data Quality Investigation Queue & Exception Explorer",
        "Filter and triage rule checks and statistical IQR observations by company, severity, quality dimension, "
        "rule, classification, and keyword with full metric/date context.",
    )

    render_scope_banner(
        "EPISTEMIC INTEGRITY — INVESTIGATION FLAGS ARE NOT AUTOMATIC DATA ERRORS",
        "Quality flags identify observations requiring analyst verification. In particular, statistical IQR flags "
        "(unusual_financial_growth_iqr and unusual_daily_return_iqr) highlight extreme movements relative to historical "
        "quartiles (Q3 + 1.5 × IQR) that often reflect genuine corporate turnarounds (such as AMZN FY2022–FY2023 Net Income) "
        "or earnings-day market volatility rather than corrupted source data.",
        warn=True,
    )

    alerts = get_alerts()
    total_db_flags = len(alerts)
    overall_crit = int((alerts["severity"] == "CRITICAL").sum()) if not alerts.empty else 0
    overall_med = int((alerts["severity"] == "MEDIUM").sum()) if not alerts.empty else 0
    overall_low = int((alerts["severity"] == "LOW").sum()) if not alerts.empty else 0
    overall_stat = (
        int((alerts["flag_classification"] == "Statistical Anomaly (IQR)").sum())
        if not alerts.empty
        else 0
    )
    overall_det = total_db_flags - overall_stat

    company_labels = {
        f"{row.ticker} - {row.company_name}": row.ticker
        for row in alerts[["ticker", "company_name"]]
        .drop_duplicates()
        .sort_values("ticker")
        .itertuples(index=False)
    }
    # Ensure all monitored companies are selectable even if a company has 0 alerts
    all_companies_df = read_query("SELECT ticker, company_name FROM company ORDER BY ticker")
    for row in all_companies_df.itertuples(index=False):
        label = f"{row.ticker} - {row.company_name}"
        if label not in company_labels:
            company_labels[label] = row.ticker

    all_severities = ["All severities", "CRITICAL", "MEDIUM", "LOW"]
    present_dims = (
        sorted(alerts["dimension"].dropna().unique().tolist()) if not alerts.empty else []
    )
    all_dimensions = ["All dimensions"] + sorted(
        set(present_dims) | {"Completeness", "Consistency", "Timeliness", "Uniqueness", "Validity"}
    )
    present_rules = (
        sorted(alerts["rule_name"].dropna().unique().tolist()) if not alerts.empty else []
    )
    all_rules = ["All rules"] + present_rules
    all_classifications = [
        "All flag classifications",
        "Statistical Anomaly (IQR)",
        "Deterministic Rule",
    ]
    all_domains = [
        "All record domains",
        "financial_metric",
        "market_price",
        "reconciliation_result",
    ]

    f_row1 = st.columns(4)
    selected_company_label = f_row1[0].selectbox(
        "Company filter",
        ["All companies"] + sorted(company_labels.keys()),
        key="alerts_company",
    )
    selected_severity = f_row1[1].selectbox(
        "Severity filter",
        all_severities,
        key="alerts_severity",
    )
    selected_dimension = f_row1[2].selectbox(
        "Quality dimension filter",
        all_dimensions,
        key="alerts_dimension",
    )
    selected_rule = f_row1[3].selectbox(
        "Rule filter",
        all_rules,
        key="alerts_rule",
    )

    f_row2 = st.columns([1.0, 1.0, 1.5, 0.9])
    selected_classification = f_row2[0].selectbox(
        "Flag classification",
        all_classifications,
        key="alerts_classification",
    )
    selected_domain = f_row2[1].selectbox(
        "Record domain",
        all_domains,
        key="alerts_domain",
    )
    search_query = f_row2[2].text_input(
        "Keyword search (rule, metric/date, ticker, description)",
        value="",
        placeholder="e.g., AMZN, Net Income, 2023, daily_return...",
        key="alerts_search",
    )
    with f_row2[3]:
        st.markdown("<div style='height: 26px'></div>", unsafe_allow_html=True)
        show_ext_cols = st.checkbox(
            "Show source metadata",
            value=False,
            key="alerts_show_meta",
        )

    filtered_alerts = alerts.copy()
    if selected_company_label != "All companies":
        filtered_alerts = filtered_alerts[
            filtered_alerts["ticker"] == company_labels[selected_company_label]
        ]
    if selected_severity != "All severities":
        filtered_alerts = filtered_alerts[
            filtered_alerts["severity"] == selected_severity
        ]
    if selected_dimension != "All dimensions":
        filtered_alerts = filtered_alerts[
            filtered_alerts["dimension"] == selected_dimension
        ]
    if selected_rule != "All rules":
        filtered_alerts = filtered_alerts[filtered_alerts["rule_name"] == selected_rule]
    if selected_classification != "All flag classifications":
        filtered_alerts = filtered_alerts[
            filtered_alerts["flag_classification"] == selected_classification
        ]
    if selected_domain != "All record domains":
        filtered_alerts = filtered_alerts[
            filtered_alerts["record_type"] == selected_domain
        ]
    if search_query and search_query.strip():
        q = search_query.strip().lower()
        mask = (
            filtered_alerts["ticker"].astype(str).str.lower().str.contains(q, na=False, regex=False)
            | filtered_alerts["company_name"].astype(str).str.lower().str.contains(q, na=False, regex=False)
            | filtered_alerts["rule_name"].astype(str).str.lower().str.contains(q, na=False, regex=False)
            | filtered_alerts["metric_or_date_context"].astype(str).str.lower().str.contains(q, na=False, regex=False)
            | filtered_alerts["description"].astype(str).str.lower().str.contains(q, na=False, regex=False)
        )
        filtered_alerts = filtered_alerts[mask]

    filt_count = len(filtered_alerts)
    filt_crit = int((filtered_alerts["severity"] == "CRITICAL").sum()) if not filtered_alerts.empty else 0
    filt_med = int((filtered_alerts["severity"] == "MEDIUM").sum()) if not filtered_alerts.empty else 0
    filt_low = int((filtered_alerts["severity"] == "LOW").sum()) if not filtered_alerts.empty else 0
    filt_tickers = int(filtered_alerts["ticker"].nunique()) if not filtered_alerts.empty else 0

    render_scope_banner(
        "EXPLICIT SCOPE COMPARISON — FILTERED SELECTION vs. FULL DATASET",
        f"Filtered Table Scope: {filt_count:,} matching flag(s) across {filt_tickers} company(ies) "
        f"(CRITICAL: {filt_crit}, MEDIUM: {filt_med}, LOW: {filt_low})  |  "
        f"Overall Dataset Baseline: {total_db_flags:,} total flag(s) in dq_issue "
        f"(CRITICAL: {overall_crit}, MEDIUM: {overall_med}, LOW: {overall_low} · "
        f"{overall_stat} Statistical IQR, {overall_det} Deterministic).",
    )

    summary_cards = st.columns(4)
    with summary_cards[0]:
        pct_of_total = (filt_count / total_db_flags * 100.0) if total_db_flags else 0.0
        render_metric_card(
            "Filtered Flags (Current View)",
            f"{filt_count:,} / {total_db_flags:,}",
            f"SCOPE · {pct_of_total:.1f}% of Dataset",
            "info",
            f"Showing {filt_count:,} filtered rows vs. {total_db_flags:,} total stored flags in dq_issue",
            max(5.0, pct_of_total),
        )
    with summary_cards[1]:
        render_metric_card(
            "Critical Severity (Filtered / Total)",
            f"{filt_crit} / {overall_crit}",
            "HEALTHY · 0 Critical" if filt_crit == 0 else f"FAILED · {filt_crit} Critical",
            "healthy" if filt_crit == 0 else "failed",
            "Deterministic completeness, validity, or balance-sheet breaches",
            100 if filt_crit == 0 else 30,
        )
    with summary_cards[2]:
        render_metric_card(
            "Medium Severity (Filtered / Total)",
            f"{filt_med} / {overall_med}",
            f"WARNING · {filt_med} Review" if filt_med > 0 else "HEALTHY · 0 Medium",
            "warning" if filt_med > 0 else "healthy",
            "Financial growth IQR flags, duplicate checks, or close reconciliation breaks",
            100 if filt_med == 0 else 65,
        )
    with summary_cards[3]:
        render_metric_card(
            "Low Severity (Filtered / Total)",
            f"{filt_low} / {overall_low}",
            f"OBSERVATION · {filt_low} Low" if filt_low > 0 else "HEALTHY · 0 Low",
            "teal" if filt_low > 0 else "healthy",
            "Daily market return IQR outliers and annual filing age checks",
            100,
        )

    if filtered_alerts.empty:
        st.info(
            "No investigation flags match the active filter combination. "
            "Adjust the company, severity, dimension, rule, or keyword filters above to broaden the scope."
        )
        return

    render_section_heading(
        f"Filtered Investigation Queue ({filt_count:,} of {total_db_flags:,} Dataset Flags)",
        "Includes linked metric/date context, value origin (Reported vs. Derived), and observed vs. threshold summary.",
    )

    base_table_cols = [
        "issue_id",
        "ticker",
        "company_name",
        "severity_label",
        "flag_classification",
        "dimension",
        "rule_name",
        "metric_or_date_context",
        "value_origin_label",
        "observed_vs_threshold",
        "description",
    ]
    ext_table_cols = [
        "record_type",
        "related_record_id",
        "status",
        "detected_at",
    ]
    display_cols = base_table_cols + (ext_table_cols if show_ext_cols else [])
    col_rename = {
        "issue_id": "Issue ID",
        "ticker": "Ticker",
        "company_name": "Company",
        "severity_label": "Severity & State",
        "flag_classification": "Flag Type",
        "dimension": "Dimension",
        "rule_name": "Rule Code",
        "metric_or_date_context": "Metric / Date Context",
        "value_origin_label": "Value Origin",
        "observed_vs_threshold": "Observed vs. Threshold",
        "description": "Full Observation Description",
        "record_type": "Source Table",
        "related_record_id": "Record ID",
        "status": "Queue Status",
        "detected_at": "Detected At (UTC)",
    }

    st.dataframe(
        filtered_alerts[display_cols].rename(columns=col_rename),
        use_container_width=True,
        hide_index=True,
    )

    dl_col, _ = st.columns([1, 2])
    with dl_col:
        st.download_button(
            label=f"Download Filtered Investigation Flags CSV ({filt_count:,} rows)",
            data=filtered_alerts[display_cols].rename(columns=col_rename).to_csv(index=False).encode("utf-8"),
            file_name="filtered_quality_investigations.csv",
            mime="text/csv",
            key="dl_filtered_alerts_csv",
        )

    # Quick Inline Inspector within Quality Investigations
    st.markdown("---")
    render_section_heading(
        "Quick Observation Summary Card",
        "Select any flag from the filtered queue above to preview its rule threshold and linked source record, "
        "or switch to '4 · Record Detail' for multi-year and time-series lineage.",
    )
    issue_lookup = {
        int(row.issue_id): (
            f"Issue #{int(row.issue_id)} · {row.ticker} · {row.severity} · "
            f"{row.rule_name} · {row.metric_or_date_context}"
        )
        for row in filtered_alerts.itertuples(index=False)
    }
    selected_issue_id = st.selectbox(
        "Select filtered flag to preview",
        options=list(issue_lookup.keys()),
        format_func=lambda idx: issue_lookup.get(idx, str(idx)),
        key="alerts_issue_id",
    )
    issue = filtered_alerts[filtered_alerts["issue_id"] == selected_issue_id].iloc[0]
    related_record = get_related_record(issue["record_type"], issue["related_record_id"])
    observed_txt, expected_txt = describe_observed_and_expected(issue, related_record)
    source_txt = get_issue_source(issue, related_record)

    d_cols = st.columns(4)
    with d_cols[0]:
        render_detail_card("Company & Issue ID", f"#{int(issue['issue_id'])} · {issue['ticker']} ({issue['company_name']})")
    with d_cols[1]:
        render_detail_card("Rule & Classification", f"{issue['rule_name']} ({issue['flag_classification']})")
    with d_cols[2]:
        render_detail_card("Dimension & Severity State", f"{issue['dimension']} · {issue['severity_label']}")
    with d_cols[3]:
        render_detail_card("Metric / Date & Origin", f"{issue['metric_or_date_context']} · {issue['value_origin_label']}")

    v_cols = st.columns(3)
    with v_cols[0]:
        render_detail_card("Observed Value / Movement", observed_txt)
    with v_cols[1]:
        render_detail_card("Expected Condition / Threshold", expected_txt)
    with v_cols[2]:
        render_detail_card("Primary Source Lineage", source_txt)

    render_message_card("Stored Observation Description", issue["description"])


def show_reconciliation_workspace():
    """
    Tab 3: Cross-Source Reconciliation — matched, mismatched, and unmatched records wherever
    available, coverage boundaries, epistemic caveats, and strict separation between the
    controlled injected-break test and actual saved snapshot discrepancies.
    """
    render_page_heading(
        "3 · CROSS-SOURCE RECONCILIATION WORKSPACE",
        "Market Close Reconciliation, Coverage Overlap & Controlled Test Verification",
        "Cross-source comparison of daily closing prices between Yahoo Finance (Source A) and Nasdaq (Source B), "
        "explicit accounting of matched, mismatched, and unmatched records, and separation of the isolated unit test.",
    )

    render_scope_banner(
        "COVERAGE & EPISTEMIC BOUNDARIES — OVERLAPPING CLOSES ONLY",
        f"1. Overlapping Records Only: Reconciliation joins Yahoo Finance and Nasdaq on (ticker, price_date) via inner join; "
        f"it compares only dates present in both feeds. "
        f"2. Match ≠ Independent Proof of Correctness: Agreement within the {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% tolerance "
        f"confirms cross-vendor consistency after decimal-precision rounding, not independent economic truth. "
        f"3. Fundamentals Reconciliation: Not available (SEC EDGAR is the sole fundamentals source).",
    )

    total_mkt_rows = int(get_single_value("SELECT COUNT(*) FROM market_price") or 0)
    total_recon_rows = int(get_single_value("SELECT COUNT(*) FROM reconciliation_result") or 0)
    matched_rows = int(
        get_single_value("SELECT COUNT(*) FROM reconciliation_result WHERE status = 'MATCH'") or 0
    )
    break_rows = int(
        get_single_value("SELECT COUNT(*) FROM reconciliation_result WHERE status = 'BREAK'") or 0
    )
    nonzero_var_rows = int(
        get_single_value(
            "SELECT COUNT(*) FROM reconciliation_result WHERE difference_percent > 0"
        )
        or 0
    )
    max_var_pct = float(
        get_single_value(
            "SELECT COALESCE(MAX(difference_percent), 0.0) FROM reconciliation_result"
        )
        or 0.0
    )

    # Query unmatched rows between market_price (Yahoo primary) and reconciliation_result
    unmatched_primary_df = read_query(
        """
        SELECT
            mp.price_id,
            mp.ticker,
            mp.price_date,
            mp.close AS yahoo_close,
            mp.volume,
            mp.source
        FROM market_price AS mp
        LEFT JOIN reconciliation_result AS rr
            ON mp.ticker = rr.ticker AND mp.price_date = rr.price_date
        WHERE rr.reconciliation_id IS NULL
        ORDER BY mp.ticker, mp.price_date
        """
    )
    unmatched_recon_df = read_query(
        """
        SELECT
            rr.reconciliation_id,
            rr.ticker,
            rr.price_date,
            rr.source_a,
            rr.close_source_a,
            rr.source_b,
            rr.close_source_b,
            rr.status
        FROM reconciliation_result AS rr
        LEFT JOIN market_price AS mp
            ON rr.ticker = mp.ticker AND rr.price_date = mp.price_date
        WHERE mp.price_id IS NULL
        ORDER BY rr.ticker, rr.price_date
        """
    )
    unmatched_primary_count = len(unmatched_primary_df)
    unmatched_recon_count = len(unmatched_recon_df)
    overlap_ratio = (
        ((total_mkt_rows - unmatched_primary_count) / total_mkt_rows * 100.0)
        if total_mkt_rows
        else 0.0
    )

    r_cards = st.columns(4)
    with r_cards[0]:
        render_metric_card(
            "Matched Close Pairs (MATCH)",
            f"{matched_rows:,} / {total_recon_rows:,}",
            f"MATCH · <= {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% Diff",
            "healthy",
            f"{matched_rows:,} overlapping (ticker, price_date) pairs within {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% tolerance",
            (matched_rows / total_recon_rows * 100.0) if total_recon_rows else 100,
        )
    with r_cards[1]:
        render_metric_card(
            "Mismatched Close Pairs (BREAK)",
            f"{break_rows:,}",
            "HEALTHY · 0 Real Breaks" if break_rows == 0 else f"BREAK · {break_rows} Exceeds Tol",
            "healthy" if break_rows == 0 else "failed",
            f"Saved snapshot pairs exceeding {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% "
            f"(Max observed variance: {max_var_pct:.6f}%)",
            100 if break_rows == 0 else 25,
        )
    with r_cards[2]:
        render_metric_card(
            "Unmatched Primary Market Rows",
            f"{unmatched_primary_count:,}",
            f"OVERLAP · {overlap_ratio:.1f}% of Yahoo Rows" if unmatched_primary_count == 0 else f"WARNING · {unmatched_primary_count} Unmatched",
            "teal" if unmatched_primary_count == 0 else "warning",
            f"Yahoo market_price rows without a paired Nasdaq comparison in reconciliation_result "
            f"({total_mkt_rows:,} primary rows vs. {total_recon_rows:,} compared pairs)",
            overlap_ratio,
        )
    with r_cards[3]:
        render_metric_card(
            "Standalone Nasdaq Unmatched Feed",
            "Not available",
            "UNAVAILABLE · Not Stored in SQLite",
            "unavailable",
            "Raw Nasdaq-only dates outside the inner join are not persisted as a separate SQLite table; "
            "only overlapping pairs are stored in reconciliation_result",
            100,
        )

    # Per-company reconciliation scorecard
    render_section_heading(
        "Per-Company Reconciliation & Coverage Overlap Scorecard (Full Snapshot Scope)",
        f"Compares primary Yahoo Finance daily rows against overlapping Yahoo vs. Nasdaq reconciliation pairs "
        f"(tolerance = {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%).",
    )
    company_recon = read_query(
        """
        SELECT
            c.ticker,
            c.company_name,
            COALESCE(m.mkt_rows, 0) AS primary_market_rows,
            COALESCE(r.comparisons, 0) AS overlapping_comparisons,
            COALESCE(m.mkt_rows, 0) - COALESCE(r.comparisons, 0) AS unmatched_primary_rows,
            COALESCE(r.matched, 0) AS matched_rows,
            COALESCE(r.breaks, 0) AS break_rows,
            COALESCE(r.nonzero_rows, 0) AS nonzero_precision_rows,
            COALESCE(r.min_diff_pct, 0.0) AS min_variance_pct,
            COALESCE(r.avg_diff_pct, 0.0) AS avg_variance_pct,
            COALESCE(r.max_diff_pct, 0.0) AS largest_variance_percent,
            COALESCE(r.min_date, 'Not available') || ' to ' || COALESCE(r.max_date, 'Not available') AS compared_date_span
        FROM company AS c
        LEFT JOIN (
            SELECT ticker, COUNT(*) AS mkt_rows
            FROM market_price
            GROUP BY ticker
        ) AS m ON c.ticker = m.ticker
        LEFT JOIN (
            SELECT
                ticker,
                COUNT(*) AS comparisons,
                SUM(CASE WHEN status = 'MATCH' THEN 1 ELSE 0 END) AS matched,
                SUM(CASE WHEN status = 'BREAK' THEN 1 ELSE 0 END) AS breaks,
                SUM(CASE WHEN difference_percent > 0 THEN 1 ELSE 0 END) AS nonzero_rows,
                MIN(difference_percent) AS min_diff_pct,
                AVG(difference_percent) AS avg_diff_pct,
                MAX(difference_percent) AS max_diff_pct,
                MIN(price_date) AS min_date,
                MAX(price_date) AS max_date
            FROM reconciliation_result
            GROUP BY ticker
        ) AS r ON c.ticker = r.ticker
        ORDER BY c.ticker
        """
    )
    if not company_recon.empty:
        company_recon["overlap_pct"] = [
            f"{(comp / mkt * 100.0):.1f}%" if mkt > 0 else "Not available"
            for comp, mkt in zip(
                company_recon["overlapping_comparisons"],
                company_recon["primary_market_rows"],
            )
        ]
        company_recon["status_label"] = [
            "FAILED · Break Detected"
            if brk > 0
            else "HEALTHY · All Overlapping Pairs Match"
            if comp > 0
            else "UNAVAILABLE · No Comparisons"
            for brk, comp in zip(
                company_recon["break_rows"],
                company_recon["overlapping_comparisons"],
            )
        ]
        company_recon["avg_variance_fmt"] = company_recon["avg_variance_pct"].map(
            lambda v: f"{float(v):.6f}%"
        )
        company_recon["largest_variance_fmt"] = company_recon[
            "largest_variance_percent"
        ].map(lambda v: f"{float(v):.6f}%")

        scorecard_display = company_recon[
            [
                "ticker",
                "company_name",
                "status_label",
                "compared_date_span",
                "primary_market_rows",
                "overlapping_comparisons",
                "unmatched_primary_rows",
                "overlap_pct",
                "matched_rows",
                "break_rows",
                "nonzero_precision_rows",
                "avg_variance_fmt",
                "largest_variance_fmt",
            ]
        ].rename(
            columns={
                "ticker": "Ticker",
                "company_name": "Company",
                "status_label": "Reconciliation State",
                "compared_date_span": "Compared Date Range",
                "primary_market_rows": "Yahoo Rows",
                "overlapping_comparisons": "Overlapping Pairs",
                "unmatched_primary_rows": "Unmatched Yahoo Rows",
                "overlap_pct": "Overlap %",
                "matched_rows": "MATCH Rows",
                "break_rows": "BREAK Rows",
                "nonzero_precision_rows": "Non-Zero Decimal Diffs",
                "avg_variance_fmt": "Mean Variance %",
                "largest_variance_fmt": "Max Variance %",
            }
        )
        st.dataframe(scorecard_display, use_container_width=True, hide_index=True)

    # Interactive Reconciliation Record Explorer
    st.markdown("---")
    render_section_heading(
        "Interactive Reconciliation Record Explorer (Matched, Mismatched & Unmatched Views)",
        "Filter overlapping Yahoo vs. Nasdaq daily close comparisons or inspect unmatched primary market records.",
    )
    recon_all = read_query(
        """
        SELECT
            rr.reconciliation_id,
            rr.ticker,
            c.company_name,
            rr.price_date,
            rr.source_a,
            rr.close_source_a,
            rr.source_b,
            rr.close_source_b,
            rr.absolute_difference,
            rr.difference_percent,
            rr.status
        FROM reconciliation_result AS rr
        JOIN company AS c ON rr.ticker = c.ticker
        ORDER BY rr.difference_percent DESC, rr.ticker, rr.price_date DESC
        """
    )

    rec_f_cols = st.columns(4)
    rec_comp_opts = ["All companies"] + sorted(
        company_recon["ticker"].unique().tolist() if not company_recon.empty else []
    )
    rec_view_opts = [
        "All Overlapping Comparisons (reconciliation_result)",
        "Matched Records Only (status = MATCH)",
        "Mismatched Records Only (status = BREAK)",
        "Non-Zero Decimal Variance Only (difference_percent > 0)",
        "Unmatched Primary Market Records (market_price without recon pair)",
    ]
    sel_rec_comp = rec_f_cols[0].selectbox(
        "Company", rec_comp_opts, key="rec_filter_company"
    )
    sel_rec_view = rec_f_cols[1].selectbox(
        "Reconciliation Record Category", rec_view_opts, key="rec_filter_view"
    )
    rec_date_search = rec_f_cols[2].text_input(
        "Date filter (YYYY-MM-DD or YYYY-MM)",
        value="",
        placeholder="e.g., 2026-03 or 2025-11...",
        key="rec_filter_date",
    )
    row_limit = rec_f_cols[3].selectbox(
        "Display limit",
        [100, 250, 500, 1500],
        index=1,
        key="rec_filter_limit",
    )

    if sel_rec_view.startswith("Unmatched Primary Market"):
        unmatched_view = unmatched_primary_df.copy()
        if sel_rec_comp != "All companies":
            unmatched_view = unmatched_view[unmatched_view["ticker"] == sel_rec_comp]
        if rec_date_search.strip():
            unmatched_view = unmatched_view[
                unmatched_view["price_date"].astype(str).str.contains(rec_date_search.strip(), na=False, regex=False)
            ]
        render_scope_banner(
            "FILTERED UNMATCHED PRIMARY RECORDS SCOPE",
            f"Showing {len(unmatched_view):,} unmatched primary market_price record(s) "
            f"(out of {unmatched_primary_count:,} total unmatched primary rows and {total_mkt_rows:,} total market_price rows). "
            f"Comparison rows without a matching primary market row: {unmatched_recon_count}. "
            f"Standalone unmatched Nasdaq-only feed rows are not available in SQLite.",
        )
        if unmatched_view.empty:
            st.info(
                "No unmatched primary market_price records match the current selection. "
                "Broaden the company or date filter to inspect other unmatched rows."
            )
        else:
            st.dataframe(unmatched_view.head(int(row_limit)), use_container_width=True, hide_index=True)
    else:
        filtered_recon = recon_all.copy()
        if sel_rec_comp != "All companies":
            filtered_recon = filtered_recon[filtered_recon["ticker"] == sel_rec_comp]
        if sel_rec_view.startswith("Matched Records Only"):
            filtered_recon = filtered_recon[filtered_recon["status"] == "MATCH"]
        elif sel_rec_view.startswith("Mismatched Records Only"):
            filtered_recon = filtered_recon[filtered_recon["status"] == "BREAK"]
        elif sel_rec_view.startswith("Non-Zero Decimal"):
            filtered_recon = filtered_recon[filtered_recon["difference_percent"] > 0]
        if rec_date_search.strip():
            filtered_recon = filtered_recon[
                filtered_recon["price_date"].astype(str).str.contains(rec_date_search.strip(), na=False, regex=False)
            ]

        render_scope_banner(
            "FILTERED RECONCILIATION TABLE SCOPE vs. OVERALL SNAPSHOT",
            f"Showing {min(len(filtered_recon), int(row_limit)):,} of {len(filtered_recon):,} matching comparison rows "
            f"(out of {total_recon_rows:,} total overlapping comparisons in reconciliation_result: "
            f"{matched_rows:,} MATCH, {break_rows:,} BREAK, {nonzero_var_rows:,} with non-zero decimal variance).",
        )

        if filtered_recon.empty:
            st.info(
                f"No reconciliation records match '{sel_rec_view}' for the active filter selection. "
                f"(The saved database snapshot currently contains {break_rows} BREAK rows.)"
            )
        else:
            disp_recon = filtered_recon.head(int(row_limit)).copy()
            disp_recon["status_badge"] = disp_recon["status"].map(
                lambda s: (
                    f"MATCH · Within {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%"
                    if s == "MATCH"
                    else f"BREAK · Exceeds {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%"
                )
            )
            disp_recon["close_a_fmt"] = disp_recon["close_source_a"].map(lambda v: f"${float(v):,.4f}")
            disp_recon["close_b_fmt"] = disp_recon["close_source_b"].map(lambda v: f"${float(v):,.4f}")
            disp_recon["abs_diff_fmt"] = disp_recon["absolute_difference"].map(lambda v: f"${float(v):,.6f}")
            disp_recon["diff_pct_fmt"] = disp_recon["difference_percent"].map(lambda v: f"{float(v):.6f}%")

            recon_cols = [
                "reconciliation_id",
                "ticker",
                "company_name",
                "price_date",
                "source_a",
                "close_a_fmt",
                "source_b",
                "close_b_fmt",
                "abs_diff_fmt",
                "diff_pct_fmt",
                "status_badge",
            ]
            recon_rename = {
                "reconciliation_id": "Recon ID",
                "ticker": "Ticker",
                "company_name": "Company",
                "price_date": "Trading Date",
                "source_a": "Source A",
                "close_a_fmt": "Source A Close",
                "source_b": "Source B",
                "close_b_fmt": "Source B Close",
                "abs_diff_fmt": "Abs Difference",
                "diff_pct_fmt": "Difference %",
                "status_badge": "Reconciliation Status",
            }
            st.dataframe(
                disp_recon[recon_cols].rename(columns=recon_rename),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                label=f"Download Filtered Reconciliation Records CSV ({len(filtered_recon):,} rows)",
                data=filtered_recon.to_csv(index=False).encode("utf-8"),
                file_name="filtered_market_reconciliation.csv",
                mime="text/csv",
                key="dl_filtered_recon_csv",
            )

    # Strict Separation: Saved Snapshot vs. Controlled Injected-Break Unit Test
    st.markdown("---")
    render_section_heading(
        "Controlled Injected-Break Verification vs. Saved Snapshot Discrepancies",
        "Explicitly separates the isolated unit test (tests/test_reconciliation.py) from the saved saved SQLite dataset.",
    )
    sep_cols = st.columns(2)
    with sep_cols[0]:
        render_detail_card(
            "1. Saved Snapshot Database (data/financial_data.db)",
            f"ACTUAL SOURCE DISCREPANCIES: {break_rows} BREAK rows across {total_recon_rows:,} overlapping Yahoo vs. Nasdaq comparisons "
            f"(largest observed variance = {max_var_pct:.6f}%, well within the {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% tolerance).",
        )
        render_message_card(
            "Snapshot Finding — Vendor Decimal-Precision Noise",
            f"In the real ingested market feeds, Yahoo Finance and Nasdaq occasionally differ at the 5th–6th decimal place "
            f"(up to {max_var_pct:.6f}%) due to floating-point representation. Applying the {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% "
            f"tolerance prevents false-positive alert fatigue while keeping all {total_recon_rows:,} comparisons auditable.",
        )
    with sep_cols[1]:
        render_detail_card(
            "2. Controlled Injected-Break Test (tests/test_reconciliation.py)",
            "ISOLATED IN-MEMORY UNIT TEST ONLY (Not written to data/financial_data.db): "
            "Injects Yahoo Close = $100.00 vs. altered Nasdaq Close = $110.00 (+10.000% variance) -> "
            "verifies status = 'BREAK' and 1 MEDIUM Consistency issue under rule 'market_close_reconciliation'.",
        )
        render_message_card(
            "Why the Controlled Test Is Separated",
            "Because real overlapping Yahoo and Nasdaq closes had 0 breaks above 0.50%, the failure path is verified via "
            "ReconciliationRuleTest.test_altered_source_b_close_creates_issue in memory without polluting the saved SQLite tables.",
        )

    with st.expander("Inspect Isolated In-Memory Controlled Break Test Fixture (Read-Only Simulation)", expanded=False):
        test_a = pd.DataFrame(
            [{"ticker": "AAPL", "price_date": "2026-08-26", "close": 100.00, "source": "Yahoo Finance chart"}]
        )
        test_b = pd.DataFrame(
            [{"ticker": "AAPL", "price_date": "2026-08-26", "close": 110.00, "source": "Nasdaq"}]
        )
        sim_comp = compare_market_closes(test_a, test_b)
        sim_comp["test_scope"] = "ISOLATED IN-MEMORY TEST (Not in SQLite)"
        st.caption(
            "Output below is computed in-memory by calling `compare_market_closes` on the exact `tests/test_reconciliation.py` fixture (`$100.00` vs. `$110.00`). "
            "It never touches `data/financial_data.db`."
        )
        st.dataframe(sim_comp, use_container_width=True, hide_index=True)


def show_incident_drilldown():
    """
    Tab 4: Record Detail & Lineage Inspector — inspect original values, source identifiers,
    derived-value labels, multi-period context, and collapsible SEC/source metadata.
    Supports both Flagged Observation Drill-Down and Direct Record Inspection across all tables.
    """
    render_page_heading(
        "4 · RECORD DETAIL & SOURCE LINEAGE INSPECTOR",
        "Record-Level Drill-Down, Value Origin & Filing Metadata",
        "Inspect flagged observations or browse any individual financial metric, daily market price, or reconciliation "
        "record with explicit Reported vs. Derived labels and expandable source metadata.",
    )

    companies = read_query("SELECT ticker, company_name, cik FROM company ORDER BY ticker")
    company_labels = {
        f"{row.ticker} - {row.company_name}": row.ticker
        for row in companies.itertuples(index=False)
    }
    cik_by_ticker = {row.ticker: row.cik for row in companies.itertuples(index=False)}

    mode = st.radio(
        "Inspection Mode",
        [
            "Mode A · Inspect by Quality Investigation Flag (dq_issue)",
            "Mode B · Direct Record Browser (All Stored Records: financial_metric, market_price, reconciliation_result)",
        ],
        horizontal=True,
        key="drilldown_mode",
    )

    if mode.startswith("Mode A"):
        selector_columns = st.columns([1.0, 2.2])
        selected_company = selector_columns[0].selectbox(
            "Company",
            list(company_labels.keys()),
            key="incident_company",
        )
        ticker = company_labels[selected_company]

        issues = read_query(
            """
            SELECT *
            FROM dq_issue
            WHERE ticker = ?
            ORDER BY
                CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END,
                issue_id
            """,
            parameters=(ticker,),
        )
        if issues.empty:
            st.info(f"This company ({selected_company}) has no stored DQ issues in dq_issue.")
            return

        issue_ids = issues["issue_id"].tolist()

        def _format_issue_option(issue_id):
            row = issues[issues["issue_id"] == issue_id].iloc[0]
            rel = get_related_record(row["record_type"], row["related_record_id"])
            ctx = ""
            if rel is not None:
                if row["record_type"] == "financial_metric":
                    ctx = f" · {rel['metric_name']} (FY {rel['fiscal_year']})"
                elif row["record_type"] == "market_price":
                    ctx = f" · {rel['price_date']} (Close ${float(rel['close']):.2f})"
                elif row["record_type"] == "reconciliation_result":
                    ctx = f" · {rel['price_date']} ({float(rel['difference_percent']):.4f}%)"
            return f"Issue #{int(issue_id)} · [{row['severity']}] {row['rule_name']} ({row['dimension']}){ctx}"

        selected_issue_id = selector_columns[1].selectbox(
            "DQ issue",
            issue_ids,
            format_func=_format_issue_option,
            key="incident_issue",
        )
        issue = issues[issues["issue_id"] == selected_issue_id].iloc[0]
        related_record = get_related_record(
            issue["record_type"], issue["related_record_id"]
        )
        observed, expected = describe_observed_and_expected(issue, related_record)
        source = get_issue_source(issue, related_record)
        flag_class = classify_flag_type(issue["rule_name"])

        render_scope_banner(
            f"DRILL-DOWN SCOPE — ISSUE #{int(issue['issue_id'])} ({ticker})",
            f"Classification: {flag_class}  |  Severity State: {format_severity_label(issue['severity'])}  |  "
            f"Note: Quality flags indicate observations requiring analyst verification, not automatically confirmed errors.",
        )

        summary_columns = st.columns(4)
        with summary_columns[0]:
            render_detail_card("Ticker / company", f"{selected_company} (CIK: {cik_by_ticker.get(ticker, 'Not available')})")
        with summary_columns[1]:
            render_detail_card("Rule & Classification", f"{issue['rule_name']} · {flag_class}")
        with summary_columns[2]:
            render_detail_card("Quality dimension", issue["dimension"])
        with summary_columns[3]:
            render_detail_card("Severity & State", format_severity_label(issue["severity"]))

        value_columns = st.columns(3)
        with value_columns[0]:
            render_detail_card("Observed value", observed)
        with value_columns[1]:
            render_detail_card("Expected value / threshold", expected)
        with value_columns[2]:
            render_detail_card("Source", source)

        render_message_card("Issue description", issue["description"])

        _render_linked_record_details(
            ticker=ticker,
            record_type=issue["record_type"],
            related_record=related_record,
            cik=cik_by_ticker.get(ticker, "Not available"),
            issue_detected_at=issue.get("detected_at"),
        )
    else:
        # Mode B: Direct Record Browser across all 3 data tables
        b_cols = st.columns(3)
        sel_comp_b = b_cols[0].selectbox(
            "Company",
            list(company_labels.keys()),
            key="direct_browser_company",
        )
        ticker_b = company_labels[sel_comp_b]
        sel_table_b = b_cols[1].selectbox(
            "Database Table",
            [
                "financial_metric (SEC Annual Fundamentals — Reported & Derived)",
                "market_price (Yahoo Finance Daily OHLCV)",
                "reconciliation_result (Yahoo vs. Nasdaq Daily Close Comparison)",
            ],
            key="direct_browser_table",
        )
        table_code = sel_table_b.split(" ")[0]

        if table_code == "financial_metric":
            rows_df = read_query(
                "SELECT * FROM financial_metric WHERE ticker = ? ORDER BY fiscal_year DESC, metric_name",
                parameters=(ticker_b,),
            )
            if rows_df.empty:
                st.info("No financial_metric records found for this company.")
                return
            options = rows_df["metric_id"].tolist()
            label_lookup = {
                int(r.metric_id): (
                    f"metric_id={int(r.metric_id)} · FY {int(r.fiscal_year)} · {r.metric_name} · "
                    f"{format_currency_compact(r.value, r.unit)} "
                    f"[{'DERIVED: ' + str(r.derivation or 'Assets - Equity') if int(r.is_derived or 0) == 1 else 'REPORTED: SEC XBRL'}]"
                )
                for r in rows_df.itertuples(index=False)
            }
            sel_id = b_cols[2].selectbox(
                "Select Financial Metric Record",
                options,
                format_func=lambda i: label_lookup.get(int(i), str(i)),
                key="direct_fin_id",
            )
            rec = rows_df[rows_df["metric_id"] == sel_id].iloc[0]
            _render_linked_record_details(
                ticker=ticker_b,
                record_type="financial_metric",
                related_record=rec,
                cik=cik_by_ticker.get(ticker_b, "Not available"),
                issue_detected_at=None,
            )
        elif table_code == "market_price":
            rows_df = read_query(
                "SELECT * FROM market_price WHERE ticker = ? ORDER BY price_date DESC",
                parameters=(ticker_b,),
            )
            if rows_df.empty:
                st.info("No market_price records found for this company.")
                return
            options = rows_df["price_id"].tolist()
            label_lookup = {
                int(r.price_id): f"price_id={int(r.price_id)} · {r.price_date} · Close ${float(r.close):.2f} · Vol {int(r.volume):,}"
                for r in rows_df.itertuples(index=False)
            }
            sel_id = b_cols[2].selectbox(
                "Select Market Price Record",
                options,
                format_func=lambda i: label_lookup.get(int(i), str(i)),
                key="direct_mkt_id",
            )
            rec = rows_df[rows_df["price_id"] == sel_id].iloc[0]
            _render_linked_record_details(
                ticker=ticker_b,
                record_type="market_price",
                related_record=rec,
                cik=cik_by_ticker.get(ticker_b, "Not available"),
                issue_detected_at=None,
            )
        else:
            rows_df = read_query(
                "SELECT * FROM reconciliation_result WHERE ticker = ? ORDER BY difference_percent DESC, price_date DESC",
                parameters=(ticker_b,),
            )
            if rows_df.empty:
                st.info("No reconciliation_result records found for this company.")
                return
            options = rows_df["reconciliation_id"].tolist()
            label_lookup = {
                int(r.reconciliation_id): (
                    f"reconciliation_id={int(r.reconciliation_id)} · {r.price_date} · "
                    f"{r.status} · Diff {float(r.difference_percent):.6f}%"
                )
                for r in rows_df.itertuples(index=False)
            }
            sel_id = b_cols[2].selectbox(
                "Select Reconciliation Record",
                options,
                format_func=lambda i: label_lookup.get(int(i), str(i)),
                key="direct_rec_id",
            )
            rec = rows_df[rows_df["reconciliation_id"] == sel_id].iloc[0]
            _render_linked_record_details(
                ticker=ticker_b,
                record_type="reconciliation_result",
                related_record=rec,
                cik=cik_by_ticker.get(ticker_b, "Not available"),
                issue_detected_at=None,
            )


def _render_linked_record_details(
    ticker, record_type, related_record, cik="Not available", issue_detected_at=None
):
    """Render original record values, derived-value status, historical context, and expandable metadata."""
    if related_record is None:
        render_section_heading(
            "Underlying Record Details",
            "No individual row ID is linked to this record (or the check applies at period/group level).",
        )
        render_detail_card("Linked Record Status", "Not available (Group / Period-level observation)")
        return

    if record_type == "financial_metric":
        is_der = int(related_record.get("is_derived", 0) or 0) == 1
        origin_badge = (
            f"DERIVED VALUE · Calculated as {related_record.get('derivation') or 'Assets - Equity'} (is_derived = 1)"
            if is_der
            else "REPORTED VALUE · Directly Reported in SEC XBRL (is_derived = 0)"
        )
        derivation_text = (
            str(related_record.get("derivation"))
            if is_der and pd.notna(related_record.get("derivation"))
            else "Not available (Directly reported in SEC filing)"
        )
        p_start = related_record.get("period_start")
        p_start_text = (
            str(p_start)
            if p_start is not None and pd.notna(p_start) and str(p_start).strip()
            else "Not available (Point-in-time balance sheet fact)"
        )

        render_section_heading(
            "Financial Record Values & Reported vs. Derived Provenance",
            "Preserves original reported values versus derived calculations, keeping technical SEC filing metadata available below.",
        )
        r_cols = st.columns(4)
        with r_cols[0]:
            render_detail_card(
                "Metric & Fiscal Year",
                f"{related_record['metric_name']} · FY {int(related_record['fiscal_year'])}",
            )
        with r_cols[1]:
            render_detail_card(
                "Stored Value (Compact & Raw)",
                f"{format_currency_compact(related_record['value'], related_record['unit'])} "
                f"({float(related_record['value']):,.0f} {related_record['unit']})",
            )
        with r_cols[2]:
            render_detail_card("Value Origin Label", origin_badge)
        with r_cols[3]:
            render_detail_card("Derivation Formula", derivation_text)

        # Essential summary metadata cards (preserving original fields)
        metadata_columns = st.columns(3)
        with metadata_columns[0]:
            render_detail_card("Source tag", related_record.get("source_tag"))
        with metadata_columns[1]:
            render_detail_card("Filing date", related_record.get("filing_date"))
        with metadata_columns[2]:
            render_detail_card("Period end date", related_record.get("period_end"))

        # Multi-year series for this company & metric so analyst can verify YoY trajectory
        metric_name = str(related_record["metric_name"])
        history_df = read_query(
            """
            SELECT
                metric_id,
                fiscal_year,
                period_start,
                period_end,
                value,
                unit,
                is_derived,
                derivation,
                form,
                filing_date,
                accession_number,
                source_tag
            FROM financial_metric
            WHERE ticker = ? AND metric_name = ?
            ORDER BY period_end ASC
            """,
            parameters=(ticker, metric_name),
        )
        if not history_df.empty:
            history_df["prev_val"] = history_df["value"].shift(1)
            history_df["yoy_change_pct"] = [
                f"{((v - pv) / abs(pv) * 100.0):+.2f}%"
                if pd.notna(pv) and float(pv) != 0
                else "Not available (Base period)"
                for v, pv in zip(history_df["value"], history_df["prev_val"])
            ]
            history_df["formatted_value"] = [
                format_currency_compact(v, u) for v, u in zip(history_df["value"], history_df["unit"])
            ]
            history_df["value_origin"] = [
                f"DERIVED ({d or 'Assets - Equity'})" if int(der or 0) == 1 else "REPORTED (SEC XBRL)"
                for der, d in zip(history_df["is_derived"], history_df["derivation"])
            ]
            render_section_heading(
                f"Multi-Period Trajectory for {ticker} · {metric_name} (All Stored Fiscal Years)",
                "Allows immediate verification of year-over-year changes and value provenance across all ingested annual filings.",
            )
            st.dataframe(
                history_df[
                    [
                        "metric_id",
                        "fiscal_year",
                        "period_end",
                        "formatted_value",
                        "yoy_change_pct",
                        "value_origin",
                        "form",
                        "filing_date",
                        "source_tag",
                    ]
                ].rename(
                    columns={
                        "metric_id": "Metric ID",
                        "fiscal_year": "Fiscal Year",
                        "period_end": "Period End",
                        "formatted_value": "Value",
                        "yoy_change_pct": "YoY Change %",
                        "value_origin": "Value Origin",
                        "form": "Form",
                        "filing_date": "Filing Date",
                        "source_tag": "XBRL Tag",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Full SEC Filing & Record Lineage Metadata", expanded=False):
            m_cols = st.columns(4)
            with m_cols[0]:
                render_detail_card("Record ID (metric_id)", str(related_record.get("metric_id")))
                render_detail_card("SEC CIK", str(cik))
            with m_cols[1]:
                render_detail_card("SEC Accession Number", related_record.get("accession_number"))
                render_detail_card("SEC Form Type", related_record.get("form"))
            with m_cols[2]:
                render_detail_card("Period Start Date", p_start_text)
                render_detail_card("Period End Date", related_record.get("period_end"))
            with m_cols[3]:
                render_detail_card("XBRL Source Tag", related_record.get("source_tag"))
                render_detail_card(
                    "Issue Detected Timestamp",
                    issue_detected_at if issue_detected_at else "Not available (Direct record view)",
                )

    elif record_type == "market_price":
        render_section_heading(
            "Market Price Record Details (Primary OHLCV Series)",
            "Daily market bar stored in market_price with surrounding trading-window context.",
        )
        m_cols = st.columns(4)
        with m_cols[0]:
            render_detail_card("Trading Date & Source", f"{related_record['price_date']} · {related_record['source']}")
        with m_cols[1]:
            render_detail_card(
                "Open / Close",
                f"Open: ${float(related_record['open']):.4f} · Close: ${float(related_record['close']):.4f}",
            )
        with m_cols[2]:
            render_detail_card(
                "Intraday Low / High",
                f"Low: ${float(related_record['low']):.4f} · High: ${float(related_record['high']):.4f}",
            )
        with m_cols[3]:
            render_detail_card(
                "Volume & Value Origin",
                f"{int(related_record['volume']):,} shares · REPORTED ({related_record['source']})",
            )

        window_df = read_query(
            """
            SELECT price_id, price_date, open, high, low, close, volume, source
            FROM market_price
            WHERE ticker = ?
              AND price_date BETWEEN date(?, '-10 days') AND date(?, '+10 days')
            ORDER BY price_date ASC
            """,
            parameters=(ticker, related_record["price_date"], related_record["price_date"]),
        )
        if not window_df.empty:
            window_df["prev_close"] = window_df["close"].shift(1)
            window_df["daily_return_pct"] = [
                f"{((c - pc) / abs(pc) * 100.0):+.2f}%"
                if pd.notna(pc) and float(pc) != 0
                else "Not available"
                for c, pc in zip(window_df["close"], window_df["prev_close"])
            ]
            render_section_heading(
                f"Surrounding Trading Window (±10 Calendar Days around {related_record['price_date']})",
                "Contextualizes daily close-to-close return movements across adjacent trading sessions.",
            )
            st.dataframe(
                window_df[
                    [
                        "price_id",
                        "price_date",
                        "open",
                        "high",
                        "low",
                        "close",
                        "daily_return_pct",
                        "volume",
                        "source",
                    ]
                ].rename(
                    columns={
                        "price_id": "Price ID",
                        "price_date": "Trading Date",
                        "open": "Open",
                        "high": "High",
                        "low": "Low",
                        "close": "Close",
                        "daily_return_pct": "Daily Return %",
                        "volume": "Volume",
                        "source": "Source",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Full Market Record Lineage Metadata", expanded=False):
            meta_c = st.columns(4)
            with meta_c[0]:
                render_detail_card("Record ID (price_id)", str(related_record.get("price_id")))
            with meta_c[1]:
                render_detail_card("Data Provider (source)", related_record.get("source"))
            with meta_c[2]:
                render_detail_card("SEC CIK", str(cik))
            with meta_c[3]:
                render_detail_card(
                    "Issue Detected Timestamp",
                    issue_detected_at if issue_detected_at else "Not available (Direct record view)",
                )

    elif record_type == "reconciliation_result":
        render_section_heading(
            "Cross-Source Close Reconciliation Record Details",
            f"Overlapping trading-date comparison against the {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% tolerance threshold.",
        )
        rc_cols = st.columns(4)
        with rc_cols[0]:
            render_detail_card("Trading Date & Status", f"{related_record['price_date']} · {related_record['status']}")
        with rc_cols[1]:
            render_detail_card(
                f"Source A ({related_record['source_a']}) Close",
                f"${float(related_record['close_source_a']):.6f}",
            )
        with rc_cols[2]:
            render_detail_card(
                f"Source B ({related_record['source_b']}) Close",
                f"${float(related_record['close_source_b']):.6f}",
            )
        with rc_cols[3]:
            render_detail_card(
                "Absolute & Percentage Variance",
                f"${float(related_record['absolute_difference']):.6f} ({float(related_record['difference_percent']):.6f}%)",
            )
        with st.expander("Full Reconciliation Record Lineage Metadata", expanded=False):
            mc = st.columns(3)
            with mc[0]:
                render_detail_card("Record ID (reconciliation_id)", str(related_record.get("reconciliation_id")))
            with mc[1]:
                render_detail_card("Tolerance Threshold", f"{MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%")
            with mc[2]:
                render_detail_card(
                    "Issue Detected Timestamp",
                    issue_detected_at if issue_detected_at else "Not available (Direct record view)",
                )


def show_methodology_and_limitations():
    """
    Tab 5: Methodology, Rules, Thresholds, Case Studies & Documented Limitations.
    """
    render_page_heading(
        "5 · METHODOLOGY, QUALITY RULES & LIMITATIONS",
        "Quality Rule Specifications, Mathematical Thresholds & Epistemic Limitations",
        "Complete specification of all 12 quality checks in src/quality.py, scoring and IQR formulas, "
        "documented engineering case studies, analyst personas, and system boundaries.",
    )

    # Query live counts per rule from dq_issue
    rule_counts_df = read_query(
        "SELECT rule_name, COUNT(*) AS active_flags FROM dq_issue GROUP BY rule_name"
    )
    count_by_rule = (
        dict(zip(rule_counts_df["rule_name"], rule_counts_df["active_flags"]))
        if not rule_counts_df.empty
        else {}
    )

    catalog_rows = []
    for rule_code, spec in RULE_CATALOG.items():
        cnt = int(count_by_rule.get(rule_code, 0))
        catalog_rows.append(
            {
                "Rule Code": rule_code,
                "Domain": spec["domain"],
                "Target Table": spec["table"],
                "Dimension": spec["dimension"],
                "Severity": spec["severity"],
                "Classification": spec["classification"],
                "Exact Threshold / Condition": spec["threshold"],
                "Current Stored Flags": cnt,
                "Active State": (
                    f"HEALTHY · 0 Flags"
                    if cnt == 0
                    else f"FAILED · {cnt} Critical"
                    if spec["severity"] == "CRITICAL"
                    else f"WARNING · {cnt} Observation(s)"
                ),
                "Implementation & Circularity Notes": spec["notes"],
            }
        )
    catalog_df = pd.DataFrame(catalog_rows)

    render_section_heading(
        "Complete Data-Quality Rule Catalog (12 Rules in src/quality.py)",
        "Stored flag counts are queried directly from dq_issue. Rules distinguish deterministic validation checks from statistical IQR outlier prompts.",
    )
    st.dataframe(catalog_df, use_container_width=True, hide_index=True)

    # Core Mathematical Formulas & Definitions
    st.markdown("---")
    render_section_heading(
        "Core Mathematical Definitions, Thresholds & Value Derivation",
        "All thresholds and formulas are preserved unchanged from src/quality.py, src/ingest_sec.py, and src/ingest_market.py.",
    )
    f_cols = st.columns(4)
    with f_cols[0]:
        render_detail_card(
            "Company DQ Score Formula",
            "DQ Score = max(0, 100 - 2×LOW - 5×MEDIUM - 10×CRITICAL)",
        )
        render_detail_card(
            "IQR Statistical Upper Fence",
            f"Upper Fence = Q3 + {IQR_MULTIPLIER} × IQR (where IQR = Q3 - Q1)",
        )
    with f_cols[1]:
        render_detail_card(
            "Market Close Reconciliation Tolerance",
            f"|Close_A - Close_B| / |Close_A| × 100 <= {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%",
        )
        render_detail_card(
            "Balance-Sheet Identity Tolerance",
            "|Assets - (Liabilities + Equity)| / |Assets| <= 5.0% (0.05)",
        )
    with f_cols[2]:
        render_detail_card(
            "Derived Liabilities Rule (is_derived = 1)",
            "Liabilities = Assets - Equity (applied for AMZN, WMT, KO where plain Liabilities XBRL tag is absent)",
        )
        render_detail_card(
            "Circularity Guardrail",
            "balance_sheet_equation check is skipped when Liabilities is derived from Assets - Equity",
        )
    with f_cols[3]:
        render_detail_card(
            "Stale Annual Filing Threshold",
            "Latest annual period_end age <= 550 calendar days at the quality run; not recalculated by the dashboard",
        )
        render_detail_card(
            "Stale Market Price Threshold",
            "Ticker latest price_date age <= 7 calendar days at the quality run; not recalculated by the dashboard",
        )

    # Documented Process Improvements / Case Studies
    st.markdown("---")
    render_section_heading(
        "Documented Investigation & Engineering Case Studies (docs/process_improvements.md)",
        "Real diagnostic examples illustrating decimal-precision noise filtering, isolated failure testing, and anomaly interpretation.",
    )
    cs_cols = st.columns(3)
    with cs_cols[0]:
        render_message_card(
            "1 · Market Reconciliation Decimal Noise",
            f"Issue: Yahoo Finance and Nasdaq closing prices exhibited tiny 5th–6th decimal differences (up to ~0.000006%). "
            f"Root cause: Providers store identical closes at slightly different floating-point precision. "
            f"Fix: Treat differences within {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% as MATCH and monitor only variances above tolerance.",
        )
    with cs_cols[1]:
        render_message_card(
            "2 · Controlled Reconciliation Failure Test",
            "Issue: Because the real overlapping market dataset had 0 breaks > 0.50%, the failure path required explicit verification. "
            "Fix: tests/test_reconciliation.py alters a sample Nasdaq close from $100.00 to $110.00 (10.0% variance) in memory, "
            "verifying status = BREAK and 1 MEDIUM market_close_reconciliation issue without writing to the saved SQLite database.",
        )
    with cs_cols[2]:
        render_message_card(
            "3 · AMZN Net-Income Statistical Anomaly",
            "Issue: unusual_financial_growth_iqr flagged AMZN Net Income changing 1,217.7% from 2022 to 2023 (above the 70.5% pooled IQR fence). "
            "Root cause: Stored Net Income moved from a $2.722B loss in FY2022 to a $30.425B profit in FY2023. "
            "Fix: Treat IQR flags as investigation prompts and verify against preserved SEC 10-K filing metadata before calling them errors.",
        )

    # Client Personas & Fit-for-Purpose
    render_section_heading(
        "Analyst Personas & Fit-for-Purpose Priorities (docs/client_personas.md)",
        "The same dataset can be fit for purpose for one analytical workflow while requiring caveats for another.",
    )
    p_cols = st.columns(3)
    with p_cols[0]:
        render_detail_card(
            "Fundamental Analyst",
            "Prioritizes Completeness, Consistency & Traceability across multi-year Revenue, Income, Assets, Liabilities, and Equity "
            "with preserved XBRL source tags, filing dates, and explicit Reported vs. Derived labels.",
        )
    with p_cols[1]:
        render_detail_card(
            "Quant Researcher",
            "Prioritizes Timeliness, Uniqueness, Completeness & Validity across daily OHLCV bars (High >= Low, Open/Close within range, "
            "positive prices, and cross-vendor close agreement) so backtests are not distorted.",
        )
    with p_cols[2]:
        render_detail_card(
            "Credit Analyst",
            "Prioritizes Balance-Sheet Completeness & Consistency (Assets = Liabilities + Equity within 5% tolerance and transparent "
            "labeling when Liabilities are derived as Assets - Equity) before computing leverage ratios.",
        )

    # Explicit System & Epistemic Limitations
    st.markdown("---")
    render_section_heading(
        "Explicit System, Coverage & Epistemic Limitations (README.md)",
        "Transparently documents all 14 project boundaries and capabilities that are currently not available.",
    )
    limitations_df = pd.DataFrame(
        [
            ("1. Universe Scope", "Covers 5 US-listed companies (AAPL, MSFT, AMZN, WMT, KO) and ~1 trading year of daily market prices.", "Bounded MVP Scope"),
            ("2. Batch Snapshot Workflow", "Batch-based SQLite snapshot (not real-time streaming). Fundamentals are annual (10-K/10-K/A) only; quarterly 10-Q facts are omitted.", "Quarterly 10-Q & Live Stream: Not available"),
            ("3. Canonical Metric Breadth", "SEC XBRL concept mapping covers 6 core financial metrics and a curated list of standard US-GAAP tags.", "Extended Statement Line Items: Not available"),
            ("4. Custom XBRL Extensions", "Company-specific XBRL extension tags outside the standard concept map may not be captured.", "Custom Extension Taxonomy: Not available"),
            ("5. Derived Liabilities", "AMZN, WMT, and KO do not report plain 'Liabilities' in selected facts; Liabilities are derived as Assets - Equity (is_derived = 1).", "Explicitly Labeled in UI & DB"),
            ("6. Heuristic Thresholds", "Quality tolerances (5% balance sheet, 0.50% close recon, 550d/7d staleness, 1.5x IQR) are fixed heuristic settings.", "Dynamic/Regime-Adjusted Thresholds: Not available"),
            ("7. Observation vs. Confirmed Error", "Quality and anomaly flags indicate observations requiring human review, not proof that underlying source data is wrong.", "Enforced Across All Views"),
            ("8. Explainable IQR vs. ML", "Uses transparent quartile fences (Q3 + 1.5 x IQR) rather than black-box machine learning anomaly models.", "ML Anomaly Model: Not available"),
            ("9. Single Fundamentals Source", "Reconciliation is limited to Yahoo vs. Nasdaq daily market closes; there is no second fundamentals provider.", "Fundamentals Reconciliation: Not available"),
            ("10. Public Endpoint Stability", "Yahoo Finance and Nasdaq historical endpoints are public web feeds whose schemas or access policies may change.", "Enterprise Feed SLA: Not available"),
            ("11. Match != Proof of Truth", "A cross-source match within 0.50% between two public market vendors does not independently prove economic correctness.", "Enforced in Reconciliation Framing"),
            ("12. Corporate Actions & Calendars", "Stock splits, dividends, adjusted-close conventions, multi-currency conversion, and exchange holiday calendars are not modeled in depth.", "Corporate Action Engine: Not available"),
            ("13. Issue Resolution Workflow", "SQLite stores open findings regenerated on quality runs; persistent analyst sign-off/comment state transitions are not yet implemented.", "Ticketing / Resolution Workflow: Not available"),
            ("14. Snapshot Count Variability", "Stored record and flag counts reflect the current SQLite snapshot and will change when ingestion scripts are re-executed on newer dates.", "Queried Dynamically from SQLite"),
        ],
        columns=["Boundary / Area", "Technical & Analytical Explanation", "Availability / Safeguard Status"],
    )
    st.dataframe(limitations_df, use_container_width=True, hide_index=True)


def main():
    st.markdown(APP_CSS, unsafe_allow_html=True)

    if not DATABASE_PATH.exists():
        st.error(f"Database not found: {DATABASE_PATH}")
        st.stop()

    render_app_header()

    page = st.radio(
        "Workspace Navigation",
        [
            "Dataset Overview",
            "Quality Investigations",
            "Reconciliation",
            "Record Detail",
            "Methodology",
        ],
        horizontal=True,
        label_visibility="collapsed",
        key="workspace_nav_radio",
    )

    if page == "Dataset Overview":
        show_dataset_health()
    elif page == "Quality Investigations":
        show_alerts_explorer()
    elif page == "Reconciliation":
        show_reconciliation_workspace()
    elif page == "Record Detail":
        show_incident_drilldown()
    else:
        show_methodology_and_limitations()


if __name__ == "__main__":
    main()
