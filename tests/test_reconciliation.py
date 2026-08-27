"""Controlled test for the market close reconciliation rule."""

import unittest

import pandas as pd

from src.ingest_market import compare_market_closes
from src.quality import check_market_close_reconciliation


class ReconciliationRuleTest(unittest.TestCase):
    def test_altered_source_b_close_creates_issue(self):
        source_a = pd.DataFrame(
            [
                {
                    "ticker": "AAPL",
                    "price_date": "2026-08-26",
                    "close": 100.00,
                    "source": "Yahoo Finance chart",
                }
            ]
        )

        # Intentionally inject a discrepancy to test the reconciliation failure path.
        source_b = source_a.copy()
        source_b.loc[0, "close"] = 110.00
        source_b.loc[0, "source"] = "Nasdaq"

        comparison = compare_market_closes(source_a, source_b)
        comparison.insert(0, "reconciliation_id", 1)
        issues = check_market_close_reconciliation(comparison)

        self.assertEqual(source_a.loc[0, "close"], 100.00)
        self.assertEqual(source_b.loc[0, "close"], 110.00)
        self.assertEqual(comparison.loc[0, "status"], "BREAK")
        self.assertAlmostEqual(comparison.loc[0, "difference_percent"], 10.0)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["rule_name"], "market_close_reconciliation")
        self.assertEqual(issues[0]["severity"], "MEDIUM")
        self.assertEqual(issues[0]["dimension"], "Consistency")
        print(f"Caught expected issue: {issues[0]['description']}")


if __name__ == "__main__":
    unittest.main()
