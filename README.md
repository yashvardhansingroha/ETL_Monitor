# Financial Data Quality & ETL Monitor

## 1. What I Built

I built a small financial data pipeline for five US-listed companies: AAPL, MSFT, AMZN, WMT, and KO. It downloads annual financial facts and daily market prices, standardizes the fields, loads them into SQLite, runs explainable data-quality checks, and displays the results in Streamlit.

The project currently stores five annual periods for six financial metrics and about one year of daily market data. It also compares closing prices from two market sources.

## 2. Why I Built It

I built this project to understand the practical work behind financial data management. A financial value is useful only when I know what it represents, which filing it came from, whether it is complete, and whether it agrees with related data.

The project helped me practise Python, pandas, SQL, source mapping, reconciliation, quality rules, and explaining why an anomaly needs investigation instead of automatically calling it an error.

## 3. Architecture

```text
SEC Company Facts ──> raw SEC JSON ──> canonical financial metrics ──┐
                                                                    │
Yahoo daily prices ──> raw Yahoo JSON ──> standardized OHLCV ───────┼──> SQLite
                                                                    │
Nasdaq closes ──────> raw Nasdaq JSON ──> close reconciliation ─────┘
                                                                        │
                                                                        v
                                                              Data-quality rules
                                                                        │
                                                                        v
                                                              Streamlit dashboard
```

The main files are:

```text
src/
  ingest_sec.py       SEC download, XBRL mapping, and annual selection
  ingest_market.py    Yahoo/Nasdaq downloads and close reconciliation
  database.py         SQLite schema and data loading
  quality.py          Data-quality and anomaly rules
dashboard/
  app.py              Streamlit dashboard
tests/
  test_reconciliation.py
docs/
  client_personas.md
  process_improvements.md
```

Raw responses are saved before transformation under `data/raw/`. Standardized intermediate files are saved under `data/processed/`, while the dashboard reads directly from `data/financial_data.db`.

## 4. Data Sources

### SEC Company Facts

The financial data comes from the SEC EDGAR Company Facts API. I keep annual `10-K` and `10-K/A` observations for:

- Revenue
- Assets
- Liabilities
- Equity
- Net Income
- Operating Income

A small dictionary maps common US-GAAP XBRL tags to these canonical names. Each record keeps its original source tag, filing date, period end, accession number, form, and unit.

AMZN, WMT, and KO do not report the plain `Liabilities` tag in the selected Company Facts records. For those companies, liabilities are transparently calculated as `Assets - Equity` and marked as derived.

### Market Prices

Yahoo Finance chart data is the primary market source. It provides daily open, high, low, close, and volume values.

Nasdaq historical data is used as the second source for closing-price reconciliation. It is not loaded into the main `market_price` table.

## 5. Database Tables

The SQLite database contains five tables:

| Table | Purpose |
|---|---|
| `company` | One row per ticker, including company name and SEC CIK |
| `financial_metric` | Annual canonical metrics and SEC source metadata |
| `market_price` | Daily Yahoo OHLCV records |
| `reconciliation_result` | Yahoo close versus Nasdaq close by ticker and date |
| `dq_issue` | Failed quality checks and statistical anomaly flags |

The ticker is the primary key in `company`. The other tables use generated integer primary keys and link back to `company.ticker` through foreign keys.

## 6. Data-Quality Rules

### Financial rules

- Required financial metric is missing
- Duplicate company, metric, and period record
- Assets approximately equal Liabilities plus Equity
- Unusual year-on-year Revenue or Net Income change
- Latest annual period is stale

The balance-sheet equation is skipped when liabilities were derived from the same equation, because checking it would be circular.

### Market rules

- OHLC price is zero or negative
- Volume is negative
- High is below low
- Open or close falls outside the daily low/high range
- Unusual daily close-to-close return
- Latest market date is stale

### Reconciliation rule

- Yahoo and Nasdaq closing prices differ by more than 0.50%

Issues are assigned a quality dimension such as Completeness, Validity, Consistency, Uniqueness, or Timeliness. Severities are LOW, MEDIUM, and CRITICAL.

## 7. Market Reconciliation

The reconciliation joins Yahoo and Nasdaq records on ticker and trading date. It stores both closing prices, their absolute difference, their percentage difference, and either `MATCH` or `BREAK`.

The threshold is 0.50%. This prevents very small decimal-precision differences from creating meaningless breaks.

The project includes a controlled failure test. It creates isolated sample records with a Yahoo close of 100 and a Nasdaq close of 110. The 10% difference is marked as `BREAK` and produces exactly one MEDIUM Consistency issue. The test does not write to the production SQLite database.

## 8. Statistical Anomaly Detection

I use the interquartile range, or IQR, rather than a black-box model.

The upper anomaly threshold is:

```text
Q3 + 1.5 × IQR
```

For financial growth, the threshold is calculated separately for Revenue and Net Income using changes pooled across the five companies. For market data, the daily-return threshold is calculated separately for each ticker.

These results are labelled as statistical anomaly flags, not confirmed data errors. A large movement may be genuine and should be checked against the source.

## 9. Dashboard

The Streamlit dashboard has three pages:

1. **Dataset Health** shows record counts, issue counts, DQ scores, severity mix, and reconciliation results.
2. **Alerts Explorer** filters issues by company, severity, dimension, and rule.
3. **Incident Drilldown** shows one issue with its observed value, expected threshold, source, and available SEC filing metadata.

The dashboard reads from SQLite and does not create a separate copy of the data.

## 10. How to Run the Project

Run the commands from the project root.

### Install the packages

```powershell
python -m pip install pandas requests streamlit plotly
```

### Set a real SEC contact identity

The SEC asks API users to identify themselves. Replace the example with your own name and email.

```powershell
$env:SEC_USER_AGENT="Your Name your.email@example.com"
```

### Run the pipeline in order

```powershell
python src\ingest_sec.py
python src\ingest_market.py
python src\ingest_market.py --source-b
python src\database.py
python src\quality.py
```

The database loader replaces the previous MVP dataset. Run the quality engine after loading because a reload clears the previous `dq_issue` rows.

### Run the controlled test

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

### Start the dashboard

```powershell
python -m streamlit run dashboard\app.py
```

Then open `http://localhost:8501`.

## 11. Current Results

The current local database contains:

- 5 companies
- 150 annual financial metric records
- 1,270 Yahoo daily market-price records
- 1,270 Yahoo/Nasdaq closing-price comparisons
- 0 real reconciliation breaks
- Largest real reconciliation variance of approximately 0.0000057%
- 60 existing anomaly/DQ issues

The 60 issues consist of 57 LOW daily-return IQR flags and 3 MEDIUM AMZN net-income growth flags. There are currently no CRITICAL issues.

The controlled reconciliation test successfully detects the deliberately introduced 10% break while leaving the production database unchanged.

## 12. Limitations

- The project covers only five US-listed companies and about one year of market prices.
- The pipeline is batch-based, not real-time. Financial data is annual only, and quarterly facts are not included.
- The SEC XBRL mapping covers only six financial metrics and a small list of common tags.
- Company-specific XBRL extension tags may not be fully handled.
- Some liabilities are derived from Assets and Equity rather than directly reported under the `Liabilities` tag.
- Quality tolerances and IQR settings are simple, manually selected thresholds for this student project.
- Anomalies are investigation flags, not proof that the underlying data is bad.
- There is no ML model; anomaly detection uses the explainable IQR method.
- There is no second fundamentals provider. Reconciliation is limited to Yahoo and Nasdaq market closing prices.
- Yahoo and Nasdaq are public data endpoints and may change their formats or access rules.
- A match between two public market sources does not prove that a value is correct.
- Corporate actions, adjusted-price conventions, currencies, and trading calendars are not handled in depth.
- SQLite is used instead of a production database, and issue statuses do not yet have a user workflow for resolution.
- Current counts will change when the pipeline is rerun with newer source data.
