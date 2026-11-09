import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.user_id = users.add_user(self.conn, "anna@example.com")

    def create(self, price="349.90", at="2026-11-09T12:00:00+00:00"):
        with patch("app.subscriptions.utc_now", return_value=datetime.fromisoformat(at)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-11-01", "2026-12-01")

    def test_create_and_exact_revenue(self):
        first = self.create()
        second = self.create()
        self.assertIsInstance(first, str)
        self.assertNotEqual(first, second)
        self.assertEqual(self.report(), "699.80")
        self.create("0.10")
        self.create("0.20")
        self.assertEqual(self.report(), "700.10")

    def test_invalid_prices_leave_no_subscriptions(self):
        for price in ("0.00", "-1.00", "349.9", "1.001", "1", "NaN", "Infinity",
                      "1e2", " 1.00", "1,00", "", None, 1.0,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:30]), self.assertRaises(AppError):
                self.create(price)
        self.assertEqual(self.report(), "0.00")

    def test_missing_and_deleted_users(self):
        with self.assertRaises(AppError):
            subscriptions.create_subscription(self.conn, self.user_id + 1, "monthly", "1.00")
        users.remove_user(self.conn, self.user_id)
        with self.assertRaises(AppError):
            self.create()
        self.assertEqual(self.report(), "0.00")

    def test_cancel_is_idempotent_and_excludes_revenue(self):
        cancelled = self.create()
        self.create()
        subscriptions.cancel_subscription(self.conn, cancelled)
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(self.report(), "349.90")
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, "missing")

    def test_half_open_period(self):
        self.create("1.00", "2026-10-31T23:59:59+00:00")
        self.create("2.00", "2026-11-01T00:00:00+00:00")
        self.create("4.00", "2026-11-30T23:59:59+00:00")
        self.create("8.00", "2026-12-01T00:00:00+00:00")
        self.assertEqual(self.report(), "6.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-11-01", "2026-11-01"), "0.00")

    def test_invalid_dates(self):
        for start, end in (("2026-02-30", "2026-12-01"), ("2026-1-01", "2026-12-01"),
                           ("2026-11-01", "invalid"), (None, "2026-12-01"),
                           ("2026-12-01", "2026-11-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_large_totals_do_not_overflow(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(self.report(), "184467440737095516.14")

    def test_persistence_and_repeated_migrations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "app.db")
            conn = db.connect(path)
            try:
                user_id = users.add_user(conn, "persist@example.com")
                subscription_id = subscriptions.create_subscription(conn, user_id, "monthly", "1.00")
            finally:
                conn.close()
            conn = db.connect(path)
            try:
                self.assertEqual(conn.execute("SELECT price_kopecks FROM subscriptions WHERE id = ?",
                                              (subscription_id,)).fetchone()["price_kopecks"], 100)
            finally:
                conn.close()
