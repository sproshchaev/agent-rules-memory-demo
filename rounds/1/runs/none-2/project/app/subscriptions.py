"""Subscriptions and revenue from their creation, with dates interpreted in UTC."""

import re
from datetime import date

from app.clock import to_iso, utc_now
from app.errors import AppError
from app.users import get_user


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> int:
    get_user(conn, user_id)
    if not isinstance(price_rub, str) or re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub) is None:
        raise AppError("bad_price", "Цена должна быть положительной суммой с двумя знаками после точки")
    # SQLite stores signed 64-bit integers. Check before converting untrusted text.
    digits = price_rub.replace(".", "").lstrip("0") or "0"
    if len(digits) > 19 or (len(digits) == 19 and digits > "9223372036854775807"):
        raise AppError("bad_price", "Цена слишком велика")
    kopecks = int(digits)
    if kopecks <= 0:
        raise AppError("bad_price", "Цена должна быть положительной")
    cur = conn.execute(
        "INSERT INTO subscriptions (user_id, plan, price_kopecks, created_at) VALUES (?, ?, ?, ?)",
        (user_id, plan, kopecks, to_iso(utc_now())),
    )
    conn.commit()
    return cur.lastrowid


def cancel_subscription(conn, subscription_id: int) -> None:
    row = conn.execute("SELECT id FROM subscriptions WHERE id = ?", (subscription_id,)).fetchone()
    if row is None:
        raise AppError("subscription_not_found", f"Подписка {subscription_id} не найдена")
    conn.execute(
        "UPDATE subscriptions SET cancelled_at = ? WHERE id = ? AND cancelled_at IS NULL",
        (to_iso(utc_now()), subscription_id),
    )
    conn.commit()


def _parse_date(value: str) -> date:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise AppError("bad_date", "Дата должна иметь формат YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise AppError("bad_date", "Некорректная дата") from exc


def revenue_report(conn, date_from: str, date_to: str) -> str:
    """Sum creation prices in [date_from, date_to), excluding all cancellations."""
    if _parse_date(date_from) > _parse_date(date_to):
        raise AppError("bad_date_range", "Начало периода позже конца")
    rows = conn.execute(
        "SELECT price_kopecks FROM subscriptions "
        "WHERE created_at >= ? AND created_at < ? AND cancelled_at IS NULL",
        (date_from + "T00:00:00+00:00", date_to + "T00:00:00+00:00"),
    )
    # Python integers also allow reports whose total exceeds SQLite's integer range.
    total = sum(row["price_kopecks"] for row in rows)
    return f"{total // 100}.{total % 100:02d}"
