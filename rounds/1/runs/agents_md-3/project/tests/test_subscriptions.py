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

    def create(self, price="349.90", moment="2026-06-01T00:00:00+00:00"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def report(self):
        return subscriptions.revenue_report(self.conn, "2026-06-01", "2026-07-01")

    def test_creation_and_exact_revenue(self):
        first = self.create()
        second = self.create()
        self.assertNotEqual(first, second)
        row = db.find_subscription(self.conn, first)
        self.assertEqual(row["price_kop"], 34990)
        self.assertEqual(row["plan"], "monthly")
        self.assertEqual(row["user_id"], self.user_id)
        self.assertEqual(row["created_at"], "2026-06-01T00:00:00+00:00")
        self.assertEqual(self.report(), "699.80")

    def test_cancellation_is_soft_and_idempotent(self):
        subscription_id = self.create()
        self.create("0.01")
        moment = datetime(2026, 6, 2, tzinfo=timezone.utc)
        with patch("app.clock.utc_now", return_value=moment):
            subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        row = db.find_subscription(self.conn, subscription_id)
        self.assertEqual(row["cancelled_at"], "2026-06-02T00:00:00+00:00")
        self.assertEqual(self.report(), "0.01")

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
        for price in ("", "349", "349.9", "1.001", "-1.00", "0.00", "NaN", "1e2",
                      " 1.00", "1,00", "١.00", None, "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:30]):
                with self.assertRaises(AppError) as caught:
                    self.create(price)
                self.assertEqual(caught.exception.code, "bad_price")
        self.assertEqual(self.report(), "0.00")

    def test_half_open_period_and_utc(self):
        self.create("1.00", "2026-05-31T23:59:59+00:00")
        self.create("2.00", "2026-06-01T00:00:00+00:00")
        self.create("4.00", "2026-06-30T23:59:59+00:00")
        self.create("8.00", "2026-07-01T00:00:00+00:00")
        self.create("16.00", "2026-06-01T02:00:00+03:00")
        self.assertEqual(self.report(), "6.00")

    def test_empty_period(self):
        self.assertEqual(self.report(), "0.00")
        self.create()
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-06-01", "2026-06-01"), "0.00")

    def test_invalid_dates_and_period(self):
        for value in ("2026-02-30", "2026-6-01", "20260601", "0000-01-01", "bad", None):
            for start, end in ((value, "2026-07-01"), ("2026-06-01", value)):
                with self.subTest(start=start, end=end):
                    with self.assertRaises(AppError):
                        subscriptions.revenue_report(self.conn, start, end)
        with self.assertRaises(AppError):
            subscriptions.revenue_report(self.conn, "2026-07-01", "2026-06-01")

    def test_large_total_and_leading_zeroes(self):
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.create("0000.01")
        self.assertEqual(self.report(), "184467440737095516.15")

    def test_migrations_can_be_applied_again(self):
        subscription_id = self.create()
        db.apply_migrations(self.conn)
        self.assertIsNotNone(db.find_subscription(self.conn, subscription_id))
        self.assertEqual(self.report(), "349.90")
