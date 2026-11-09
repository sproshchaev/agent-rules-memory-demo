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

    def create(self, price="349.90", moment="2026-01-10T12:00:00+00:00"):
        with patch("app.subscriptions.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01")

    def test_create_and_exact_revenue(self):
        first = self.create()
        second = self.create()
        self.assertNotEqual(first, second)
        row = self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (first,)).fetchone()
        self.assertEqual((row["user_id"], row["plan"], row["price_kopecks"]),
                         (self.user_id, "monthly", 34990))
        self.assertEqual(self.report(), "699.80")

    def test_decimal_precision(self):
        self.create("0.10")
        self.create("0.20")
        self.assertEqual(self.report(), "0.30")

    def test_bad_prices_do_not_create_subscriptions(self):
        for price in ("0.00", "-1.00", "1.001", "1.0", "1", "NaN", "Infinity",
                      "1e2", " 1.00", "1.00\n", "349,90", "", None, 1.0,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=repr(price)[:80]), self.assertRaises(AppError):
                self.create(price)
        self.assertEqual(self.report(), "0.00")

    def test_missing_and_deleted_users(self):
        with self.assertRaises(AppError):
            subscriptions.create_subscription(self.conn, self.user_id + 1, "monthly", "1.00")
        users.remove_user(self.conn, self.user_id)
        with self.assertRaises(AppError):
            self.create()

    def test_cancellation_is_idempotent_and_excluded(self):
        subscription_id = self.create()
        self.create()
        subscriptions.cancel_subscription(self.conn, subscription_id)
        before = self.conn.execute("SELECT cancelled_at FROM subscriptions WHERE id = ?",
                                   (subscription_id,)).fetchone()[0]
        subscriptions.cancel_subscription(self.conn, subscription_id)
        after = self.conn.execute("SELECT cancelled_at FROM subscriptions WHERE id = ?",
                                  (subscription_id,)).fetchone()[0]
        self.assertEqual(before, after)
        self.assertIsNotNone(after)
        self.assertEqual(self.report(), "349.90")
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, 9999)

    def test_half_open_date_boundaries(self):
        self.create("1.00", "2025-12-31T23:59:59+00:00")
        self.create("2.00", "2026-01-01T00:00:00+00:00")
        self.create("4.00", "2026-01-31T23:59:59+00:00")
        self.create("8.00", "2026-02-01T00:00:00+00:00")
        self.assertEqual(self.report(), "6.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-01-01"), "0.00")

    def test_invalid_dates(self):
        for value in ("2026-02-30", "2026-1-01", "20260101", "2026-01-01T00:00:00", None):
            for bounds in ((value, "2026-03-01"), ("2026-01-01", value)):
                with self.subTest(bounds=bounds), self.assertRaises(AppError):
                    subscriptions.revenue_report(self.conn, *bounds)
        with self.assertRaises(AppError):
            subscriptions.revenue_report(self.conn, "2026-02-01", "2026-01-01")

    def test_large_totals_are_exact(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(self.report(), "184467440737095516.14")

    def test_migration_and_persistence(self):
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
                                              (subscription_id,)).fetchone()[0], 100)
                subscriptions.cancel_subscription(conn, subscription_id)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
