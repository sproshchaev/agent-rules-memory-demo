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

    def create(self, moment="2026-02-01T00:00:00+00:00", price="349.90"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01")

    def test_creation_and_exact_total(self):
        first = self.create()
        second = self.create()
        self.assertNotEqual(first, second)
        self.assertEqual(self.report(), "699.80")
        self.create(price="0.01")
        self.assertEqual(self.report(), "699.81")

    def test_invalid_prices(self):
        for price in ("0.00", "-1.00", "1", "1.0", "1.001", "1,00", " 1.00",
                      "1e2", "NaN", "١.00", None, 349.90,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:30]), self.assertRaises(AppError) as error:
                self.create(price=price)
            self.assertEqual(error.exception.code, "bad_price")
        self.assertEqual(self.report(), "0.00")

    def test_missing_and_deleted_user(self):
        for user_id in (self.user_id + 1, self.user_id):
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError) as error:
                subscriptions.create_subscription(self.conn, user_id, "monthly", "349.90")
            self.assertEqual(error.exception.code, "user_not_found")

    def test_cancel_is_idempotent_and_excluded(self):
        cancelled = self.create()
        self.create()
        subscriptions.cancel_subscription(self.conn, cancelled)
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(self.report(), "349.90")
        self.assertIsNotNone(db.find_subscription(self.conn, cancelled))

    def test_cancel_missing(self):
        with self.assertRaises(AppError) as error:
            subscriptions.cancel_subscription(self.conn, 123)
        self.assertEqual(error.exception.code, "subscription_not_found")

    def test_half_open_period_and_utc(self):
        self.create("2026-01-31T23:59:59+00:00")
        self.create("2026-02-01T03:00:00+03:00")
        self.create("2026-02-28T23:59:59+00:00")
        self.create("2026-03-01T00:00:00+00:00")
        self.assertEqual(self.report(), "699.80")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-02-01"), "0.00")

    def test_invalid_dates_and_period(self):
        for start, end in (("2026-02-30", "2026-03-01"), ("2026-2-01", "2026-03-01"),
                           ("2026-02-01", "bad"), (None, "2026-03-01"),
                           ("2026-03-01", "2026-02-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_report_survives_user_removal(self):
        self.create()
        users.remove_user(self.conn, self.user_id)
        self.assertEqual(self.report(), "349.90")

    def test_large_totals_use_integer_arithmetic(self):
        self.create(price="92233720368547758.07")
        self.create(price="92233720368547758.07")
        self.assertEqual(self.report(), "184467440737095516.14")
