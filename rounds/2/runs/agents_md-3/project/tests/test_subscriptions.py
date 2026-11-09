import unittest
import uuid
from datetime import datetime, timezone
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

    def test_create_and_audit(self):
        subscription_id = self.create()
        self.assertEqual(str(uuid.UUID(subscription_id)), subscription_id)
        row = self.conn.execute("SELECT * FROM subscriptions").fetchone()
        self.assertEqual((row["price_kop"], row["status"], row["plan"]),
                         (34990, "active", "monthly"))
        audit = self.conn.execute("SELECT * FROM audit_log").fetchone()
        self.assertEqual((audit["entity"], audit["entity_id"], audit["action"]),
                         ("subscription", subscription_id, "created"))
        self.assertEqual(audit["at"], "2026-01-15T12:00:00+00:00")

    def test_invalid_prices(self):
        for price in ["0.00", "-1.00", "349,90", "1.001", "NaN", "1e2", " 1.00", "1", "1.0",
                      "92233720368547758.08", "9" * 5000 + ".00", None]:
            with self.subTest(price=str(price)[:40]), self.assertRaises(AppError) as caught:
                self.create(price)
            self.assertEqual(caught.exception.code, "SUB_BAD_PRICE")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_missing_or_deleted_user(self):
        for user_id in [999, self.user_id]:
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError) as caught:
                subscriptions.create_subscription(self.conn, user_id, "monthly", "1.00")
            self.assertEqual(caught.exception.code, "SUB_USER_NOT_FOUND")

    def test_report_boundaries_and_cancellation(self):
        self.create(at="2025-12-31T23:59:59+00:00")
        self.create(at="2026-01-01T00:00:00+00:00")
        self.create()
        cancelled = self.create()
        self.create(at="2026-02-01T00:00:00+00:00")
        subscriptions.cancel_subscription(self.conn, cancelled)
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "699.80")
        self.assertEqual(db.find_subscription(self.conn, cancelled)["status"], "cancelled")
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'cancelled'"
        ).fetchone()[0], 1)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-01-01"), "0.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2027-01-01", "2027-02-01"), "0.00")

    def test_unknown_subscription(self):
        with self.assertRaises(AppError) as caught:
            subscriptions.cancel_subscription(self.conn, "missing")
        self.assertEqual(caught.exception.code, "SUB_NOT_FOUND")

    def test_invalid_period(self):
        for start, end in [("2026-02-30", "2026-03-01"), ("2026-1-01", "2026-02-01"),
                           ("2026-03-01", "2026-02-01"), ("0000-01-01", "2026-02-01")]:
            with self.subTest(start=start), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_large_total_and_kopecks(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.create("0.01")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"),
                         "184467440737095516.15")

    def test_audit_failure_rolls_back_changes(self):
        with patch("app.db.add_audit", side_effect=AppError("AUDIT_FAILED", "failed")):
            with self.assertRaises(AppError):
                self.create()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        subscription_id = self.create()
        with patch("app.db.add_audit", side_effect=AppError("AUDIT_FAILED", "failed")):
            with self.assertRaises(AppError):
                subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)["status"], "active")
