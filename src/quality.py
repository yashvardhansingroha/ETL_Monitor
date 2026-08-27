"""Run simple, explainable data-quality checks and save the failures."""

from datetime import date

import pandas as pd

try:
    from src.database import DATABASE_PATH, connect_database
except ModuleNotFoundError:
    from database import DATABASE_PATH, connect_database


EXPECTED_FINANCIAL_METRICS = {
    "Revenue",
    "Assets",
    "Liabilities",
    "Equity",
    "Net Income",
    "Operating Income",
}

# Standard IQR upper fence: Q3 + 1.5 * IQR.
IQR_MULTIPLIER = 1.5
ANOMALY_EXPLANATION = "Statistical anomaly flag; not a confirmed data error."


def make_issue(
    ticker,
    dimension,
    rule_name,
    severity,
    description,
    record_type=None,
    related_record_id=None,
):
    """Build one issue in the same shape as the dq_issue table."""
    return {
        "ticker": ticker,
        "record_type": record_type,
        "related_record_id": related_record_id,
        "rule_name": rule_name,
        "dimension": dimension,
        "severity": severity,
        "description": description,
    }


def check_missing_financial_metrics(financial_data):
    """Return an issue for each expected metric missing from a fiscal period."""
    issues = []

    for (ticker, period_end), rows in financial_data.groupby(["ticker", "period_end"]):
        missing_metrics = EXPECTED_FINANCIAL_METRICS - set(rows["metric_name"])
        for metric_name in sorted(missing_metrics):
            issues.append(
                make_issue(
                    ticker,
                    "Completeness",
                    "missing_financial_metric",
                    "CRITICAL",
                    f"{metric_name} is missing for the period ending {period_end}.",
                    "financial_metric",
                )
            )

    return issues


def check_duplicate_financial_records(financial_data):
    """Return an issue when a company, metric, and period appear more than once."""
    issues = []
    key_columns = ["ticker", "metric_name", "period_end"]
    duplicate_groups = financial_data.groupby(key_columns).size()

    for (ticker, metric_name, period_end), count in duplicate_groups.items():
        if count > 1:
            issues.append(
                make_issue(
                    ticker,
                    "Uniqueness",
                    "duplicate_financial_metric",
                    "MEDIUM",
                    f"Found {count} {metric_name} records for {period_end}.",
                    "financial_metric",
                )
            )

    return issues


def check_balance_sheet_equation(financial_data, tolerance=0.05):
    """Check whether Assets is approximately Liabilities plus Equity."""
    issues = []

    # Derived liabilities already use Assets - Equity, so checking them is circular.
    reported_rows = financial_data[financial_data["is_derived"] == 0]
    balance_metrics = reported_rows[
        reported_rows["metric_name"].isin(["Assets", "Liabilities", "Equity"])
    ]
    balances = balance_metrics.pivot_table(
        index=["ticker", "period_end"],
        columns="metric_name",
        values="value",
        aggfunc="first",
    )

    for (ticker, period_end), row in balances.iterrows():
        if not {"Assets", "Liabilities", "Equity"}.issubset(row.dropna().index):
            continue
        if row["Assets"] == 0:
            continue

        difference = abs(row["Assets"] - row["Liabilities"] - row["Equity"])
        difference_ratio = difference / abs(row["Assets"])
        if difference_ratio > tolerance:
            issues.append(
                make_issue(
                    ticker,
                    "Consistency",
                    "balance_sheet_equation",
                    "CRITICAL",
                    f"Assets differ from Liabilities + Equity by "
                    f"{difference_ratio:.1%} for {period_end}; tolerance is {tolerance:.0%}.",
                    "financial_metric",
                )
            )

    return issues


def check_large_financial_changes(financial_data):
    """Use IQR to flag unusual year-over-year Revenue and Net Income changes."""
    issues = []
    change_rows = []

    for (ticker, metric_name), rows in financial_data.groupby(["ticker", "metric_name"]):
        if metric_name not in {"Revenue", "Net Income"}:
            continue

        rows = rows.sort_values("period_end")
        previous_value = None
        previous_period = None

        for row in rows.itertuples(index=False):
            if previous_value is not None and previous_value != 0:
                change = (row.value - previous_value) / abs(previous_value)
                change_rows.append(
                    {
                        "ticker": ticker,
                        "metric_name": metric_name,
                        "period_end": row.period_end,
                        "previous_period": previous_period,
                        "change": change,
                        "absolute_change": abs(change),
                        "metric_id": int(row.metric_id),
                    }
                )

            previous_value = row.value
            previous_period = row.period_end

    changes = pd.DataFrame(change_rows)
    if changes.empty:
        return issues

    # Pool companies by metric to avoid calculating a threshold from only four
    # year-over-year changes for one company.
    for metric_name, metric_changes in changes.groupby("metric_name"):
        first_quartile = metric_changes["absolute_change"].quantile(0.25)
        third_quartile = metric_changes["absolute_change"].quantile(0.75)
        iqr = third_quartile - first_quartile
        upper_limit = third_quartile + IQR_MULTIPLIER * iqr

        unusual_changes = metric_changes[metric_changes["absolute_change"] > upper_limit]
        for row in unusual_changes.itertuples(index=False):
            issues.append(
                make_issue(
                    row.ticker,
                    "Consistency",
                    "unusual_financial_growth_iqr",
                    "MEDIUM",
                    f"{ANOMALY_EXPLANATION} {metric_name} changed {row.change:.1%} "
                    f"from {row.previous_period} to {row.period_end}; the IQR upper "
                    f"threshold is {upper_limit:.1%} "
                    f"(Q3 + {IQR_MULTIPLIER} x IQR).",
                    "financial_metric",
                    row.metric_id,
                )
            )

    return issues


def check_financial_timeliness(financial_data, maximum_age_days=550):
    """Flag a company when its latest annual period is too old."""
    issues = []
    today = pd.Timestamp(date.today())

    for ticker, rows in financial_data.groupby("ticker"):
        latest_period = pd.to_datetime(rows["period_end"]).max()
        age_days = (today - latest_period).days
        if age_days > maximum_age_days:
            issues.append(
                make_issue(
                    ticker,
                    "Timeliness",
                    "stale_financial_data",
                    "LOW",
                    f"Latest annual period is {latest_period.date()} ({age_days} days old); "
                    f"threshold is {maximum_age_days} days.",
                    "financial_metric",
                )
            )

    return issues


def check_nonpositive_prices(market_data):
    """Flag a row when any OHLC price is zero or negative."""
    issues = []
    price_columns = ["open", "high", "low", "close"]

    for row in market_data.itertuples(index=False):
        invalid_columns = [column for column in price_columns if getattr(row, column) <= 0]
        if invalid_columns:
            issues.append(
                make_issue(
                    row.ticker,
                    "Validity",
                    "nonpositive_price",
                    "CRITICAL",
                    f"{row.price_date} has zero or negative values in: "
                    f"{', '.join(invalid_columns)}.",
                    "market_price",
                    int(row.price_id),
                )
            )

    return issues


def check_negative_volume(market_data):
    """Flag a row when volume is negative."""
    issues = []

    for row in market_data.itertuples(index=False):
        if row.volume < 0:
            issues.append(
                make_issue(
                    row.ticker,
                    "Validity",
                    "negative_volume",
                    "CRITICAL",
                    f"Volume is {row.volume} on {row.price_date}; volume cannot be negative.",
                    "market_price",
                    int(row.price_id),
                )
            )

    return issues


def check_high_below_low(market_data):
    """Flag a row when its daily high is below its daily low."""
    issues = []

    for row in market_data.itertuples(index=False):
        if row.high < row.low:
            issues.append(
                make_issue(
                    row.ticker,
                    "Consistency",
                    "high_below_low",
                    "CRITICAL",
                    f"High {row.high:.2f} is below low {row.low:.2f} on {row.price_date}.",
                    "market_price",
                    int(row.price_id),
                )
            )

    return issues


def check_ohlc_consistency(market_data):
    """Flag open or close prices that fall outside the daily low/high range."""
    issues = []

    for row in market_data.itertuples(index=False):
        invalid_fields = []
        if not row.low <= row.open <= row.high:
            invalid_fields.append("open")
        if not row.low <= row.close <= row.high:
            invalid_fields.append("close")

        if invalid_fields:
            issues.append(
                make_issue(
                    row.ticker,
                    "Consistency",
                    "ohlc_consistency",
                    "CRITICAL",
                    f"{', '.join(invalid_fields)} falls outside the low/high range "
                    f"on {row.price_date}.",
                    "market_price",
                    int(row.price_id),
                )
            )

    return issues


def check_large_daily_movements(market_data):
    """Use the IQR rule to flag unusually large absolute daily returns."""
    issues = []

    for ticker, rows in market_data.groupby("ticker"):
        rows = rows.sort_values("price_date").copy()
        rows["daily_return"] = rows["close"].pct_change(fill_method=None)
        rows["absolute_return"] = rows["daily_return"].abs()
        usable_returns = rows["absolute_return"].dropna()

        if usable_returns.empty:
            continue

        first_quartile = usable_returns.quantile(0.25)
        third_quartile = usable_returns.quantile(0.75)
        iqr = third_quartile - first_quartile
        upper_limit = third_quartile + IQR_MULTIPLIER * iqr

        for row in rows[rows["absolute_return"] > upper_limit].itertuples(index=False):
            issues.append(
                make_issue(
                    ticker,
                    "Consistency",
                    "unusual_daily_return_iqr",
                    "LOW",
                    f"{ANOMALY_EXPLANATION} Close changed {row.daily_return:.2%} "
                    f"on {row.price_date}; the IQR upper threshold is {upper_limit:.2%} "
                    f"(Q3 + {IQR_MULTIPLIER} x IQR).",
                    "market_price",
                    int(row.price_id),
                )
            )

    return issues


def check_market_timeliness(market_data, maximum_age_days=7):
    """Flag a company when its latest market date is too old."""
    issues = []
    today = pd.Timestamp(date.today())

    for ticker, rows in market_data.groupby("ticker"):
        latest_date = pd.to_datetime(rows["price_date"]).max()
        age_days = (today - latest_date).days
        if age_days > maximum_age_days:
            issues.append(
                make_issue(
                    ticker,
                    "Timeliness",
                    "stale_market_data",
                    "MEDIUM",
                    f"Latest market date is {latest_date.date()} ({age_days} days old); "
                    f"threshold is {maximum_age_days} days.",
                    "market_price",
                )
            )

    return issues


def check_market_close_reconciliation(reconciliation_data):
    """Flag source-A/source-B close comparisons that exceed the stored tolerance."""
    issues = []

    for row in reconciliation_data.itertuples(index=False):
        if row.status == "BREAK":
            issues.append(
                make_issue(
                    row.ticker,
                    "Consistency",
                    "market_close_reconciliation",
                    "MEDIUM",
                    f"{row.source_a} close {row.close_source_a:.4f} and "
                    f"{row.source_b} close {row.close_source_b:.4f} differ by "
                    f"{row.difference_percent:.3f}% on {row.price_date}.",
                    "reconciliation_result",
                    int(row.reconciliation_id),
                )
            )

    return issues


def insert_issues(connection, issues):
    """Replace the previous quality results with the current run."""
    connection.execute("DELETE FROM dq_issue")
    insert_sql = """
        INSERT INTO dq_issue (
            ticker, record_type, related_record_id, rule_name,
            dimension, severity, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            issue["ticker"],
            issue["record_type"],
            issue["related_record_id"],
            issue["rule_name"],
            issue["dimension"],
            issue["severity"],
            issue["description"],
        )
        for issue in issues
    ]
    connection.executemany(insert_sql, rows)
    connection.commit()


def run_quality_checks(database_path=DATABASE_PATH):
    """Load database records, run every rule, and save all failures."""
    with connect_database(database_path) as connection:
        financial_data = pd.read_sql_query("SELECT * FROM financial_metric", connection)
        market_data = pd.read_sql_query("SELECT * FROM market_price", connection)
        reconciliation_data = pd.read_sql_query(
            "SELECT * FROM reconciliation_result", connection
        )

        issues = []
        issues.extend(check_missing_financial_metrics(financial_data))
        issues.extend(check_duplicate_financial_records(financial_data))
        issues.extend(check_balance_sheet_equation(financial_data))
        issues.extend(check_large_financial_changes(financial_data))
        issues.extend(check_financial_timeliness(financial_data))
        issues.extend(check_nonpositive_prices(market_data))
        issues.extend(check_negative_volume(market_data))
        issues.extend(check_high_below_low(market_data))
        issues.extend(check_ohlc_consistency(market_data))
        issues.extend(check_large_daily_movements(market_data))
        issues.extend(check_market_timeliness(market_data))
        issues.extend(check_market_close_reconciliation(reconciliation_data))

        insert_issues(connection, issues)
    return issues


def print_issue_summary(database_path=DATABASE_PATH):
    """Print issue totals using simple SQL queries."""
    with connect_database(database_path) as connection:
        total = connection.execute("SELECT COUNT(*) FROM dq_issue").fetchone()[0]
        print(f"Total issues: {total}")

        query = """
            SELECT ticker, dimension, severity, COUNT(*) AS issue_count
            FROM dq_issue
            GROUP BY ticker, dimension, severity
            ORDER BY ticker, dimension, severity
        """
        rows = connection.execute(query).fetchall()
        for ticker, dimension, severity, count in rows:
            print(f"{ticker}: {dimension} / {severity} = {count}")


if __name__ == "__main__":
    saved_issues = run_quality_checks()
    print(f"Saved {len(saved_issues)} issues to dq_issue.\n")
    print_issue_summary()
