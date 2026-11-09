"""Subscriptions and revenue for their UTC creation dates."""

import re
from datetime import date

from app import users
from app.clock import to_iso, utc_now
from app.errors import AppError


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> int:
    users.get_user(conn, user_id)
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("bad_price", "Цена должна иметь формат 349.90")
    rubles, kopecks = price_rub.split(".")
    # Bound the input before conversion to avoid oversized integers and SQLite overflow.
    rubles = rubles.lstrip("0") or "0"
    if len(rubles) > 17:
        raise AppError("bad_price", "Цена слишком велика")
    price = int(rubles) * 100 + int(kopecks)
    if not 0 < price <= 2**63 - 1:
        raise AppError("bad_price", "Цена должна быть положительной и помещаться в базу")
    cur = conn.execute(
        "INSERT INTO subscriptions (user_id, plan, price_kopecks, created_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, plan, price, to_iso(utc_now())),
    )
    conn.commit()
    return cur.lastrowid


def cancel_subscription(conn, subscription_id: int) -> None:
    cur = conn.execute(
        "UPDATE subscriptions SET cancelled_at = COALESCE(cancelled_at, ?) WHERE id = ?",
        (to_iso(utc_now()), subscription_id),
    )
    if cur.rowcount == 0:
        raise AppError("subscription_not_found", f"Подписка {subscription_id} не найдена")
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
    total = sum(row["price_kopecks"] for row in rows)
    return f"{total // 100}.{total % 100:02d}"
