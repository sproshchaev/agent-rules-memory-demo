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

    def create(self, price="349.90", moment="2026-02-01T00:00:00+00:00"):
        with patch("app.clock.utc_now", return_value=datetime.fromisoformat(moment)):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def test_create_stores_kopecks_and_utc_time(self):
        subscription_id = self.create(moment="2026-02-01T03:00:00+03:00")
        row = db.find_subscription(self.conn, subscription_id)
        self.assertEqual(row["user_id"], self.user_id)
        self.assertEqual(row["plan"], "monthly")
        self.assertEqual(row["price_kop"], 34990)
        self.assertIsInstance(row["price_kop"], int)
        self.assertEqual(row["created_at"], "2026-02-01T00:00:00+00:00")

    def test_report_period_boundaries(self):
        self.create(moment="2026-01-31T23:59:59+00:00")
        self.create()
        self.create(moment="2026-02-28T23:59:59+00:00")
        self.create(moment="2026-03-01T00:00:00+00:00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"), "699.80")

    def test_cancel_is_idempotent_and_excluded_from_report(self):
        subscription_id = self.create()
        moment = datetime(2026, 3, 1, tzinfo=timezone.utc)
        with patch("app.clock.utc_now", return_value=moment):
            subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        row = db.find_subscription(self.conn, subscription_id)
        self.assertEqual(row["cancelled_at"], "2026-03-01T00:00:00+00:00")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"), "0.00")

    def test_missing_subscription(self):
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, 999)

    def test_missing_and_deleted_users(self):
        users.remove_user(self.conn, self.user_id)
        for user_id in (999, self.user_id):
            with self.assertRaises(AppError):
                subscriptions.create_subscription(self.conn, user_id, "monthly", "349.90")

    def test_invalid_prices(self):
        for price in ("0.00", "-1.00", "349,90", "349.9", "349", "1.001", "NaN", " 1.00", "1e2", "١.00", None, 349.90, "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:30]), self.assertRaises(AppError):
                self.create(price)

    def test_exact_arithmetic_and_large_totals(self):
        self.create("0.10")
        self.create("0.20")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"), "0.30")
        self.create("92233720368547758.07")
        self.create("92233720368547758.07")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"), "184467440737095516.44")

    def test_empty_and_invalid_periods(self):
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-02-01"), "0.00")
        for start, end in (("2026-02-30", "2026-03-01"), ("2026-2-01", "2026-03-01"), (None, "2026-03-01"), ("2026-03-01", "2026-02-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)


if __name__ == "__main__":
    unittest.main()
