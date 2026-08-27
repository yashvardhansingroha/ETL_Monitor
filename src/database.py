"""Create and load the small SQLite database used by the MVP."""

import sqlite3
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "financial_data.db"
FINANCIAL_CSV = DATA_DIR / "processed" / "sec_financial_metrics.csv"
MARKET_CSV = DATA_DIR / "processed" / "market_prices.csv"
RECONCILIATION_CSV = DATA_DIR / "processed" / "market_reconciliation.csv"


SCHEMA_SQL = """
-- ticker is the primary key: one row identifies one company.
CREATE TABLE IF NOT EXISTS company (
    ticker TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    cik TEXT NOT NULL
);

-- metric_id is an automatically generated primary key for each financial row.
-- ticker is a foreign key: every financial row must belong to company.ticker.
CREATE TABLE IF NOT EXISTS financial_metric (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    period_start TEXT,
    period_end TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    accession_number TEXT NOT NULL,
    form TEXT NOT NULL,
    source_tag TEXT NOT NULL,
    is_derived INTEGER NOT NULL DEFAULT 0,
    derivation TEXT,
    FOREIGN KEY (ticker) REFERENCES company(ticker)
);

-- price_id is the primary key for each daily market-price row.
-- ticker is a foreign key: every price row must belong to company.ticker.
CREATE TABLE IF NOT EXISTS market_price (
    price_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    price_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    source TEXT NOT NULL,
    FOREIGN KEY (ticker) REFERENCES company(ticker)
);

-- reconciliation_id is the primary key for each source-A/source-B comparison.
-- ticker is a foreign key: every comparison must belong to company.ticker.
CREATE TABLE IF NOT EXISTS reconciliation_result (
    reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    price_date TEXT NOT NULL,
    source_a TEXT NOT NULL,
    close_source_a REAL NOT NULL,
    source_b TEXT NOT NULL,
    close_source_b REAL NOT NULL,
    absolute_difference REAL NOT NULL,
    difference_percent REAL NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (ticker) REFERENCES company(ticker)
);

-- issue_id is the primary key for each detected data-quality problem.
-- ticker is a foreign key so every issue is assigned to a known company.
-- related_record_id is optional because it may refer to either source table.
CREATE TABLE IF NOT EXISTS dq_issue (
    issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    record_type TEXT,
    related_record_id INTEGER,
    rule_name TEXT NOT NULL,
    dimension TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ticker) REFERENCES company(ticker)
);
"""


def connect_database(database_path=DATABASE_PATH):
    """Open SQLite and enforce its foreign-key rules."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_tables(connection):
    """Create the four MVP tables when they do not already exist."""
    connection.executescript(SCHEMA_SQL)
    connection.commit()


def clear_tables(connection):
    """Remove the previous run in child-to-parent order."""
    connection.execute("DELETE FROM dq_issue")
    connection.execute("DELETE FROM reconciliation_result")
    connection.execute("DELETE FROM financial_metric")
    connection.execute("DELETE FROM market_price")
    connection.execute("DELETE FROM company")
    connection.commit()


def none_if_missing(value):
    """Convert pandas missing values into values SQLite understands."""
    return None if pd.isna(value) else value


def load_companies(connection, financial_data):
    """Load one company row per ticker from the SEC data."""
    companies = financial_data[["ticker", "company_name", "cik"]].drop_duplicates("ticker")
    rows = [
        (row.ticker, row.company_name, str(row.cik).zfill(10))
        for row in companies.itertuples(index=False)
    ]
    connection.executemany(
        "INSERT INTO company (ticker, company_name, cik) VALUES (?, ?, ?)", rows
    )


def load_financial_metrics(connection, financial_data):
    """Load standardized SEC metric rows."""
    insert_sql = """
        INSERT INTO financial_metric (
            ticker, metric_name, value, unit, fiscal_year, period_start,
            period_end, filing_date, accession_number, form, source_tag,
            is_derived, derivation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = []

    for row in financial_data.itertuples(index=False):
        rows.append(
            (
                row.ticker,
                row.metric_name,
                float(row.value),
                row.unit,
                int(row.fiscal_year),
                none_if_missing(row.period_start),
                row.period_end,
                row.filing_date,
                row.accession_number,
                row.form,
                row.source_tag,
                int(bool(row.is_derived)),
                none_if_missing(row.derivation),
            )
        )

    connection.executemany(insert_sql, rows)


def load_market_prices(connection, market_data):
    """Load standardized daily OHLCV rows."""
    insert_sql = """
        INSERT INTO market_price (
            ticker, price_date, open, high, low, close, volume, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            row.ticker,
            row.price_date,
            float(row.open),
            float(row.high),
            float(row.low),
            float(row.close),
            int(row.volume),
            row.source,
        )
        for row in market_data.itertuples(index=False)
    ]
    connection.executemany(insert_sql, rows)


def load_reconciliation_results(connection, reconciliation_data):
    """Load source-A versus source-B closing-price comparisons."""
    insert_sql = """
        INSERT INTO reconciliation_result (
            ticker, price_date, source_a, close_source_a, source_b,
            close_source_b, absolute_difference, difference_percent, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    rows = [
        (
            row.ticker,
            row.price_date,
            row.source_a,
            float(row.close_source_a),
            row.source_b,
            float(row.close_source_b),
            float(row.absolute_difference),
            float(row.difference_percent),
            row.status,
        )
        for row in reconciliation_data.itertuples(index=False)
    ]
    connection.executemany(insert_sql, rows)


def load_database(database_path=DATABASE_PATH):
    """Read both standardized CSVs and reload the complete MVP database."""
    financial_data = pd.read_csv(FINANCIAL_CSV, dtype={"cik": str})
    market_data = pd.read_csv(MARKET_CSV)
    reconciliation_data = pd.read_csv(RECONCILIATION_CSV)

    with connect_database(database_path) as connection:
        create_tables(connection)
        clear_tables(connection)
        load_companies(connection, financial_data)
        load_financial_metrics(connection, financial_data)
        load_market_prices(connection, market_data)
        load_reconciliation_results(connection, reconciliation_data)
        connection.commit()

    return database_path


def print_table_counts(database_path=DATABASE_PATH):
    """Run basic SQL count queries for all four tables."""
    count_queries = {
        "company": "SELECT COUNT(*) FROM company",
        "financial_metric": "SELECT COUNT(*) FROM financial_metric",
        "market_price": "SELECT COUNT(*) FROM market_price",
        "reconciliation_result": "SELECT COUNT(*) FROM reconciliation_result",
        "dq_issue": "SELECT COUNT(*) FROM dq_issue",
    }

    with connect_database(database_path) as connection:
        for table_name, query in count_queries.items():
            count = connection.execute(query).fetchone()[0]
            print(f"{table_name}: {count}")

        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        print(f"foreign_key_errors: {len(foreign_key_errors)}")


if __name__ == "__main__":
    loaded_path = load_database()
    print(f"Loaded SQLite database: {loaded_path}\n")
    print_table_counts(loaded_path)
