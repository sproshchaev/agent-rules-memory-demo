import re
from datetime import date
from uuid import uuid4

from app.clock import to_iso, utc_now
from app.errors import AppError
from app.users import get_user


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> str:
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("bad_price", "Цена должна быть положительной суммой в формате 349.90")
    rubles, kopecks = price_rub.split(".")
    # Bound the input before conversion, including arbitrarily long strings.
    rubles = rubles.lstrip("0") or "0"
    if len(rubles) > 17:
        raise AppError("bad_price", "Цена слишком велика")
    price = int(rubles) * 100 + int(kopecks)
    if not 0 < price <= 2**63 - 1:
        raise AppError("bad_price", "Цена вне допустимого диапазона")
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


def revenue_report(conn, date_from: str, date_to: str) -> str:
    for value in (date_from, date_to):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise AppError("bad_date", "Дата должна быть в формате YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise AppError("bad_date", "Некорректная дата") from exc
    if date_from > date_to:
        raise AppError("bad_period", "Начало периода позже конца")
    rows = conn.execute(
        "SELECT price_kopecks FROM subscriptions "
        "WHERE created_at >= ? AND created_at < ? AND cancelled_at IS NULL",
        (date_from + "T00:00:00+00:00", date_to + "T00:00:00+00:00"),
    )
    total = sum(row["price_kopecks"] for row in rows)
    return f"{total // 100}.{total % 100:02d}"
