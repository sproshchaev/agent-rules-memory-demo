import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.user_id = users.add_user(self.conn, "anna@example.com")

    def create(self, price="349.90", when="2026-01-15T12:00:00+00:00"):
        with patch("app.subscriptions.utc_now", return_value=datetime.fromisoformat(when)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01")

    def test_creation_and_exact_total(self):
        first = self.create()
        second = self.create()
        self.assertIsInstance(first, int)
        self.assertNotEqual(first, second)
        self.assertEqual(self.report(), "699.80")
        row = self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (first,)).fetchone()
        self.assertEqual((row["user_id"], row["plan"], row["price_kopecks"]),
                         (self.user_id, "monthly", 34990))

    def test_small_amounts_and_normalization(self):
        for price in ("0.10", "0.20", "1", "2.5"):
            self.create(price)
        self.assertEqual(self.report(), "3.80")

    def test_invalid_prices_do_not_create_subscriptions(self):
        for price in ("0", "0.00", "-1.00", "1.001", "NaN", "Infinity", "1e2",
                      "349,90", " 1.00", "1.00 ", "", ".50", "1.", None, 1.0,
                      "92233720368547758.08", "9" * 5000):
            with self.subTest(price=str(price)[:30]), self.assertRaises(AppError):
                self.create(price)
        self.assertEqual(self.report(), "0.00")

    def test_missing_and_deleted_users(self):
        with self.assertRaises(AppError):
            subscriptions.create_subscription(self.conn, 999, "monthly", "1.00")
        users.remove_user(self.conn, self.user_id)
        with self.assertRaises(AppError):
            self.create()

    def test_cancellation_is_idempotent_and_excluded(self):
        subscription_id = self.create()
        self.create()
        subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(self.report(), "349.90")
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, 999)

    def test_half_open_period(self):
        for when in ("2025-12-31T23:59:59+00:00", "2026-01-01T00:00:00+00:00",
                     "2026-01-31T23:59:59+00:00", "2026-02-01T00:00:00+00:00"):
            self.create("1.01", when)
        self.assertEqual(self.report(), "2.02")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-01-01"), "0.00")

    def test_invalid_dates(self):
        for start, end in (("2026-02-30", "2026-03-01"), ("2026-1-01", "2026-02-01"),
                           ("2026-02-01", "2026-01-01"), (None, "2026-02-01"),
                           ("2026-01-01", "invalid")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_large_total_is_exact(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(self.report(), "184467440737095516.14")

    def test_migration_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "app.sqlite")
            conn = db.connect(path)
            try:
                user_id = users.add_user(conn, "persist@example.com")
                subscriptions.create_subscription(conn, user_id, "monthly", "1.23")
            finally:
                conn.close()
            conn = db.connect(path)
            try:
                self.assertEqual(conn.execute("SELECT price_kopecks FROM subscriptions").fetchone()[0], 123)
            finally:
                conn.close()
