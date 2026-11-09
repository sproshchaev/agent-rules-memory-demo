import unittest

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.user_id = users.add_user(self.conn, "anna@example.com")

    def audit_actions(self, entity_id: str) -> list:
        return [r["action"] for r in self.conn.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? ORDER BY id", (entity_id,))]

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
        self.assertEqual(self.audit_actions(sub_id), ["created", "cancelled"])

    def test_cancel_twice(self):
        sub_id = subscriptions.create_subscription(self.conn, self.user_id, "basic", "1.00")
        subscriptions.cancel_subscription(self.conn, sub_id)
        with self.assertRaises(AppError):
            subscriptions.cancel_subscription(self.conn, sub_id)

    def test_cancel_unknown_is_not_audited(self):
        with self.assertRaises(AppError) as ctx:
            subscriptions.cancel_subscription(self.conn, "no-such-id")
        self.assertEqual(ctx.exception.code, "SUB_NOT_FOUND")
        self.assertEqual(self.audit_actions("no-such-id"), [])


if __name__ == "__main__":
    unittest.main()
