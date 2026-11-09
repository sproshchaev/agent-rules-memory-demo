import unittest

from app import db, users
from app.errors import AppError


class UsersTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()

    def test_add_and_get(self):
        user_id = users.add_user(self.conn, " Anna@Example.com ")
        self.assertEqual(users.get_user(self.conn, user_id)["email"], "anna@example.com")

    def test_bad_email(self):
        with self.assertRaises(AppError):
            users.add_user(self.conn, "anna")

    def test_removed_user_is_hidden(self):
        user_id = users.add_user(self.conn, "anna@example.com")
        users.remove_user(self.conn, user_id)
        with self.assertRaises(AppError):
            users.get_user(self.conn, user_id)


if __name__ == "__main__":
    unittest.main()
