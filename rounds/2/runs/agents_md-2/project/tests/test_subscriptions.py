import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app import db, subscriptions, users
from app.errors import AppError


class SubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.addCleanup(self.conn.close)
        self.user_id = users.add_user(self.conn, 'anna@example.com')

    def create(self, price='349.90', at='2026-02-10T12:00:00+00:00', plan='monthly'):
        with patch('app.clock.utc_now', return_value=datetime.fromisoformat(at)):
            return subscriptions.create_subscription(self.conn, self.user_id, plan, price)

    def report(self):
        return subscriptions.revenue_report(self.conn, '2026-02-01', '2026-03-01')

    def test_create_and_exact_revenue(self):
        subscription_id = self.create(plan="monthly ' special")
        self.assertEqual(str(uuid.UUID(subscription_id)), subscription_id)
        row = db.find_subscription(self.conn, subscription_id)
        self.assertEqual(row['price_kop'], 34990)
        self.assertEqual(row['plan'], "monthly ' special")
        self.assertEqual(row['status'], 'active')
        self.assertEqual(row['created_at'], '2026-02-10T12:00:00+00:00')
        self.create()
        self.assertEqual(self.report(), '699.80')

    def test_bad_prices(self):
        for price in ('0.00', '-1.00', '1.001', '1', '1.2', '1,00', ' 1.00',
                      'NaN', 'inf', '1e2', '', '１.00', None,
                      '92233720368547758.08', '9' * 5000 + '.00'):
            with self.subTest(price=price):
                with self.assertRaises(AppError) as caught:
                    self.create(price)
                self.assertEqual(caught.exception.code, 'SUB_BAD_PRICE')
        self.assertEqual(self.report(), '0.00')

    def test_unknown_and_deleted_users(self):
        for user_id in (999, self.user_id):
            if user_id == self.user_id:
                users.remove_user(self.conn, user_id)
            with self.assertRaises(AppError) as caught:
                subscriptions.create_subscription(self.conn, user_id, 'monthly', '1.00')
            self.assertEqual(caught.exception.code, 'SUB_USER_NOT_FOUND')

    def test_cancel_and_audit(self):
        subscription_id = self.create()
        subscriptions.cancel_subscription(self.conn, subscription_id)
        subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)['status'], 'cancelled')
        self.assertEqual(self.report(), '0.00')
        rows = self.conn.execute('SELECT * FROM audit_log ORDER BY id').fetchall()
        self.assertEqual([(r['entity'], r['entity_id'], r['action']) for r in rows], [
            ('subscription', subscription_id, 'created'),
            ('subscription', subscription_id, 'cancelled'),
        ])
        for row in rows:
            self.assertEqual(datetime.fromisoformat(row['at']).tzinfo, timezone.utc)
        with self.assertRaises(AppError) as caught:
            subscriptions.cancel_subscription(self.conn, 'missing')
        self.assertEqual(caught.exception.code, 'SUB_NOT_FOUND')

    def test_half_open_period_and_utc(self):
        self.create('1.00', '2026-01-31T23:59:59+00:00')
        self.create('2.00', '2026-02-01T00:00:00+00:00')
        self.create('4.00', '2026-02-28T23:59:59+00:00')
        self.create('8.00', '2026-03-01T00:00:00+00:00')
        self.create('16.00', '2026-02-01T01:00:00+05:00')
        self.assertEqual(self.report(), '6.00')
        self.assertEqual(subscriptions.revenue_report(self.conn, '2026-02-01', '2026-02-01'), '0.00')

    def test_bad_dates_and_period(self):
        for value in ('2026-02-30', '2026-2-01', '2026-01-01T00:00:00', '', None):
            for start, end in ((value, '2026-03-01'), ('2026-02-01', value)):
                with self.subTest(start=start, end=end):
                    with self.assertRaises(AppError) as caught:
                        subscriptions.revenue_report(self.conn, start, end)
                    self.assertEqual(caught.exception.code, 'SUB_BAD_DATE')
        with self.assertRaises(AppError) as caught:
            subscriptions.revenue_report(self.conn, '2026-03-01', '2026-02-01')
        self.assertEqual(caught.exception.code, 'SUB_BAD_PERIOD')

    def test_large_totals_and_small_prices(self):
        self.create('92233720368547758.07')
        self.create('92233720368547758.07')
        self.create('0.01')
        self.assertEqual(self.report(), '184467440737095516.15')

    def test_audit_failure_rolls_back_changes(self):
        with patch('app.db.add_audit', side_effect=AppError('TEST_FAILURE', 'audit unavailable')):
            with self.assertRaises(AppError):
                self.create()
        self.assertEqual(self.report(), '0.00')
        subscription_id = self.create()
        with patch('app.db.add_audit', side_effect=AppError('TEST_FAILURE', 'audit unavailable')):
            with self.assertRaises(AppError):
                subscriptions.cancel_subscription(self.conn, subscription_id)
        self.assertEqual(db.find_subscription(self.conn, subscription_id)['status'], 'active')
