"""Download and standardize a small set of annual SEC Company Facts."""

import json
import os
import time
from pathlib import Path

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "sec"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

COMPANIES = {
    "AAPL": {"name": "Apple Inc.", "cik": "0000320193"},
    "MSFT": {"name": "Microsoft Corporation", "cik": "0000789019"},
    "AMZN": {"name": "Amazon.com, Inc.", "cik": "0001018724"},
    "WMT": {"name": "Walmart Inc.", "cik": "0000104169"},
    "KO": {"name": "The Coca-Cola Company", "cik": "0000021344"},
}

# This is deliberately small: canonical metric -> acceptable SEC US-GAAP tags.
# The order matters. Earlier tags are preferred when more than one tag is present.
XBRL_CONCEPT_MAP = {
    "Revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ],
    "Assets": ["Assets"],
    "Liabilities": ["Liabilities"],
    "Equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "Net Income": ["NetIncomeLoss", "ProfitLoss"],
    "Operating Income": ["OperatingIncomeLoss"],
}

SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
DEFAULT_USER_AGENT = "FinancialDataQualityMonitor student.portfolio@example.com"


def download_company_facts(ticker, cik, user_agent):
    """Download one company response and save it before any transformation."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = RAW_DIR / f"{ticker}_companyfacts.json"
    url = SEC_COMPANY_FACTS_URL.format(cik=cik)
    headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    raw_path.write_bytes(response.content)
    return raw_path


def read_annual_candidates(raw_path, ticker, company_name, cik):
    """Return all usable annual USD observations for the mapped concepts."""
    company_facts = json.loads(raw_path.read_text(encoding="utf-8"))
    us_gaap_facts = company_facts.get("facts", {}).get("us-gaap", {})
    rows = []

    for metric_name, source_tags in XBRL_CONCEPT_MAP.items():
        for tag_priority, source_tag in enumerate(source_tags):
            fact = us_gaap_facts.get(source_tag)
            if not fact:
                continue

            for observation in fact.get("units", {}).get("USD", []):
                if observation.get("form") not in {"10-K", "10-K/A"}:
                    continue
                if observation.get("fp") != "FY":
                    continue
                if not observation.get("end") or observation.get("val") is None:
                    continue

                rows.append(
                    {
                        "ticker": ticker,
                        "company_name": company_name,
                        "cik": cik,
                        "metric_name": metric_name,
                        "value": observation["val"],
                        "unit": "USD",
                        "fiscal_year": int(observation["end"][:4]),
                        "period_start": observation.get("start"),
                        "period_end": observation["end"],
                        "filing_date": observation.get("filed"),
                        "accession_number": observation.get("accn"),
                        "form": observation.get("form"),
                        "source_tag": source_tag,
                        "tag_priority": tag_priority,
                    }
                )

    return pd.DataFrame(rows)


def select_latest_five_years(candidates):
    """Choose one preferred observation per metric and period end."""
    if candidates.empty:
        return candidates

    selected_parts = []
    for ticker, company_rows in candidates.groupby("ticker"):
        latest_periods = sorted(company_rows["period_end"].unique(), reverse=True)[:5]
        recent_rows = company_rows[company_rows["period_end"].isin(latest_periods)].copy()

        # Prefer the first mapped tag. For repeated filings, keep the latest filing.
        recent_rows = recent_rows.sort_values(
            ["tag_priority", "filing_date"], ascending=[True, False]
        )
        recent_rows = recent_rows.drop_duplicates(
            subset=["ticker", "metric_name", "period_end"], keep="first"
        )
        selected_parts.append(recent_rows)

    selected = pd.concat(selected_parts, ignore_index=True)
    selected = selected.drop(columns="tag_priority")
    selected["is_derived"] = False
    selected["derivation"] = ""
    selected = add_derived_liabilities(selected)
    return selected.sort_values(
        ["ticker", "period_end", "metric_name"], ascending=[True, False, True]
    ).reset_index(drop=True)


def add_derived_liabilities(selected):
    """Fill total liabilities only when the SEC does not report that tag."""
    derived_rows = []

    for (ticker, period_end), period_rows in selected.groupby(["ticker", "period_end"]):
        metric_names = set(period_rows["metric_name"])
        if "Liabilities" in metric_names:
            continue
        if not {"Assets", "Equity"}.issubset(metric_names):
            continue

        assets = period_rows[period_rows["metric_name"] == "Assets"].iloc[0]
        equity = period_rows[period_rows["metric_name"] == "Equity"].iloc[0]
        derived = assets.copy()
        derived["metric_name"] = "Liabilities"
        derived["value"] = assets["value"] - equity["value"]
        derived["source_tag"] = "DERIVED:Assets-Equity"
        derived["is_derived"] = True
        derived["derivation"] = (
            f"Assets [{assets['source_tag']}] - "
            f"Equity [{equity['source_tag']}]"
        )

        if assets["accession_number"] != equity["accession_number"]:
            derived["accession_number"] = (
                f"{assets['accession_number']} | {equity['accession_number']}"
            )
        derived_rows.append(derived)

    if derived_rows:
        selected = pd.concat([selected, pd.DataFrame(derived_rows)], ignore_index=True)
    return selected


def ingest_sec_companies():
    """Download all five companies, transform them, and save one CSV."""
    user_agent = os.getenv("SEC_USER_AGENT", DEFAULT_USER_AGENT)
    all_candidates = []
    failures = []

    for ticker, company in COMPANIES.items():
        try:
            raw_path = download_company_facts(ticker, company["cik"], user_agent)
            candidates = read_annual_candidates(
                raw_path, ticker, company["name"], company["cik"]
            )
            all_candidates.append(candidates)
            print(f"{ticker}: saved raw response and found {len(candidates)} annual candidates")
        except (requests.RequestException, json.JSONDecodeError, OSError) as error:
            failures.append((ticker, str(error)))
            print(f"{ticker}: FAILED - {error}")

        # Stay comfortably below the SEC fair-access request-rate limit.
        time.sleep(0.2)

    if not all_candidates:
        raise RuntimeError("No SEC company data was retrieved.")

    candidates = pd.concat(all_candidates, ignore_index=True)
    standardized = select_latest_five_years(candidates)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = PROCESSED_DIR / "sec_financial_metrics.csv"
    standardized.to_csv(output_path, index=False)

    print(f"\nSaved {len(standardized)} standardized records to {output_path}")
    if failures:
        print("Failures:")
        for ticker, message in failures:
            print(f"  {ticker}: {message}")

    return standardized


def print_retrieval_summary(financial_data):
    """Print compact coverage and source-tag summaries for verification."""
    coverage = (
        financial_data.groupby("ticker")
        .agg(
            records=("metric_name", "size"),
            metrics=("metric_name", "nunique"),
            first_period=("period_end", "min"),
            latest_period=("period_end", "max"),
        )
        .reset_index()
    )
    metric_counts = pd.crosstab(financial_data["ticker"], financial_data["metric_name"])
    source_tags = (
        financial_data.groupby(["ticker", "metric_name"])["source_tag"]
        .unique()
        .apply(lambda tags: ", ".join(tags))
        .reset_index()
    )

    print("\nCoverage by company")
    print(coverage.to_string(index=False))
    print("\nRecord counts by metric")
    print(metric_counts.to_string())
    print("\nSource tags used")
    print(source_tags.to_string(index=False))


if __name__ == "__main__":
    data = ingest_sec_companies()
    print_retrieval_summary(data)
