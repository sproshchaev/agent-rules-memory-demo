import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.user_id = users.add_user(self.conn, "anna@example.com")

    def create(self, moment="2026-02-01T00:00:00+00:00", price="349.90"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01")

    def test_creation_and_exact_sum(self):
        first = self.create()
        second = self.create()
        self.assertNotEqual(first, second)
        self.assertEqual(self.report(), "699.80")

    def test_half_open_period_and_utc(self):
        self.create("2026-01-31T23:59:59+00:00")
        self.create("2026-02-01T00:00:00+00:00")
        self.create("2026-02-28T23:59:59+00:00")
        self.create("2026-03-01T00:00:00+00:00")
        self.create("2026-03-01T01:00:00+03:00", "0.01")
        self.assertEqual(self.report(), "699.81")

    def test_cancel_is_repeatable_and_excludes_revenue(self):
        subscription_id = self.create()
        subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(self.report(), "0.00")

    def test_unknown_subscription(self):
        with self.assertRaises(AppError) as caught:
            subscriptions.cancel_subscription(self.conn, 999)
        self.assertEqual(caught.exception.code, "subscription_not_found")

    def test_missing_or_deleted_user(self):
        for user_id in (999, self.user_id):
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError) as caught:
                subscriptions.create_subscription(self.conn, user_id, "monthly", "349.90")
            self.assertEqual(caught.exception.code, "user_not_found")

    def test_invalid_prices(self):
        for price in (None, 349.90, "", "349", "349.9", "349.900", "-1.00",
                      "0.00", "NaN", "1e2", " 1.00", "1,00", "١.00",
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:40]), self.assertRaises(AppError) as caught:
                self.create(price=price)
            self.assertEqual(caught.exception.code, "bad_price")
        self.assertEqual(self.report(), "0.00")

    def test_large_totals_use_integer_arithmetic(self):
        self.create(price="92233720368547758.07")
        self.create(price="92233720368547758.07")
        self.assertEqual(self.report(), "184467440737095516.14")

    def test_empty_periods(self):
        self.assertEqual(self.report(), "0.00")
        self.create()
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-02-01"), "0.00")

    def test_invalid_dates_and_period(self):
        for start, end in (("2026-02-30", "2026-03-01"), ("2026-2-01", "2026-03-01"),
                           ("2026-02-01", "bad"), (None, "2026-03-01"),
                           ("2026-03-01", "2026-02-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)
