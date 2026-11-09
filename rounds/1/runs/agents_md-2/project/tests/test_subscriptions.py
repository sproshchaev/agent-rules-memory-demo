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

    def create(self, price="349.90", moment="2026-04-10T12:00:00+00:00"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-04-01", "2026-05-01")

    def test_creation_and_exact_revenue(self):
        first = self.create()
        second = self.create()
        self.assertIsInstance(first, int)
        self.assertNotEqual(first, second)
        self.assertEqual(self.report(), "699.80")
        self.create("0.01")
        self.assertEqual(self.report(), "699.81")

    def test_invalid_prices(self):
        for price in ("", "349,90", "349.9", "349.900", "-1.00", "0.00",
                      "NaN", " 349.90", "1e2", "1", None, 349.90,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:50]):
                with self.assertRaises(AppError) as caught:
                    self.create(price)
                self.assertEqual(caught.exception.code, "bad_price")
        self.assertEqual(self.report(), "0.00")

    def test_missing_and_deleted_users(self):
        with self.assertRaises(AppError) as caught:
            subscriptions.create_subscription(self.conn, 999, "monthly", "349.90")
        self.assertEqual(caught.exception.code, "user_not_found")
        users.remove_user(self.conn, self.user_id)
        with self.assertRaises(AppError):
            self.create()

    def test_cancellation_is_persistent_and_idempotent(self):
        subscription_id = self.create()
        self.create("10.01")
        moment = datetime(2026, 5, 10, tzinfo=timezone.utc)
        with patch("app.clock.utc_now", return_value=moment):
            subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)["cancelled_at"],
                         "2026-05-10T00:00:00+00:00")
        self.assertEqual(self.report(), "10.01")

    def test_cancel_missing_subscription(self):
        with self.assertRaises(AppError) as caught:
            subscriptions.cancel_subscription(self.conn, 999)
        self.assertEqual(caught.exception.code, "subscription_not_found")

    def test_half_open_utc_period(self):
        self.create("1.00", "2026-03-31T23:59:59+00:00")
        self.create("2.00", "2026-04-01T00:00:00+00:00")
        self.create("4.00", "2026-04-30T23:59:59+00:00")
        self.create("8.00", "2026-05-01T00:00:00+00:00")
        self.create("16.00", "2026-04-01T02:00:00+03:00")
        self.assertEqual(self.report(), "6.00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-04-01", "2026-04-01"), "0.00")

    def test_invalid_dates_and_period(self):
        for value in ("2026-02-30", "2026-4-01", "0000-01-01", "2026-04-01T00:00:00", None):
            for start, end in ((value, "2026-05-01"), ("2026-04-01", value)):
                with self.subTest(start=start, end=end):
                    with self.assertRaises(AppError):
                        subscriptions.revenue_report(self.conn, start, end)
        with self.assertRaises(AppError):
            subscriptions.revenue_report(self.conn, "2026-05-01", "2026-04-01")

    def test_large_integer_totals(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(self.report(), "184467440737095516.14")

    def test_migrations_can_be_reapplied(self):
        self.create()
        db.apply_migrations(self.conn)
        self.assertEqual(self.report(), "349.90")
