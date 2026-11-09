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

    def create(self, price="349.90", at="2026-01-15T12:00:00+00:00"):
        with patch("app.subscriptions.utc_now", return_value=datetime.fromisoformat(at)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01")

    def test_create_and_exact_total(self):
        first, second = self.create(), self.create()
        self.assertIsInstance(first, str)
        self.assertNotEqual(first, second)
        row = self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (first,)).fetchone()
        self.assertEqual((row["user_id"], row["plan"], row["price_kopecks"]),
                         (self.user_id, "monthly", 34990))
        self.assertEqual(self.report(), "699.80")

    def test_small_amounts_and_empty_report(self):
        self.assertEqual(self.report(), "0.00")
        self.create("0.10")
        self.create("0.20")
        self.assertEqual(self.report(), "0.30")

    def test_invalid_prices_do_not_create_subscriptions(self):
        for price in ("0.00", "-1.00", "1.001", "1.0", "1", "NaN", "Infinity",
                      "1e2", " 1.00", "1,00", "", None, 349.90,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:40]), self.assertRaises(AppError):
                self.create(price)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_missing_and_deleted_users(self):
        with self.assertRaises(AppError):
            subscriptions.create_subscription(self.conn, 999, "monthly", "1.00")
        users.remove_user(self.conn, self.user_id)
        with self.assertRaises(AppError):
            self.create()

    def test_cancel_is_idempotent_and_excludes_revenue(self):
        cancelled = self.create()
        self.create()
        self.assertIsNone(subscriptions.cancel_subscription(self.conn, cancelled))
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(self.report(), "349.90")
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, "missing")

    def test_period_is_half_open(self):
        self.create("1.00", "2025-12-31T23:59:59+00:00")
        self.create("2.00", "2026-01-01T00:00:00+00:00")
        self.create("4.00", "2026-01-31T23:59:59+00:00")
        self.create("8.00", "2026-02-01T00:00:00+00:00")
        self.assertEqual(self.report(), "6.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-01-01"), "0.00")

    def test_invalid_dates(self):
        for start, end in (("2026-02-30", "2026-03-01"), ("20260101", "2026-02-01"),
                           ("2026-01-01", "bad"), (None, "2026-02-01"),
                           ("2026-02-01", "2026-01-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_total_can_exceed_sqlite_integer_range(self):
        self.create("92233720368547758.07")
        self.create("0.01")
        self.assertEqual(self.report(), "92233720368547758.08")

    def test_migrations_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "app.sqlite")
            conn = db.connect(path)
            try:
                user_id = users.add_user(conn, "persistent@example.com")
                subscription_id = subscriptions.create_subscription(conn, user_id, "monthly", "1.00")
            finally:
                conn.close()
            conn = db.connect(path)
            try:
                self.assertIsNotNone(conn.execute("SELECT id FROM subscriptions WHERE id = ?",
                                                 (subscription_id,)).fetchone())
                subscriptions.cancel_subscription(conn, subscription_id)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
