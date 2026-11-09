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

    def create(self, date="2026-03-01T00:00:00+00:00", price="349.90"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(date)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-03-01", "2026-04-01")

    def test_create_and_exact_revenue(self):
        first = self.create()
        second = self.create()
        self.assertNotEqual(first, second)
        self.assertEqual(self.report(), "699.80")

    def test_period_boundaries(self):
        self.create("2026-02-28T23:59:59+00:00")
        self.create()
        self.create("2026-03-31T23:59:59+00:00")
        self.create("2026-04-01T00:00:00+00:00")
        self.assertEqual(self.report(), "699.80")

    def test_cancel_is_repeatable_and_excludes_revenue(self):
        subscription_id = self.create()
        self.create(price="0.01")
        subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertIsNotNone(db.find_subscription(self.conn, subscription_id)["cancelled_at"])
        self.assertEqual(self.report(), "0.01")

    def test_missing_subscription(self):
        with self.assertRaises(AppError) as error:
            subscriptions.cancel_subscription(self.conn, 999)
        self.assertEqual(error.exception.code, "subscription_not_found")

    def test_missing_and_deleted_user(self):
        with self.assertRaises(AppError):
            subscriptions.create_subscription(self.conn, 999, "monthly", "349.90")
        users.remove_user(self.conn, self.user_id)
        with self.assertRaises(AppError):
            self.create()

    def test_invalid_prices(self):
        for price in ("0.00", "-1.00", "349,90", "1.001", "NaN", "inf", "1e2", "", " 1.00", "1", "1.0", None, 349.9, "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:30]):
                with self.assertRaises(AppError) as error:
                    self.create(price=price)
                self.assertEqual(error.exception.code, "bad_price")
        self.assertEqual(self.report(), "0.00")

    def test_large_totals_use_integer_arithmetic(self):
        self.create(price="92233720368547758.07")
        self.create(price="92233720368547758.07")
        self.assertEqual(self.report(), "184467440737095516.14")

    def test_empty_period(self):
        self.assertEqual(self.report(), "0.00")
        self.create()
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-03-01", "2026-03-01"), "0.00")

    def test_invalid_dates_and_period(self):
        for start, end in (("2026-02-30", "2026-04-01"), ("2026-3-01", "2026-04-01"), ("2026-03-01", "bad"), (None, "2026-04-01"), ("2026-04-01", "2026-03-01")):
            with self.subTest(start=start, end=end):
                with self.assertRaises(AppError):
                    subscriptions.revenue_report(self.conn, start, end)
