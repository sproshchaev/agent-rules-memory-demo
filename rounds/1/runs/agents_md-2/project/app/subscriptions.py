import re
from datetime import date, datetime, timezone

from app import clock, db, users
from app.errors import AppError


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> int:
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("bad_price", "Цена должна иметь формат 349.90")
    rub, kop = price_rub.split(".")
    # Bound the input before int conversion, including unusually long strings.
    rub = rub.lstrip("0") or "0"
    if len(rub) > 17:
        raise AppError("bad_price", "Цена слишком велика")
    price_kop = int(rub) * 100 + int(kop)
    if not 0 < price_kop <= 9223372036854775807:
        raise AppError("bad_price", "Цена должна быть положительной и помещаться в INTEGER")
    users.get_user(conn, user_id)
    return db.insert_subscription(conn, user_id, plan, price_kop, clock.to_iso(clock.utc_now()))


def cancel_subscription(conn, subscription_id: int) -> None:
    if db.find_subscription(conn, subscription_id) is None:
        raise AppError("subscription_not_found", f"Подписка {subscription_id} не найдена")
    db.mark_subscription_cancelled(conn, subscription_id, clock.to_iso(clock.utc_now()))


def _date_boundary(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise AppError("bad_date", "Дата должна иметь формат YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise AppError("bad_date", f"Некорректная дата: {value}") from None
    return clock.to_iso(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))


def revenue_report(conn, date_from: str, date_to: str) -> str:
    start, end = _date_boundary(date_from), _date_boundary(date_to)
    if start > end:
        raise AppError("bad_period", "Начало периода позже конца")
    # Sum in Python to allow totals larger than SQLite's INTEGER range.
    total = sum(row["price_kop"] for row in db.subscription_prices_for_period(conn, start, end))
    return f"{total // 100}.{total % 100:02d}"
