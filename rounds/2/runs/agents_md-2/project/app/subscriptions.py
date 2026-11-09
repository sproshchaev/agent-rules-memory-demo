import re
import uuid
from datetime import date, datetime, timezone

from app import clock, db
from app.errors import AppError
from app.log import get_logger

log = get_logger(__name__)


def _price_kop(price_rub: str) -> int:
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("SUB_BAD_PRICE", "Цена должна быть суммой в рублях с двумя знаками после точки")
    rub, kop = price_rub.split(".")
    # SQLite INTEGER is a signed 64-bit value; check before converting long input.
    rub = rub.lstrip("0") or "0"
    if len(rub) > 17:
        raise AppError("SUB_BAD_PRICE", "Цена слишком велика")
    amount = int(rub) * 100 + int(kop)
    if not 0 < amount <= 9223372036854775807:
        raise AppError("SUB_BAD_PRICE", "Цена должна быть положительной и помещаться в INTEGER")
    return amount


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> str:
    amount = _price_kop(price_rub)
    if db.find_user(conn, user_id) is None:
        raise AppError("SUB_USER_NOT_FOUND", f"Пользователь {user_id} не найден")
    subscription_id = str(uuid.uuid4())
    at = clock.to_iso(clock.utc_now())
    with conn:
        db.insert_subscription(conn, subscription_id, user_id, plan, amount, at)
        db.add_audit(conn, "subscription", subscription_id, "created", clock.to_iso(clock.utc_now()))
    log.info("event=subscription_created id=%s user_id=%s", subscription_id, user_id)
    return subscription_id


def cancel_subscription(conn, subscription_id: str) -> None:
    with conn:
        row = db.find_subscription(conn, subscription_id)
        if row is None:
            raise AppError("SUB_NOT_FOUND", f"Подписка {subscription_id} не найдена")
        if not db.cancel_subscription(conn, subscription_id):
            return
        db.add_audit(conn, "subscription", subscription_id, "cancelled", clock.to_iso(clock.utc_now()))
    log.info("event=subscription_cancelled id=%s", subscription_id)


def _date_boundary(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise AppError("SUB_BAD_DATE", "Дата должна иметь формат YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise AppError("SUB_BAD_DATE", f"Некорректная дата: {value}") from None
    return clock.to_iso(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))


def revenue_report(conn, date_from: str, date_to: str) -> str:
    start, end = _date_boundary(date_from), _date_boundary(date_to)
    if start > end:
        raise AppError("SUB_BAD_PERIOD", "Начало периода должно быть не позже конца")
    amount = sum(db.subscription_prices(conn, start, end))
    return f"{amount // 100}.{amount % 100:02d}"
