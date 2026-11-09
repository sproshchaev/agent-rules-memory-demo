import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.user_id = users.add_user(self.conn, "anna@example.com")

    def create(self, price="349.90", at="2026-01-15T12:00:00+00:00"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(at)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def assert_error(self, code, function, *args):
        with self.assertRaises(AppError) as error:
            function(self.conn, *args)
        self.assertEqual(error.exception.code, code)

    def test_create_and_audit(self):
        subscription_id = self.create()
        self.assertEqual(str(uuid.UUID(subscription_id)), subscription_id)
        row = db.find_subscription(self.conn, subscription_id)
        self.assertEqual(row["price_kop"], 34990)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["plan"], "monthly")
        self.assertEqual(row["created_at"], "2026-01-15T12:00:00+00:00")
        audit = self.conn.execute("SELECT * FROM audit_log").fetchone()
        self.assertEqual((audit["entity"], audit["entity_id"], audit["action"]),
                         ("subscription", subscription_id, "created"))
        self.assertEqual(audit["at"], row["created_at"])

    def test_invalid_prices(self):
        for price in ("0.00", "-1.00", "1.001", "1.2", "1", "1,00", "NaN",
                      " 1.00", "1.00\n", "1e2", "", None, "92233720368547758.08"):
            with self.subTest(price=price):
                self.assert_error("SUB_BAD_PRICE", subscriptions.create_subscription,
                                  self.user_id, "monthly", price)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_missing_and_deleted_user(self):
        self.assert_error("SUB_USER_NOT_FOUND", subscriptions.create_subscription,
                          self.user_id + 1, "monthly", "1.00")
        users.remove_user(self.conn, self.user_id)
        self.assert_error("SUB_USER_NOT_FOUND", subscriptions.create_subscription,
                          self.user_id, "monthly", "1.00")

    def test_cancel_is_idempotent_and_audited(self):
        subscription_id = self.create()
        subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)["status"], "cancelled")
        actions = [r[0] for r in self.conn.execute("SELECT action FROM audit_log ORDER BY id")]
        self.assertEqual(actions, ["created", "cancelled"])
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "0.00")
        self.assert_error("SUB_NOT_FOUND", subscriptions.cancel_subscription, "missing")

    def test_report_boundaries_and_exact_sum(self):
        self.create(at="2025-12-31T23:59:59+00:00")
        self.create(at="2026-01-01T00:00:00+00:00")
        self.create(at="2026-01-31T23:59:59+00:00")
        self.create(at="2026-02-01T00:00:00+00:00")
        cancelled = self.create()
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "699.80")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-01-01"), "0.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2027-01-01", "2027-02-01"), "0.00")

    def test_small_prices_and_large_totals(self):
        self.create("0.01")
        self.create("0.09")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "0.10")
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"),
                         "184467440737095516.24")

    def test_invalid_dates(self):
        for date_value in ("2026-02-30", "2026-1-01", "2026-01-01T00:00:00", "", None):
            self.assert_error("SUB_BAD_DATE", subscriptions.revenue_report, date_value, "2026-03-01")
            self.assert_error("SUB_BAD_DATE", subscriptions.revenue_report, "2026-01-01", date_value)
        self.assert_error("SUB_BAD_PERIOD", subscriptions.revenue_report, "2026-02-01", "2026-01-01")

    def test_audit_failure_rolls_back_changes(self):
        with patch("app.db.add_audit", side_effect=AppError("TEST_FAILURE", "audit failed")):
            with self.assertRaises(AppError):
                self.create()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        subscription_id = self.create()
        with patch("app.db.add_audit", side_effect=AppError("TEST_FAILURE", "audit failed")):
            with self.assertRaises(AppError):
                subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)["status"], "active")
