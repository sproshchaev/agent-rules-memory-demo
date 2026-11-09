import unittest

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.user_id = users.add_user(self.conn, "anna@example.com")

    def test_price_is_parsed_to_kopecks(self):
        self.assertEqual(subscriptions.parse_price_kop("349.90"), 34990)
        self.assertEqual(subscriptions.parse_price_kop("349.9"), 34990)
        self.assertEqual(subscriptions.parse_price_kop("12"), 1200)

    def test_bad_price(self):
        with self.assertRaises(AppError):
            subscriptions.create_subscription(self.conn, self.user_id, "basic", "-1")

    def test_cancel_twice(self):
        sub_id = subscriptions.create_subscription(self.conn, self.user_id, "basic", "1.00")
        subscriptions.cancel_subscription(self.conn, sub_id)
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, sub_id)

    def test_cancel_unknown(self):
        with self.assertRaises(AppError) as ctx:
            subscriptions.cancel_subscription(self.conn, 999)
        self.assertEqual(ctx.exception.code, "subscription_not_found")


if __name__ == "__main__":
    unittest.main()
