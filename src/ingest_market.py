"""Download and standardize about one year of daily market prices."""

import argparse
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "market"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

TICKERS = ["AAPL", "MSFT", "AMZN", "WMT", "KO"]
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
NASDAQ_HISTORY_URL = "https://api.nasdaq.com/api/quote/{ticker}/historical"
MARKET_CLOSE_TOLERANCE_PERCENT = 0.50


def to_unix_timestamp(day):
    """Convert a date to a UTC timestamp required by Yahoo's endpoint."""
    return int(datetime.combine(day, time.min, tzinfo=timezone.utc).timestamp())


def download_yahoo_prices(ticker, start_date, end_date):
    """Download one Yahoo response and save it before parsing it."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{ticker}_yahoo.json"
    url = YAHOO_CHART_URL.format(ticker=ticker)
    parameters = {
        "period1": to_unix_timestamp(start_date),
        "period2": to_unix_timestamp(end_date + timedelta(days=1)),
        "interval": "1d",
        "events": "history",
    }
    headers = {"User-Agent": "FinancialDataQualityMonitor/0.1"}

    response = requests.get(url, params=parameters, headers=headers, timeout=30)
    response.raise_for_status()
    raw_path.write_bytes(response.content)
    return raw_path


def standardize_yahoo_prices(raw_path, ticker):
    """Convert Yahoo's nested JSON arrays into one row per trading day."""
    response_data = json.loads(raw_path.read_text(encoding="utf-8"))
    chart = response_data.get("chart", {})
    if chart.get("error"):
        raise ValueError(f"Yahoo returned an error: {chart['error']}")

    results = chart.get("result") or []
    if not results:
        raise ValueError(f"Yahoo returned no chart result for {ticker}")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = result.get("indicators", {}).get("quote") or []
    if not timestamps or not quotes:
        raise ValueError(f"Yahoo returned no daily quotes for {ticker}")

    quote = quotes[0]
    prices = pd.DataFrame(
        {
            "price_date": [
                datetime.fromtimestamp(value, tz=timezone.utc).date() for value in timestamps
            ],
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        }
    )

    prices = prices.dropna(subset=["open", "high", "low", "close", "volume"])
    prices = prices.drop_duplicates(subset="price_date", keep="last")
    prices = prices.sort_values("price_date").reset_index(drop=True)
    prices.insert(0, "ticker", ticker)
    prices["source"] = "Yahoo Finance chart"
    prices["price_date"] = prices["price_date"].astype(str)

    if prices.empty:
        raise ValueError(f"Yahoo returned no usable daily prices for {ticker}")
    return prices


def fetch_market_prices(ticker, start_date, end_date):
    """Provider entry point that can be replaced without changing the pipeline."""
    raw_path = download_yahoo_prices(ticker, start_date, end_date)
    return standardize_yahoo_prices(raw_path, ticker)


def download_nasdaq_closes(ticker, start_date, end_date):
    """Download source-B history and save its raw JSON before parsing."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{ticker}_nasdaq.json"
    url = NASDAQ_HISTORY_URL.format(ticker=ticker)
    parameters = {
        "assetclass": "stocks",
        "fromdate": start_date.isoformat(),
        "todate": end_date.isoformat(),
        "limit": 5000,
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.nasdaq.com",
        "Referer": "https://www.nasdaq.com/",
    }

    response = requests.get(url, params=parameters, headers=headers, timeout=30)
    response.raise_for_status()
    raw_path.write_bytes(response.content)
    return raw_path


def standardize_nasdaq_closes(raw_path, ticker):
    """Extract only the date and closing price needed for reconciliation."""
    response_data = json.loads(raw_path.read_text(encoding="utf-8"))
    data = response_data.get("data")
    if not data:
        raise ValueError(f"Nasdaq returned no historical data for {ticker}")

    rows = data.get("tradesTable", {}).get("rows") or []
    closes = pd.DataFrame(rows)
    if closes.empty or not {"date", "close"}.issubset(closes.columns):
        raise ValueError(f"Nasdaq returned no usable closing prices for {ticker}")

    closes = closes[["date", "close"]].copy()
    closes.columns = ["price_date", "close"]
    closes["price_date"] = pd.to_datetime(closes["price_date"], errors="coerce")
    closes["close"] = pd.to_numeric(
        closes["close"].str.replace("$", "", regex=False).str.replace(",", "", regex=False),
        errors="coerce",
    )
    closes = closes.dropna(subset=["price_date", "close"])
    closes = closes.drop_duplicates("price_date", keep="last")
    closes = closes.sort_values("price_date").reset_index(drop=True)
    closes.insert(0, "ticker", ticker)
    closes["source"] = "Nasdaq"
    closes["price_date"] = closes["price_date"].dt.strftime("%Y-%m-%d")
    return closes


def compare_market_closes(source_a, source_b):
    """Compare Yahoo and Nasdaq closes on matching ticker/date pairs."""
    yahoo = source_a[["ticker", "price_date", "close", "source"]].rename(
        columns={"close": "close_source_a", "source": "source_a"}
    )
    nasdaq = source_b[["ticker", "price_date", "close", "source"]].rename(
        columns={"close": "close_source_b", "source": "source_b"}
    )
    comparison = yahoo.merge(nasdaq, on=["ticker", "price_date"], how="inner")
    comparison["absolute_difference"] = (
        comparison["close_source_a"] - comparison["close_source_b"]
    ).abs()
    comparison["difference_percent"] = (
        comparison["absolute_difference"] / comparison["close_source_a"].abs() * 100
    )
    comparison["status"] = comparison["difference_percent"].apply(
        lambda difference: (
            "MATCH" if difference <= MARKET_CLOSE_TOLERANCE_PERCENT else "BREAK"
        )
    )
    return comparison.sort_values(["ticker", "price_date"]).reset_index(drop=True)


def ingest_reconciliation_source(tickers=None, days=370):
    """Fetch Nasdaq closes and compare them with the stored Yahoo closes."""
    selected_tickers = tickers or TICKERS
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    all_closes = []

    for ticker in selected_tickers:
        raw_path = download_nasdaq_closes(ticker, start_date, end_date)
        closes = standardize_nasdaq_closes(raw_path, ticker)
        all_closes.append(closes)
        print(
            f"{ticker}: {len(closes)} Nasdaq closes "
            f"from {closes['price_date'].min()} to {closes['price_date'].max()}"
        )

    nasdaq_closes = pd.concat(all_closes, ignore_index=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    nasdaq_path = PROCESSED_DIR / "market_close_nasdaq.csv"
    nasdaq_closes.to_csv(nasdaq_path, index=False)

    yahoo_path = PROCESSED_DIR / "market_prices.csv"
    if not yahoo_path.exists():
        raise FileNotFoundError("Run the Yahoo market ingestion before reconciliation.")

    yahoo_prices = pd.read_csv(yahoo_path)
    comparison = compare_market_closes(yahoo_prices, nasdaq_closes)
    comparison_path = PROCESSED_DIR / "market_reconciliation.csv"
    comparison.to_csv(comparison_path, index=False)

    print(f"\nSaved {len(comparison)} close comparisons to {comparison_path}")
    print(comparison["status"].value_counts().to_string())
    return comparison


def ingest_market_companies(tickers=None, days=370):
    """Fetch the requested tickers and save one standardized CSV."""
    selected_tickers = tickers or TICKERS
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    all_prices = []
    failures = []

    for ticker in selected_tickers:
        try:
            prices = fetch_market_prices(ticker, start_date, end_date)
            all_prices.append(prices)
            print(
                f"{ticker}: {len(prices)} rows "
                f"from {prices['price_date'].min()} to {prices['price_date'].max()}"
            )
        except (requests.RequestException, OSError, ValueError, pd.errors.ParserError) as error:
            failures.append((ticker, str(error)))
            print(f"{ticker}: FAILED - {error}")

    if not all_prices:
        raise RuntimeError("No market-price data was retrieved.")

    market_prices = pd.concat(all_prices, ignore_index=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if selected_tickers == TICKERS:
        output_name = "market_prices.csv"
    else:
        output_name = f"market_prices_{'_'.join(selected_tickers)}.csv"

    output_path = PROCESSED_DIR / output_name
    market_prices.to_csv(output_path, index=False)
    print(f"\nSaved {len(market_prices)} standardized rows to {output_path}")

    if failures:
        print("Failures:")
        for ticker, message in failures:
            print(f"  {ticker}: {message}")

    return market_prices


def print_market_summary(market_prices):
    """Print compact coverage and basic validation counts."""
    summary = (
        market_prices.groupby("ticker")
        .agg(
            rows=("price_date", "size"),
            first_date=("price_date", "min"),
            latest_date=("price_date", "max"),
            minimum_close=("close", "min"),
            maximum_close=("close", "max"),
        )
        .reset_index()
    )
    duplicate_rows = market_prices.duplicated(["ticker", "price_date"]).sum()
    missing_values = market_prices.isna().sum().sum()

    print("\nCoverage by company")
    print(summary.to_string(index=False))
    print(f"\nDuplicate ticker/date rows: {duplicate_rows}")
    print(f"Missing standardized values: {missing_values}")


def parse_arguments():
    parser = argparse.ArgumentParser(description="Download daily market prices")
    parser.add_argument(
        "--ticker",
        choices=TICKERS,
        help="Fetch one ticker for a small test. Omit it to fetch all five.",
    )
    parser.add_argument(
        "--source-b",
        action="store_true",
        help="Fetch Nasdaq closes and reconcile them against stored Yahoo closes.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    requested_tickers = [arguments.ticker] if arguments.ticker else TICKERS
    if arguments.source_b:
        ingest_reconciliation_source(requested_tickers)
    else:
        data = ingest_market_companies(requested_tickers)
        print_market_summary(data)
