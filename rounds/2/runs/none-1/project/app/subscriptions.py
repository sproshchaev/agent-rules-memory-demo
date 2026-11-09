"""Подписки с точным учетом стоимости в копейках и датами в UTC."""

import re
from datetime import date
from uuid import uuid4

from app.clock import to_iso, utc_now
from app.errors import AppError
from app.users import get_user


def _price_kopecks(price_rub: str) -> int:
    if not isinstance(price_rub, str) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]{1,2})?", price_rub
    ):
        raise AppError("bad_price", "Некорректная цена подписки")
    whole, _, fraction = price_rub.partition(".")
    # Bound the value before converting to an SQLite signed 64-bit integer.
    digits = (whole + fraction.ljust(2, "0")).lstrip("0") or "0"
    if len(digits) > 19 or (len(digits) == 19 and digits > "9223372036854775807"):
        raise AppError("bad_price", "Цена подписки слишком велика")
    value = int(digits)
    if value <= 0:
        raise AppError("bad_price", "Цена подписки должна быть положительной")
    return value


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> str:
    price = _price_kopecks(price_rub)
    get_user(conn, user_id)
    subscription_id = str(uuid4())
    with conn:
        conn.execute(
            "INSERT INTO subscriptions (id, user_id, plan, price_kopecks, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (subscription_id, user_id, plan, price, to_iso(utc_now())),
        )
    return subscription_id


def cancel_subscription(conn, subscription_id: str) -> None:
    with conn:
        cursor = conn.execute(
            "UPDATE subscriptions SET cancelled_at = COALESCE(cancelled_at, ?) WHERE id = ?",
            (to_iso(utc_now()), subscription_id),
        )
        if cursor.rowcount == 0:
            raise AppError("subscription_not_found", "Подписка не найдена")


def _date_boundary(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise AppError("bad_date", "Ожидается дата в формате YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise AppError("bad_date", "Некорректная дата") from exc
    return value + "T00:00:00+00:00"


def revenue_report(conn, date_from: str, date_to: str) -> str:
    start, end = _date_boundary(date_from), _date_boundary(date_to)
    if start > end:
        raise AppError("bad_period", "Начало периода позже его конца")
    rows = conn.execute(
        "SELECT price_kopecks FROM subscriptions "
        "WHERE created_at >= ? AND created_at < ? AND cancelled_at IS NULL",
        (start, end),
    )
    # Python integers also keep reports exact when their total exceeds SQLite's range.
    total = sum(row["price_kopecks"] for row in rows)
    return f"{total // 100}.{total % 100:02d}"
