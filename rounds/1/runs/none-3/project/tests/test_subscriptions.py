import unittest
from datetime import datetime
from unittest.mock import patch

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.user_id = users.add_user(self.conn, "anna@example.com")

    def create(self, price="349.90", moment="2026-05-10T12:00:00+00:00"):
        with patch("app.subscriptions.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def test_create_and_exact_revenue(self):
        first = self.create()
        second = self.create()
        self.assertNotEqual(first, second)
        row = self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (first,)).fetchone()
        self.assertEqual((row["user_id"], row["plan"], row["price_kopecks"]),
                         (self.user_id, "monthly", 34990))
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"), "699.80")

    def test_period_boundaries(self):
        self.create(moment="2026-04-30T23:59:59+00:00")
        self.create(moment="2026-05-01T00:00:00+00:00")
        self.create(moment="2026-05-31T23:59:59+00:00")
        self.create(moment="2026-06-01T00:00:00+00:00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"), "699.80")

    def test_cancel_is_idempotent_and_excluded(self):
        subscription_id = self.create()
        self.create("0.10")
        subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"), "0.10")

    def test_missing_subscription(self):
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, 999)

    def test_missing_or_deleted_user(self):
        with self.assertRaises(AppError):
            subscriptions.create_subscription(self.conn, 999, "monthly", "349.90")
        users.remove_user(self.conn, self.user_id)
        with self.assertRaises(AppError):
            self.create()

    def test_invalid_prices(self):
        for price in ("0.00", "-1.00", "349.901", "349,90", "NaN", "Infinity",
                      "1e2", "349", "1.2", " 1.00", "+1.00", "", None,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=price), self.assertRaises(AppError):
                self.create(price)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)

    def test_empty_period_and_invalid_dates(self):
        self.create()
        for start, end in (("2026-05-10", "2026-05-10"), ("2020-01-01", "2020-02-01")):
            self.assertEqual(subscriptions.revenue_report(self.conn, start, end), "0.00")
        for start, end in (("2026-02-30", "2026-06-01"), ("2026-5-01", "2026-06-01"),
                           ("2026-06-01", "2026-05-01"), (None, "2026-06-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_large_totals_remain_exact(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"),
                         "184467440737095516.14")

    def test_migrations_can_run_again(self):
        self.create()
        db.apply_migrations(self.conn)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-05-01", "2026-06-01"), "349.90")
