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

    def create_at(self, moment, price="349.90"):
        with patch("app.subscriptions.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def test_create_and_exact_revenue(self):
        first = self.create_at("2026-01-10T12:00:00+00:00")
        second = self.create_at("2026-01-11T12:00:00+00:00")
        self.assertIsInstance(first, str)
        self.assertNotEqual(first, second)
        row = self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (first,)).fetchone()
        self.assertEqual((row["user_id"], row["plan"], row["price_kopecks"]),
                         (self.user_id, "monthly", 34990))
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "699.80")

    def test_half_open_period(self):
        self.create_at("2025-12-31T23:59:59+00:00", "1.00")
        self.create_at("2026-01-01T00:00:00+00:00", "2.00")
        self.create_at("2026-01-31T23:59:59+00:00", "4.00")
        self.create_at("2026-02-01T00:00:00+00:00", "8.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "6.00")

    def test_cancel_is_idempotent_and_excludes_historical_revenue(self):
        cancelled = self.create_at("2026-01-10T00:00:00+00:00")
        self.create_at("2026-01-11T00:00:00+00:00", "0.10")
        subscriptions.cancel_subscription(self.conn, cancelled)
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"), "0.10")

    def test_missing_subscription(self):
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, "missing")

    def test_missing_or_deleted_user(self):
        for user_id in (self.user_id + 1, self.user_id):
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError):
                subscriptions.create_subscription(self.conn, user_id, "monthly", "349.90")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_invalid_prices(self):
        for price in ("0", "0.00", "-1.00", "NaN", "Infinity", "1e2", "349,90",
                      "1.001", "", " 1.00", "1.00 ", ".10", "1.", None, 349.9,
                      "92233720368547758.08", "9" * 5000):
            with self.subTest(price=price), self.assertRaises(AppError):
                subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_empty_and_invalid_periods(self):
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-01-01"), "0.00")
        for start, end in (("2026-02-01", "2026-01-01"), ("2026-02-30", "2026-03-01"),
                           ("20260101", "2026-02-01"), (None, "2026-02-01")):
            with self.subTest(start=start), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_large_total_remains_exact(self):
        for _ in range(2):
            self.create_at("2026-01-10T00:00:00+00:00", "92233720368547758.07")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-01-01", "2026-02-01"),
                         "184467440737095516.14")

    def test_migrations_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "app.sqlite")
            conn = db.connect(path)
            try:
                user_id = users.add_user(conn, "saved@example.com")
                sid = subscriptions.create_subscription(conn, user_id, "monthly", "349.90")
            finally:
                conn.close()
            conn = db.connect(path)
            try:
                self.assertEqual(conn.execute("SELECT price_kopecks FROM subscriptions WHERE id = ?",
                                              (sid,)).fetchone()[0], 34990)
                subscriptions.cancel_subscription(conn, sid)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
