"""Приемочный тест задачи. Агент его не видит: summarize.py и selftest.py кладут файл
в копию проекта уже после прогона."""
import unittest
from datetime import timedelta

from app import db, subscriptions, users
from app.clock import utc_now


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.user_id = users.add_user(self.conn, "anna@example.com")
        today = utc_now().date()
        self.date_from = (today - timedelta(days=1)).isoformat()
        self.date_to = (today + timedelta(days=1)).isoformat()

    def test_revenue_counts_active_subscriptions(self):
        subscriptions.create_subscription(self.conn, self.user_id, "basic", "349.90")
        subscriptions.create_subscription(self.conn, self.user_id, "basic", "349.90")
        cancelled = subscriptions.create_subscription(self.conn, self.user_id, "pro", "999.00")
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(
            subscriptions.revenue_report(self.conn, self.date_from, self.date_to), "699.80"
        )

    def test_cents_add_up_exactly(self):
        for _ in range(3):
            subscriptions.create_subscription(self.conn, self.user_id, "tip", "0.10")
        subscriptions.create_subscription(self.conn, self.user_id, "tip", "0.20")
        self.assertEqual(
            subscriptions.revenue_report(self.conn, self.date_from, self.date_to), "0.50"
        )

    def test_period_is_half_open(self):
        subscriptions.create_subscription(self.conn, self.user_id, "basic", "100.00")
        today = utc_now().date().isoformat()
        self.assertEqual(
            subscriptions.revenue_report(self.conn, self.date_from, today), "0.00"
        )

    def test_unknown_user_is_rejected(self):
        with self.assertRaises(Exception):
            subscriptions.create_subscription(self.conn, 999, "basic", "349.90")

    def test_bad_price_is_rejected(self):
        with self.assertRaises(Exception):
            subscriptions.create_subscription(self.conn, self.user_id, "basic", "дорого")


if __name__ == "__main__":
    unittest.main()
