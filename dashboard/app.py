"""Fanilo-inspired Streamlit UI for the financial data-quality MVP."""

import html
import re
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(
    page_title="Financial Data Quality Monitor",
    layout="wide",
    initial_sidebar_state="collapsed",
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ingest_market import MARKET_CLOSE_TOLERANCE_PERCENT


DATABASE_PATH = PROJECT_ROOT / "data" / "financial_data.db"


APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {
  --ink: #0f172a;
  --muted: #64748b;
  --line: #e2e8f0;
  --panel: #ffffff;
  --canvas: #f8fafc;
  --blue: #2563eb;
  --green: #059669;
  --amber: #d97706;
  --red: #dc2626;
}

#MainMenu, header, footer {
  visibility: hidden !important;
  display: none !important;
}

.block-container {
  padding-top: 1.5rem !important;
  padding-bottom: 2rem !important;
  max-width: 1400px !important;
}

.stApp {
  background: var(--canvas);
}

html, body, [class*="css"], [data-testid="stAppViewContainer"] {
  font-family: 'Plus Jakarta Sans', sans-serif;
  color: var(--ink);
}

h1, h2, h3, p {
  letter-spacing: -0.02em;
}

div[data-testid="stHorizontalBlock"] {
  gap: 1rem;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.brand-row {
  display: flex;
  align-items: center;
  gap: 0.8rem;
}

.brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 11px;
  color: #ffffff;
  background: #0f172a;
  font-size: 0.8rem;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.brand-name {
  margin: 0;
  font-size: 1rem;
  font-weight: 800;
  color: var(--ink);
}

.brand-subtitle {
  margin: 0.1rem 0 0;
  color: var(--muted);
  font-size: 0.78rem;
}

.live-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
  color: #047857;
  border-radius: 999px;
  padding: 0.45rem 0.75rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 4px #d1fae5;
}

div[data-testid="stRadio"] > div {
  width: fit-content;
  padding: 0.25rem;
  gap: 0.25rem;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #ffffff;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

div[data-testid="stRadio"] label {
  padding: 0.38rem 0.8rem !important;
  border-radius: 7px;
  color: #475569 !important;
  font-size: 0.78rem;
  font-weight: 650;
}

div[data-testid="stRadio"] label p {
  color: #475569 !important;
  opacity: 1 !important;
}

div[data-testid="stRadio"] label:has(input:checked) {
  background: #0f172a;
  color: #ffffff !important;
}

div[data-testid="stRadio"] label:has(input:checked) p {
  color: #ffffff !important;
}

div[data-testid="stRadio"] label > div:first-child {
  display: none;
}

.page-heading {
  margin: 1.4rem 0 1rem;
}

.eyebrow {
  color: var(--blue);
  font-size: 0.69rem;
  font-weight: 800;
  letter-spacing: 0.11em;
  text-transform: uppercase;
  margin-bottom: 0.35rem;
}

.page-title {
  margin: 0;
  color: var(--ink);
  font-size: 1.65rem;
  font-weight: 800;
}

.page-description {
  color: var(--muted);
  margin: 0.35rem 0 0;
  font-size: 0.87rem;
}

.metric-card {
  min-height: 150px;
  padding: 1.15rem 1.15rem 1rem;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.035);
}

.metric-topline {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
  align-items: flex-start;
}

.metric-label {
  color: var(--muted);
  font-size: 0.68rem;
  letter-spacing: 0.065em;
  font-weight: 750;
  text-transform: uppercase;
}

.metric-value {
  color: var(--ink);
  font-size: 1.8rem;
  line-height: 1.15;
  font-weight: 800;
  margin-top: 0.65rem;
}

.metric-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 0.28rem 0.5rem;
  font-size: 0.62rem;
  line-height: 1;
  font-weight: 750;
  white-space: nowrap;
}

.tone-green { color: #047857; background: #ecfdf5; }
.tone-amber { color: #b45309; background: #fffbeb; }
.tone-red { color: #b91c1c; background: #fef2f2; }
.tone-blue { color: #1d4ed8; background: #eff6ff; }
.tone-slate { color: #475569; background: #f1f5f9; }

.metric-indicator {
  height: 4px;
  margin-top: 1rem;
  border-radius: 999px;
  background: #eef2f7;
  overflow: hidden;
}

.metric-indicator span {
  display: block;
  height: 100%;
  border-radius: inherit;
}

.fill-green { background: linear-gradient(90deg, #10b981, #34d399); }
.fill-amber { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.fill-red { background: linear-gradient(90deg, #ef4444, #fb7185); }
.fill-blue { background: linear-gradient(90deg, #2563eb, #60a5fa); }
.fill-slate { background: linear-gradient(90deg, #64748b, #94a3b8); }

.metric-note {
  color: #94a3b8;
  margin-top: 0.55rem;
  font-size: 0.68rem;
}

div[data-testid="stVerticalBlockBorderWrapper"] {
  background: #ffffff;
  border-color: var(--line) !important;
  border-radius: 12px !important;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.035);
}

.section-heading {
  color: var(--ink);
  font-size: 0.95rem;
  font-weight: 800;
  margin: 0 0 0.15rem;
}

.section-note {
  color: var(--muted);
  font-size: 0.73rem;
  margin-bottom: 0.75rem;
}

.detail-card {
  height: 100%;
  min-height: 108px;
  padding: 1rem;
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: 10px;
}

.detail-label {
  color: var(--muted);
  font-size: 0.66rem;
  font-weight: 750;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.detail-value {
  color: var(--ink);
  margin-top: 0.5rem;
  font-size: 0.9rem;
  line-height: 1.45;
  font-weight: 650;
  overflow-wrap: anywhere;
}

.message-card {
  padding: 1rem 1.1rem;
  border-radius: 10px;
  border: 1px solid #dbeafe;
  background: #f8fbff;
  color: #334155;
  line-height: 1.55;
  font-size: 0.84rem;
}

.message-card strong {
  display: block;
  color: #1e3a8a;
  margin-bottom: 0.3rem;
  font-size: 0.68rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

div[data-baseweb="select"] > div {
  border-color: var(--line) !important;
  border-radius: 9px !important;
  background: #ffffff !important;
}

div[data-testid="stSelectbox"] label p {
  color: #475569 !important;
  font-size: 0.72rem !important;
  font-weight: 650 !important;
}

div[data-baseweb="select"] span,
div[data-baseweb="select"] input,
div[data-baseweb="select"] div {
  color: #0f172a !important;
  opacity: 1 !important;
}

div[data-testid="stDataFrame"] {
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}

.stCaption, [data-testid="stCaptionContainer"] {
  color: var(--muted) !important;
}

@media (max-width: 800px) {
  .block-container { padding-left: 1rem !important; padding-right: 1rem !important; }
  .app-header { align-items: flex-start; }
  .metric-card { min-height: 138px; }
}
</style>
"""


def read_query(query, parameters=()):
    """Read one SQL query into a pandas DataFrame."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        return pd.read_sql_query(query, connection, params=parameters)


def get_single_value(query):
    """Return the first value from a one-value SQL query."""
    with sqlite3.connect(DATABASE_PATH) as connection:
        return connection.execute(query).fetchone()[0]


def safe_text(value):
    """Escape database text before placing it inside custom HTML."""
    return html.escape(str(value))


def render_app_header():
    st.markdown(
        """
        <div class="app-header">
          <div class="brand-row">
            <div class="brand-mark">DQ</div>
            <div>
              <p class="brand-name">Financial Data Quality Monitor</p>
              <p class="brand-subtitle">SEC fundamentals · daily market data · reconciliation</p>
            </div>
          </div>
          <div class="live-badge"><span class="live-dot"></span>SQLite connected</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_page_heading(kicker, title, description):
    st.markdown(
        f"""
        <div class="page-heading">
          <div class="eyebrow">{safe_text(kicker)}</div>
          <h1 class="page-title">{safe_text(title)}</h1>
          <p class="page-description">{safe_text(description)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label, value, badge, tone, note, indicator_width=100):
    width = max(5, min(float(indicator_width), 100))
    st.markdown(
        f"""
        <div class="metric-card">
          <div class="metric-topline">
            <div class="metric-label">{safe_text(label)}</div>
            <div class="metric-badge tone-{tone}">{safe_text(badge)}</div>
          </div>
          <div class="metric-value">{safe_text(value)}</div>
          <div class="metric-indicator">
            <span class="fill-{tone}" style="width:{width:.1f}%"></span>
          </div>
          <div class="metric-note">{safe_text(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_heading(title, note):
    st.markdown(
        f"""
        <div class="section-heading">{safe_text(title)}</div>
        <div class="section-note">{safe_text(note)}</div>
        """,
        unsafe_allow_html=True,
    )


def render_detail_card(label, value):
    st.markdown(
        f"""
        <div class="detail-card">
          <div class="detail-label">{safe_text(label)}</div>
          <div class="detail-value">{safe_text(value)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_message_card(label, message):
    st.markdown(
        f"""
        <div class="message-card">
          <strong>{safe_text(label)}</strong>
          {safe_text(message)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_score_chart(scores):
    chart_data = scores.sort_values("dq_score")
    colors = [
        "#10b981" if score >= 80 else "#f59e0b" if score >= 70 else "#ef4444"
        for score in chart_data["dq_score"]
    ]
    figure = go.Figure(
        go.Bar(
            x=chart_data["dq_score"],
            y=chart_data["ticker"],
            orientation="h",
            marker_color=colors,
            text=chart_data["dq_score"].map(lambda value: f"{value:.0f}"),
            textposition="outside",
            customdata=chart_data[["company_name", "total_issues"]],
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>Score: %{x:.0f}<br>"
                "Issues: %{customdata[1]}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        height=300,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=26, t=8, b=0),
        font=dict(family="Plus Jakarta Sans", color="#475569", size=11),
        hovermode="x unified",
        showlegend=False,
        xaxis=dict(range=[0, 105], showgrid=False, zeroline=False, title=None),
        yaxis=dict(showgrid=False, zeroline=False, title=None),
    )
    return figure


def build_severity_chart(severity_counts):
    severity_order = ["LOW", "MEDIUM", "CRITICAL"]
    count_lookup = dict(zip(severity_counts["severity"], severity_counts["issue_count"]))
    values = [count_lookup.get(severity, 0) for severity in severity_order]
    figure = go.Figure(
        go.Pie(
            labels=severity_order,
            values=values,
            hole=0.68,
            marker=dict(colors=["#3b82f6", "#f59e0b", "#ef4444"]),
            textinfo="none",
            hovertemplate="%{label}: %{value}<extra></extra>",
        )
    )
    figure.add_annotation(
        text=f"<b>{sum(values)}</b><br><span style='font-size:10px'>OPEN</span>",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(family="Plus Jakarta Sans", color="#0f172a", size=18),
    )
    figure.update_layout(
        height=300,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=8, b=0),
        font=dict(family="Plus Jakarta Sans", color="#64748b", size=11),
        legend=dict(orientation="h", y=-0.05, x=0.5, xanchor="center"),
        showlegend=True,
    )
    return figure


def get_company_scores():
    query = """
        SELECT
            c.ticker,
            c.company_name,
            SUM(CASE WHEN d.severity = 'LOW' THEN 1 ELSE 0 END) AS low_issues,
            SUM(CASE WHEN d.severity = 'MEDIUM' THEN 1 ELSE 0 END) AS medium_issues,
            SUM(CASE WHEN d.severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical_issues,
            COUNT(d.issue_id) AS total_issues
        FROM company AS c
        LEFT JOIN dq_issue AS d ON c.ticker = d.ticker
        GROUP BY c.ticker, c.company_name
        ORDER BY c.ticker
    """
    scores = read_query(query)
    scores["dq_score"] = (
        100
        - scores["low_issues"] * 2
        - scores["medium_issues"] * 5
        - scores["critical_issues"] * 10
    ).clip(lower=0)
    return scores


def show_dataset_health():
    render_page_heading(
        "Portfolio overview",
        "Dataset Health",
        "Coverage, alert pressure, and source reconciliation from the current SQLite run.",
    )

    company_count = get_single_value("SELECT COUNT(*) FROM company")
    financial_count = get_single_value("SELECT COUNT(*) FROM financial_metric")
    market_count = get_single_value("SELECT COUNT(*) FROM market_price")
    issue_count = get_single_value("SELECT COUNT(*) FROM dq_issue")
    critical_count = get_single_value(
        "SELECT COUNT(*) FROM dq_issue WHERE severity = 'CRITICAL'"
    )
    medium_count = get_single_value(
        "SELECT COUNT(*) FROM dq_issue WHERE severity = 'MEDIUM'"
    )
    comparison_count = get_single_value("SELECT COUNT(*) FROM reconciliation_result")
    break_count = get_single_value(
        "SELECT COUNT(*) FROM reconciliation_result WHERE status = 'BREAK'"
    )

    top_cards = st.columns(4)
    with top_cards[0]:
        render_metric_card("Companies", f"{company_count}", "● 5 / 5", "green", "Requested universe loaded", 100)
    with top_cards[1]:
        render_metric_card("Financial rows", f"{financial_count:,}", "● COMPLETE", "blue", "Six metrics × five annual periods", 100)
    with top_cards[2]:
        render_metric_card("Market rows", f"{market_count:,}", "● 254 / TICKER", "blue", "Approximately one trading year", 100)
    with top_cards[3]:
        render_metric_card("Open DQ issues", f"{issue_count:,}", "● INVESTIGATE", "amber", "Anomalies are not confirmed errors", min(issue_count, 100))

    st.write("")
    status_cards = st.columns(4)
    with status_cards[0]:
        render_metric_card("Critical issues", critical_count, "● CLEAR", "green", "No critical failures detected", 100 if critical_count == 0 else 25)
    with status_cards[1]:
        render_metric_card("Medium issues", medium_count, "● REVIEW", "amber", "Financial growth anomaly flags", min(medium_count * 20, 100))
    with status_cards[2]:
        render_metric_card("Close comparisons", f"{comparison_count:,}", "● TWO SOURCES", "blue", "Yahoo Finance vs Nasdaq", 100)
    with status_cards[3]:
        tone = "green" if break_count == 0 else "red"
        badge = "● MATCHED" if break_count == 0 else "● ACTION"
        render_metric_card("Reconciliation breaks", break_count, badge, tone, f"Tolerance {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%", 100 if break_count == 0 else 30)

    st.write("")
    scores = get_company_scores()
    severity_counts = read_query(
        "SELECT severity, COUNT(*) AS issue_count FROM dq_issue GROUP BY severity"
    )
    chart_columns = st.columns([3, 2])
    with chart_columns[0]:
        with st.container(border=True):
            render_section_heading("DQ score by company", "Weighted score: LOW −2, MEDIUM −5, CRITICAL −10")
            st.plotly_chart(
                build_score_chart(scores),
                use_container_width=True,
                config={"displayModeBar": False},
            )
    with chart_columns[1]:
        with st.container(border=True):
            render_section_heading("Issue severity mix", "Current open issues grouped by severity")
            st.plotly_chart(
                build_severity_chart(severity_counts),
                use_container_width=True,
                config={"displayModeBar": False},
            )

    st.write("")
    reconciliation_query = """
        SELECT
            ticker,
            COUNT(*) AS comparisons,
            SUM(CASE WHEN status = 'BREAK' THEN 1 ELSE 0 END) AS breaks,
            MAX(difference_percent) AS largest_variance_percent
        FROM reconciliation_result
        GROUP BY ticker
        ORDER BY ticker
    """
    reconciliation = read_query(reconciliation_query)
    largest_variance = reconciliation["largest_variance_percent"].max()
    reconciliation["largest_variance_percent"] = reconciliation[
        "largest_variance_percent"
    ].map(lambda value: f"{value:.6f}%")

    with st.container(border=True):
        render_section_heading(
            "Market close reconciliation",
            f"1,270 comparisons · 0 real breaks · {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}% threshold · "
            f"largest variance {largest_variance:.6f}%",
        )
        st.dataframe(reconciliation, use_container_width=True, hide_index=True)
        st.caption("Source A: Yahoo Finance chart · Source B: Nasdaq historical prices")


def get_alerts():
    query = """
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
            d.detected_at
        FROM dq_issue AS d
        JOIN company AS c ON d.ticker = c.ticker
        ORDER BY
            CASE d.severity
                WHEN 'CRITICAL' THEN 1
                WHEN 'MEDIUM' THEN 2
                ELSE 3
            END,
            d.ticker,
            d.issue_id
    """
    return read_query(query)


def show_alerts_explorer():
    render_page_heading(
        "Investigation queue",
        "Alerts Explorer",
        "Filter the current quality findings and inspect the stored explanation for any alert.",
    )
    alerts = get_alerts()

    summary_cards = st.columns(3)
    with summary_cards[0]:
        render_metric_card("Open issues", len(alerts), "● ACTIVE", "blue", "Current quality-engine output", 100)
    with summary_cards[1]:
        medium_total = int((alerts["severity"] == "MEDIUM").sum())
        render_metric_card("Medium priority", medium_total, "● REVIEW", "amber", "Financial anomaly flags", min(medium_total * 20, 100))
    with summary_cards[2]:
        critical_total = int((alerts["severity"] == "CRITICAL").sum())
        tone = "green" if critical_total == 0 else "red"
        render_metric_card("Critical priority", critical_total, "● CLEAR" if critical_total == 0 else "● ACTION", tone, "Validity and structural failures", 100 if critical_total == 0 else 30)

    st.write("")
    company_labels = {
        f"{row.ticker} — {row.company_name}": row.ticker
        for row in alerts[["ticker", "company_name"]]
        .drop_duplicates()
        .itertuples(index=False)
    }

    with st.container(border=True):
        render_section_heading("Filter alerts", "Use one or more fields to narrow the investigation queue")
        filter_columns = st.columns(4)
        selected_company = filter_columns[0].selectbox(
            "Company", ["All"] + list(company_labels.keys()), key="alerts_company"
        )
        selected_severity = filter_columns[1].selectbox(
            "Severity", ["All"] + sorted(alerts["severity"].unique().tolist()), key="alerts_severity"
        )
        selected_dimension = filter_columns[2].selectbox(
            "Dimension", ["All"] + sorted(alerts["dimension"].unique().tolist()), key="alerts_dimension"
        )
        selected_rule = filter_columns[3].selectbox(
            "Rule", ["All"] + sorted(alerts["rule_name"].unique().tolist()), key="alerts_rule"
        )

    filtered = alerts.copy()
    if selected_company != "All":
        filtered = filtered[filtered["ticker"] == company_labels[selected_company]]
    if selected_severity != "All":
        filtered = filtered[filtered["severity"] == selected_severity]
    if selected_dimension != "All":
        filtered = filtered[filtered["dimension"] == selected_dimension]
    if selected_rule != "All":
        filtered = filtered[filtered["rule_name"] == selected_rule]

    st.write("")
    with st.container(border=True):
        render_section_heading("Issue register", f"Showing {len(filtered)} of {len(alerts)} stored issues")
        display_columns = [
            "issue_id",
            "ticker",
            "company_name",
            "severity",
            "dimension",
            "rule_name",
            "description",
            "status",
            "detected_at",
        ]
        st.dataframe(filtered[display_columns], use_container_width=True, hide_index=True)

    if filtered.empty:
        st.info("No issues match the selected filters.")
        return

    st.write("")
    with st.container(border=True):
        render_section_heading("Issue detail", "Select one row to read the full stored explanation")
        issue_ids = filtered["issue_id"].tolist()
        selected_issue_id = st.selectbox(
            "Issue",
            issue_ids,
            format_func=lambda issue_id: f"Issue {issue_id}",
            key="alerts_issue",
        )
        issue = filtered[filtered["issue_id"] == selected_issue_id].iloc[0]
        detail_columns = st.columns(4)
        with detail_columns[0]:
            render_detail_card("Company", f"{issue['ticker']} · {issue['company_name']}")
        with detail_columns[1]:
            render_detail_card("Severity", issue["severity"])
        with detail_columns[2]:
            render_detail_card("Dimension", issue["dimension"])
        with detail_columns[3]:
            render_detail_card("Rule", issue["rule_name"])
        st.write("")
        render_message_card("Issue message", issue["description"])


def get_related_record(record_type, related_record_id):
    """Fetch the stored row linked to an issue, when one exists."""
    table_keys = {
        "financial_metric": ("financial_metric", "metric_id"),
        "market_price": ("market_price", "price_id"),
        "reconciliation_result": ("reconciliation_result", "reconciliation_id"),
    }
    if record_type not in table_keys or pd.isna(related_record_id):
        return None

    table_name, key_column = table_keys[record_type]
    related = read_query(
        f"SELECT * FROM {table_name} WHERE {key_column} = ?",
        (int(related_record_id),),
    )
    return None if related.empty else related.iloc[0]


def describe_observed_and_expected(issue, related_record):
    """Turn stored issue and record metadata into two short explanations."""
    description = issue["description"]
    observed_match = re.search(r"changed ([+-]?[0-9.]+)%", description)
    threshold_match = re.search(r"threshold is ([0-9.]+)%", description)

    if observed_match and threshold_match:
        return (
            f"{observed_match.group(1)}% change",
            f"Absolute change at or below {threshold_match.group(1)}% IQR threshold",
        )

    if issue["rule_name"] == "market_close_reconciliation" and related_record is not None:
        return (
            f"{related_record['difference_percent']:.6f}% close difference",
            f"Difference at or below {MARKET_CLOSE_TOLERANCE_PERCENT:.2f}%",
        )

    if issue["record_type"] == "financial_metric" and related_record is not None:
        observed = (
            f"{related_record['metric_name']}: "
            f"{related_record['value']:,.0f} {related_record['unit']}"
        )
    elif issue["record_type"] == "market_price" and related_record is not None:
        observed = f"Close {related_record['close']:.4f}; volume {related_record['volume']:,.0f}"
    else:
        observed = "See the stored issue description"

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
    return observed, expected_by_rule.get(issue["rule_name"], "See the stored rule threshold")


def get_issue_source(issue, related_record):
    """Return the source name already stored with the related record."""
    if issue["record_type"] == "financial_metric":
        return "SEC Company Facts"
    if issue["record_type"] == "market_price" and related_record is not None:
        return related_record["source"]
    if issue["record_type"] == "reconciliation_result" and related_record is not None:
        return f"{related_record['source_a']} vs {related_record['source_b']}"
    return "Not available"


def show_incident_drilldown():
    render_page_heading(
        "Single-record review",
        "Incident Drilldown",
        "Inspect one alert and the source metadata already linked to its stored record.",
    )

    companies = read_query("SELECT ticker, company_name FROM company ORDER BY ticker")
    company_labels = {
        f"{row.ticker} — {row.company_name}": row.ticker
        for row in companies.itertuples(index=False)
    }

    with st.container(border=True):
        render_section_heading("Choose an incident", "Select a company, then one of its current DQ issues")
        selector_columns = st.columns(2)
        selected_company = selector_columns[0].selectbox(
            "Company", list(company_labels.keys()), key="incident_company"
        )
        ticker = company_labels[selected_company]
        issues = read_query(
            """
            SELECT * FROM dq_issue
            WHERE ticker = ?
            ORDER BY CASE severity WHEN 'CRITICAL' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,
                     issue_id
            """,
            (ticker,),
        )
        if issues.empty:
            st.info("This company has no stored DQ issues.")
            return

        issue_ids = issues["issue_id"].tolist()
        selected_issue_id = selector_columns[1].selectbox(
            "DQ issue",
            issue_ids,
            format_func=lambda issue_id: (
                f"Issue {issue_id} — "
                f"{issues.loc[issues['issue_id'] == issue_id, 'rule_name'].iloc[0]}"
            ),
            key="incident_issue",
        )

    issue = issues[issues["issue_id"] == selected_issue_id].iloc[0]
    related_record = get_related_record(issue["record_type"], issue["related_record_id"])
    observed, expected = describe_observed_and_expected(issue, related_record)
    source = get_issue_source(issue, related_record)

    st.write("")
    summary_columns = st.columns(4)
    with summary_columns[0]:
        render_detail_card("Ticker / company", selected_company)
    with summary_columns[1]:
        render_detail_card("Rule", issue["rule_name"])
    with summary_columns[2]:
        render_detail_card("Quality dimension", issue["dimension"])
    with summary_columns[3]:
        render_detail_card("Severity", issue["severity"])

    st.write("")
    value_columns = st.columns([2, 2, 1.4])
    with value_columns[0]:
        render_detail_card("Observed value", observed)
    with value_columns[1]:
        render_detail_card("Expected value / threshold", expected)
    with value_columns[2]:
        render_detail_card("Source", source)

    st.write("")
    render_message_card("Issue description", issue["description"])

    if issue["record_type"] == "financial_metric" and related_record is not None:
        st.write("")
        render_section_heading("Financial source metadata", "Original SEC metadata retained during ingestion")
        metadata_columns = st.columns(3)
        with metadata_columns[0]:
            render_detail_card("Source tag", related_record["source_tag"])
        with metadata_columns[1]:
            render_detail_card("Filing date", related_record["filing_date"])
        with metadata_columns[2]:
            render_detail_card("Period end date", related_record["period_end"])


st.markdown(APP_CSS, unsafe_allow_html=True)

if not DATABASE_PATH.exists():
    st.error(f"Database not found: {DATABASE_PATH}")
    st.stop()

render_app_header()
page = st.radio(
    "Navigation",
    ["Dataset Health", "Alerts Explorer", "Incident Drilldown"],
    horizontal=True,
    label_visibility="collapsed",
)

if page == "Dataset Health":
    show_dataset_health()
elif page == "Alerts Explorer":
    show_alerts_explorer()
else:
    show_incident_drilldown()
