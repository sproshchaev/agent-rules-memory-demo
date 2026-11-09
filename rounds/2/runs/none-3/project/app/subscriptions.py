import re
from datetime import date
from uuid import uuid4

from app.clock import to_iso, utc_now
from app.errors import AppError
from app.users import get_user


def _price_kopecks(price_rub: str) -> int:
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("bad_price", "Цена должна быть строкой вида 349.90")
    digits = price_rub.replace(".", "").lstrip("0")
    # SQLite stores signed 64-bit integers.
    if not digits or len(digits) > 19 or int(digits) > 2**63 - 1:
        raise AppError("bad_price", "Цена должна быть положительной и помещаться в БД")
    return int(digits)


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


def _date_boundary(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise AppError("bad_date", "Дата должна быть в формате YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise AppError("bad_date", "Некорректная дата") from exc
    return value + "T00:00:00+00:00"


def revenue_report(conn, date_from: str, date_to: str) -> str:
    start, end = _date_boundary(date_from), _date_boundary(date_to)
    if start > end:
        raise AppError("bad_date_range", "Начало периода позже конца")
    # Sum in Python so a valid total can exceed SQLite's integer range.
    total = sum(
        row["price_kopecks"]
        for row in conn.execute(
            "SELECT price_kopecks FROM subscriptions "
            "WHERE created_at >= ? AND created_at < ? AND cancelled_at IS NULL",
            (start, end),
        )
    )
    return f"{total // 100}.{total % 100:02d}"
