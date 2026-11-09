import re
from datetime import date

from app import clock, db, users
from app.errors import AppError


def _price_kop(price_rub: str) -> int:
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("bad_price", "Цена должна быть положительной суммой вида 349.90")
    digits = price_rub.replace(".", "").lstrip("0")
    if not digits or len(digits) > 19 or (
        len(digits) == 19 and digits > "9223372036854775807"
    ):
        raise AppError("bad_price", "Цена вне допустимого диапазона")
    return int(digits)


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> int:
    price_kop = _price_kop(price_rub)
    users.get_user(conn, user_id)
    return db.insert_subscription(conn, user_id, plan, price_kop, clock.to_iso(clock.utc_now()))


def cancel_subscription(conn, subscription_id: int) -> None:
    if db.find_subscription(conn, subscription_id) is None:
        raise AppError("subscription_not_found", f"Подписка {subscription_id} не найдена")
    db.mark_subscription_cancelled(conn, subscription_id, clock.to_iso(clock.utc_now()))


def _report_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise AppError("bad_date", "Дата должна иметь формат YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise AppError("bad_date", "Некорректная дата") from None
    return value + "T00:00:00+00:00"


def revenue_report(conn, date_from: str, date_to: str) -> str:
    start, end = _report_date(date_from), _report_date(date_to)
    if start > end:
        raise AppError("bad_period", "Начало периода позже конца")
    total = db.subscription_revenue_kop(conn, start, end)
    return f"{total // 100}.{total % 100:02d}"
