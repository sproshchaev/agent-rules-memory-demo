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

    def test_creation_and_exact_money(self):
        first = self.create()
        second = self.create()
        self.assertEqual(str(uuid.UUID(first)), first)
        self.assertNotEqual(first, second)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "699.80")
        row = self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (first,)).fetchone()
        self.assertEqual(row["price_kop"], 34990)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["created_at"], "2026-01-15T12:00:00+00:00")

    def test_bad_prices(self):
        for price in ("0.00", "-1.00", "1.001", "1", "1.2", "NaN", "inf", " 1.00", "1e2", "1,00", "", None, 1.5, "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:30]), self.assertRaises(AppError) as error:
                self.create(price)
            self.assertEqual(error.exception.code, "SUB_BAD_PRICE")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_missing_and_deleted_users(self):
        for user_id in (self.user_id + 1, self.user_id):
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError) as error:
                subscriptions.create_subscription(self.conn, user_id, "monthly", "1.00")
            self.assertEqual(error.exception.code, "SUB_USER_NOT_FOUND")

    def test_cancel_and_audit(self):
        subscription_id = self.create()
        subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "0.00")
        self.assertEqual(db.find_subscription(self.conn, subscription_id)["status"], "cancelled")
        actions = self.conn.execute("SELECT entity, entity_id, action FROM audit_log ORDER BY id").fetchall()
        self.assertEqual([tuple(row) for row in actions], [
            ("subscription", subscription_id, "created"),
            ("subscription", subscription_id, "cancelled"),
        ])
        with self.assertRaises(AppError) as error:
            subscriptions.cancel_subscription(self.conn, "missing")
        self.assertEqual(error.exception.code, "SUB_NOT_FOUND")

    def test_half_open_period_and_utc(self):
        self.create("1.00", "2025-12-31T23:59:59+00:00")
        self.create("0.10", "2026-01-01T03:00:00+03:00")
        self.create("0.20", "2026-01-31T23:59:59+00:00")
        self.create("2.00", "2026-02-01T00:00:00+00:00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "0.30")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-01-01"), "0.00")

    def test_invalid_dates(self):
        for start, end in (("2026-02-30", "2026-03-01"), ("2026-1-01", "2026-02-01"), (None, "2026-02-01"), ("2026-03-01", "2026-02-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_audit_failure_rolls_back_mutation(self):
        with patch("app.db.add_audit", side_effect=AppError("AUDIT_FAILED", "failed")):
            with self.assertRaises(AppError):
                self.create()
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        subscription_id = self.create()
        with patch("app.db.add_audit", side_effect=AppError("AUDIT_FAILED", "failed")):
            with self.assertRaises(AppError):
                subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)["status"], "active")

    def test_large_totals_do_not_overflow_sqlite_sum(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "184467440737095516.14")
