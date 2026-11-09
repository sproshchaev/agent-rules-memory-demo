"""Subscriptions and revenue from their creation prices (dates are UTC)."""

import re
from datetime import date

from app.clock import to_iso, utc_now
from app.errors import AppError
from app.users import get_user


def _price_kopecks(price_rub: str) -> int:
    if not isinstance(price_rub, str) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]{1,2})?", price_rub
    ):
        raise AppError("bad_price", "Некорректная цена подписки")
    rubles, _, fraction = price_rub.partition(".")
    # Check length before conversion, including arbitrarily long input strings.
    digits = (rubles + fraction.ljust(2, "0")).lstrip("0") or "0"
    if len(digits) > 19:
        raise AppError("bad_price", "Слишком большая цена подписки")
    amount = int(digits)
    if not 0 < amount <= 9223372036854775807:
        raise AppError("bad_price", "Цена подписки должна быть положительной и допустимой")
    return amount


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> int:
    amount = _price_kopecks(price_rub)
    get_user(conn, user_id)
    cur = conn.execute(
        "INSERT INTO subscriptions (user_id, plan, price_kopecks, created_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, plan, amount, to_iso(utc_now())),
    )
    conn.commit()
    return cur.lastrowid


def cancel_subscription(conn, subscription_id: int) -> None:
    row = conn.execute(
        "SELECT id FROM subscriptions WHERE id = ?", (subscription_id,)
    ).fetchone()
    if row is None:
        raise AppError("subscription_not_found", "Подписка не найдена")
    conn.execute(
        "UPDATE subscriptions SET cancelled_at = ? "
        "WHERE id = ? AND cancelled_at IS NULL",
        (to_iso(utc_now()), subscription_id),
    )
    conn.commit()


def revenue_report(conn, date_from: str, date_to: str) -> str:
    for value in (date_from, date_to):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise AppError("bad_date", "Дата должна иметь формат YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise AppError("bad_date", "Некорректная дата") from exc
    if date_from > date_to:
        raise AppError("bad_date_range", "Начало периода позже конца")
    rows = conn.execute(
        "SELECT price_kopecks FROM subscriptions "
        "WHERE created_at >= ? AND created_at < ? AND cancelled_at IS NULL",
        (date_from + "T00:00:00+00:00", date_to + "T00:00:00+00:00"),
    )
    # Python integers also support totals beyond SQLite's signed integer limit.
    total = sum(row["price_kopecks"] for row in rows)
    return f"{total // 100}.{total % 100:02d}"
