"""Run the real dashboard against the committed snapshot without modifying it."""

from contextlib import closing
import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from dashboard import app as ui


ROOT = Path(__file__).resolve().parents[1]


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.before = hashlib.sha256(ui.DATABASE_PATH.read_bytes()).hexdigest()
        self.addCleanup(self.assert_snapshot_unchanged)

    def assert_snapshot_unchanged(self):
        self.assertEqual(self.before, hashlib.sha256(ui.DATABASE_PATH.read_bytes()).hexdigest())

    def render(self, page="Dataset Overview"):
        app = AppTest.from_file(str(ROOT / "dashboard" / "app.py")).run(timeout=60)
        self.assertFalse(app.exception, [e.message for e in app.exception])
        if page != "Dataset Overview":
            app.radio(key="workspace_nav_radio").set_value(page).run(timeout=60)
            self.assertFalse(app.exception, [e.message for e in app.exception])
        return app

    def rerun(self, widget, value):
        app = widget.set_value(value).run(timeout=60)
        self.assertFalse(app.exception, [e.message for e in app.exception])
        return app

    def test_all_five_views_render(self):
        app = self.render()
        self.assertEqual(len(app.radio(key="workspace_nav_radio").options), 5)
        for page in app.radio(key="workspace_nav_radio").options:
            with self.subTest(page=page):
                self.rerun(app.radio(key="workspace_nav_radio"), page)

    def test_readonly_connection_and_missing_snapshot(self):
        with closing(ui._connect_readonly()) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("CREATE TABLE must_not_exist (value INTEGER)")
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "missing snapshot.db"
            with patch.object(ui, "DATABASE_PATH", missing):
                with self.assertRaises(sqlite3.OperationalError):
                    ui._connect_readonly()
            self.assertFalse(missing.exists())

    def test_scores_and_lineage_match_canonical_rows(self):
        expected = ui.read_query("""
            SELECT c.ticker, MAX(0, 100
                - 2 * SUM(CASE WHEN d.severity='LOW' THEN 1 ELSE 0 END)
                - 5 * SUM(CASE WHEN d.severity='MEDIUM' THEN 1 ELSE 0 END)
                - 10 * SUM(CASE WHEN d.severity='CRITICAL' THEN 1 ELSE 0 END)) AS dq_score
            FROM company c LEFT JOIN dq_issue d ON c.ticker=d.ticker
            GROUP BY c.ticker ORDER BY c.ticker
        """)
        actual = ui.get_company_scores()[["ticker", "dq_score"]]
        pd.testing.assert_frame_equal(actual, expected)
        alerts = ui.get_alerts()
        self.assertEqual(len(alerts), ui.get_single_value("SELECT COUNT(*) FROM dq_issue"))
        self.assertEqual(alerts.issue_id.nunique(), len(alerts))
        for alert in alerts.to_dict("records"):
            related = ui.get_related_record(alert["record_type"], alert["related_record_id"])
            self.assertIsNotNone(related)
            self.assertEqual(alert["ticker"], related["ticker"])
        self.assertEqual(ui.safe_text(None), "Not available")
        self.assertEqual(ui.safe_text(pd.NA), "Not available")
        self.assertEqual(ui.safe_text("<script>"), "&lt;script&gt;")
        self.assertIn("quality-run date", ui.RULE_CATALOG["stale_market_data"]["threshold"])

    def test_financial_origin_filters_empty_state_and_csv(self):
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            app = self.render()
            for label, code in [("Directly Reported Only (is_derived = 0)", 0),
                                ("Derived Only (is_derived = 1 · Assets - Equity)", 1)]:
                self.rerun(app.selectbox(key="ov_fin_origin"), label)
                call = download.call_args.kwargs
                exported = pd.read_csv(io.BytesIO(call["data"]))
                expected = ui.read_query("SELECT metric_id FROM financial_metric WHERE is_derived=?", (code,))
                self.assertEqual(set(exported["Metric ID"]), set(expected.metric_id))
                self.assertEqual(call["mime"], "text/csv")
            self.rerun(app.selectbox(key="ov_fin_company"), "AAPL")
            self.assertTrue(any("No financial metric records" in e.value for e in app.info))

    def test_investigation_filters_keyword_and_csv(self):
        with patch("streamlit.download_button", wraps=st.download_button) as download:
            app = self.render("Quality Investigations")
            self.rerun(app.selectbox(key="alerts_severity"), "MEDIUM")
            exported = pd.read_csv(io.BytesIO(download.call_args.kwargs["data"]))
            expected = ui.get_alerts().query("severity == 'MEDIUM'")
            self.assertEqual(set(exported["Issue ID"]), set(expected.issue_id))
            self.rerun(app.selectbox(key="alerts_severity"), "CRITICAL")
            self.assertTrue(any("No investigation flags" in e.value for e in app.info))
            self.rerun(app.selectbox(key="alerts_severity"), "All severities")
            self.rerun(app.text_input(key="alerts_search"), "[")
            self.assertTrue(any("No investigation flags" in e.value for e in app.info))

    def test_reconciliation_breaks_unmatched_rows_and_literal_date(self):
        app = self.render("Reconciliation")
        # Every view also renders the real engine's isolated 100/110 test fixture.
        fixture = next(d.value for d in app.dataframe if "test_scope" in d.value.columns)
        self.assertEqual(fixture.status.tolist(), ["BREAK"])
        self.assertEqual(fixture.difference_percent.tolist(), [10.0])
        self.rerun(app.selectbox(key="rec_filter_view"), "Mismatched Records Only (status = BREAK)")
        self.assertTrue(any("No reconciliation records" in e.value for e in app.info))
        self.rerun(app.selectbox(key="rec_filter_view"), "Unmatched Primary Market Records (market_price without recon pair)")
        shown = next(d.value for d in app.dataframe if "price_id" in d.value.columns)
        expected = ui.read_query("""
            SELECT mp.price_id FROM market_price mp LEFT JOIN reconciliation_result rr
              ON mp.ticker=rr.ticker AND mp.price_date=rr.price_date
            WHERE rr.reconciliation_id IS NULL
        """)
        self.assertEqual(set(shown.price_id), set(expected.price_id))
        self.rerun(app.text_input(key="rec_filter_date"), "[")
        self.assertTrue(any("No unmatched primary" in e.value for e in app.info))

    def test_direct_browser_reported_derived_market_and_comparison(self):
        app = self.render("Record Detail")
        self.rerun(app.radio(key="drilldown_mode"), app.radio(key="drilldown_mode").options[1])
        company = next(x for x in app.selectbox(key="direct_browser_company").options if x.startswith("AMZN"))
        self.rerun(app.selectbox(key="direct_browser_company"), company)
        derived_id = ui.get_single_value("SELECT metric_id FROM financial_metric WHERE ticker='AMZN' AND is_derived=1 LIMIT 1")
        app.selectbox(key="direct_fin_id").select(derived_id).run(timeout=60)
        self.assertFalse(app.exception, [e.message for e in app.exception])
        self.assertTrue(any("DERIVED VALUE" in e.value for e in app.markdown))
        table_options = list(app.selectbox(key="direct_browser_table").options)
        for table in table_options[1:]:
            self.rerun(app.selectbox(key="direct_browser_table"), table)


if __name__ == "__main__":
    unittest.main()
