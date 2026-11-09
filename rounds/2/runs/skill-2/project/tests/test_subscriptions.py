import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app import clock, db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.user_id = users.add_user(self.conn, "subscriber@example.com")

    def create_at(self, date, price="349.90"):
        moment = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
        with patch("app.clock.utc_now", return_value=moment):
            return subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)

    def test_creation_storage_and_audit(self):
        subscription_id = self.create_at("2026-02-01")
        self.assertEqual(str(uuid.UUID(subscription_id)), subscription_id)
        row = self.conn.execute("SELECT * FROM subscriptions").fetchone()
        self.assertEqual(row["user_id"], self.user_id)
        self.assertEqual(row["plan"], "monthly")
        self.assertEqual(row["price_kop"], 34990)
        self.assertEqual(row["status"], "active")
        audit = self.conn.execute("SELECT * FROM audit_log").fetchone()
        self.assertEqual((audit["entity"], audit["entity_id"], audit["action"]),
                         ("subscription", subscription_id, "created"))
        self.assertEqual(audit["at"], row["created_at"])

    def test_invalid_prices(self):
        for price in ("0.00", "-1.00", "349,90", "1", "1.1", "1.001", "NaN",
                      "Infinity", " 1.00", "1.00\n", "1e2", "", None, 349.90,
                      "92233720368547758.08", "9" * 5000 + ".00"):
            with self.subTest(price=str(price)[:40]):
                with self.assertRaises(AppError) as error:
                    subscriptions.create_subscription(self.conn, self.user_id, "monthly", price)
                self.assertEqual(error.exception.code, "SUB_BAD_PRICE")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0], 0)

    def test_missing_and_deleted_users(self):
        for user_id in (self.user_id + 1, self.user_id):
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError) as error:
                subscriptions.create_subscription(self.conn, user_id, "monthly", "349.90")
            self.assertEqual(error.exception.code, "SUB_USER_NOT_FOUND")

    def test_report_boundaries_and_cancel(self):
        self.create_at("2026-01-31T23:59:59.999999")
        self.create_at("2026-02-01")
        self.create_at("2026-02-28T23:59:59.999999")
        cancelled = self.create_at("2026-02-15")
        self.create_at("2026-03-01")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"), "1049.70")
        subscriptions.cancel_subscription(self.conn, cancelled)
        subscriptions.cancel_subscription(self.conn, cancelled)
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"), "699.80")
        self.assertEqual(db.find_subscription(self.conn, cancelled)["status"], "cancelled")
        audits = self.conn.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? ORDER BY id", (cancelled,)
        ).fetchall()
        self.assertEqual([row["action"] for row in audits], ["created", "cancelled"])

    def test_missing_subscription(self):
        with self.assertRaises(AppError) as error:
            subscriptions.cancel_subscription(self.conn, "missing")
        self.assertEqual(error.exception.code, "SUB_NOT_FOUND")

    def test_empty_and_invalid_periods(self):
        for start, end in (("2026-01-01", "2026-02-01"), ("2026-01-01", "2026-01-01")):
            self.assertEqual(subscriptions.revenue_report(self.conn, start, end), "0.00")
        for start, end in (("2026-02-30", "2026-03-01"), ("2026-1-01", "2026-03-01"),
                           ("2026-01-01", "bad"), (None, "2026-03-01"),
                           ("2026-03-01", "2026-02-01")):
            with self.subTest(start=start, end=end), self.assertRaises(AppError):
                subscriptions.revenue_report(self.conn, start, end)

    def test_exact_money_and_large_total(self):
        self.create_at("2026-02-01", "0.01")
        self.create_at("2026-02-01", "0.09")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"), "0.10")
        for _ in range(2):
            self.create_at("2026-02-01", "92233720368547758.07")
        self.assertEqual(subscriptions.revenue_report(self.conn, "2026-02-01", "2026-03-01"),
                         "184467440737095516.24")

    def test_failed_audit_rolls_back_changes(self):
        with patch("app.db.add_audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                self.create_at("2026-02-01")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], 0)
        subscription_id = self.create_at("2026-02-01")
        with patch("app.db.add_audit", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaises(RuntimeError):
                subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)["status"], "active")

    def test_clock_normalizes_to_utc(self):
        from datetime import timedelta
        moment = datetime(2026, 2, 1, 3, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(clock.to_iso(moment), "2026-02-01T00:00:00.000000+00:00")
        self.assertEqual(clock.utc_now().tzinfo, timezone.utc)
