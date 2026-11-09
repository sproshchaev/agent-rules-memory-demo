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

    def create(self, at="2026-05-10T12:00:00+00:00", price="349.90"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(at)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def test_create_and_audit(self):
        subscription_id = self.create()
        self.assertEqual(str(uuid.UUID(subscription_id)), subscription_id)
        row = self.conn.execute("SELECT * FROM subscriptions").fetchone()
        self.assertEqual((row["price_kop"], row["status"], row["plan"]), (34990, "active", "monthly"))
        audit = self.conn.execute("SELECT * FROM audit_log").fetchone()
        self.assertEqual((audit["entity"], audit["entity_id"], audit["action"]),
                         ("subscription", subscription_id, "created"))
        self.assertEqual(audit["at"], "2026-05-10T12:00:00+00:00")

    def test_invalid_prices(self):
        for price in ("0.00", "-1.00", "349.9", "1.001", "NaN", "1e2", " 1.00", "1,00", "1", "", None, 1.0,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:30]):
                with self.assertRaises(AppError) as error:
                    self.create(price=price)
                self.assertEqual(error.exception.code, "SUB_BAD_PRICE")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 0)

    def test_missing_and_deleted_user(self):
        for user_id in (999, self.user_id):
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError) as error:
                subscriptions.create_subscription(self.conn, user_id, "monthly", "349.90")
            self.assertEqual(error.exception.code, "SUB_USER_NOT_FOUND")

    def test_report_boundaries_and_cancel(self):
        self.create("2026-04-30T23:59:59+00:00")
        self.create("2026-05-01T00:00:00+00:00")
        self.create("2026-05-31T23:59:59+00:00")
        cancelled = self.create()
        self.create("2026-06-01T00:00:00+00:00")
        subscriptions.cancel_subscription(self.conn, cancelled)
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"), "699.80")
        row = self.conn.execute("SELECT status FROM subscriptions WHERE id = ?", (cancelled,)).fetchone()
        self.assertEqual(row["status"], "cancelled")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = 'cancelled'").fetchone()[0], 1)
        with self.assertRaises(AppError) as error:
            subscriptions.cancel_subscription(self.conn, "missing")
        self.assertEqual(error.exception.code, "SUB_NOT_FOUND")

    def test_empty_and_invalid_periods(self):
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"), "0.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-05-01"), "0.00")
        for start, end in (("2026-02-30", "2026-03-01"), ("20260501", "2026-06-01"),
                           (None, "2026-06-01"), ("2026-05-01", "bad"), ("2026-06-01", "2026-05-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_exact_large_totals(self):
        self.create(price="92233720368547758.07")
        self.create(price="92233720368547758.07")
        self.create(price="0.01")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"),
                         "184467440737095516.15")

    def test_audit_failure_rolls_back_changes(self):
        with patch("app.db.add_audit", side_effect=AppError("TEST_FAILURE", "audit failed")):
            with self.assertRaises(AppError):
                self.create()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        subscription_id = self.create()
        with patch("app.db.add_audit", side_effect=AppError("TEST_FAILURE", "audit failed")):
            with self.assertRaises(AppError):
                subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"), "349.90")
