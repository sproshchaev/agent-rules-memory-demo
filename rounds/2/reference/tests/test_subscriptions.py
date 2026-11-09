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

    def test_changes_are_audited(self):
        sub_id = subscriptions.create_subscription(self.conn, self.user_id, "basic", "1.00")
        subscriptions.cancel_subscription(self.conn, sub_id)
        actions = [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? ORDER BY id", (sub_id,))]
        self.assertEqual(actions, ["created", "cancelled"])

    def test_cancel_twice(self):
        sub_id = subscriptions.create_subscription(self.conn, self.user_id, "basic", "1.00")
        subscriptions.cancel_subscription(self.conn, sub_id)
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, sub_id)


if __name__ == "__main__":
    unittest.main()
