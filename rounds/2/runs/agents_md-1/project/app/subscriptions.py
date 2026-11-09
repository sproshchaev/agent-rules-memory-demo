import re
import uuid
from datetime import date

from app import clock, db
from app.errors import AppError
from app.log import get_logger

log = get_logger(__name__)


def _price_kop(price_rub: str) -> int:
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("SUB_BAD_PRICE", "Цена должна иметь формат 349.90")
    rub, kop = price_rub.split(".")
    rub = rub.lstrip("0") or "0"
    if len(rub) > 17:
        raise AppError("SUB_BAD_PRICE", "Цена слишком велика")
    price = int(rub) * 100 + int(kop)
    if not 0 < price <= 9223372036854775807:
        raise AppError("SUB_BAD_PRICE", "Цена должна быть положительной и помещаться в INTEGER")
    return price


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> str:
    price = _price_kop(price_rub)
    if db.find_user(conn, user_id) is None:
        raise AppError("SUB_USER_NOT_FOUND", f"Пользователь {user_id} не найден")
    subscription_id = str(uuid.uuid4())
    with conn:
        db.insert_subscription(conn, subscription_id, user_id, plan, price,
                               clock.to_iso(clock.utc_now()))
        db.add_audit(conn, "subscription", subscription_id, "created",
                     clock.to_iso(clock.utc_now()))
    log.info("event=subscription_created id=%s user_id=%s", subscription_id, user_id)
    return subscription_id


def cancel_subscription(conn, subscription_id: str) -> None:
    row = db.find_subscription(conn, subscription_id)
    if row is None:
        raise AppError("SUB_NOT_FOUND", f"Подписка {subscription_id} не найдена")
    if row["status"] == "cancelled":
        return
    with conn:
        db.cancel_subscription(conn, subscription_id)
        db.add_audit(conn, "subscription", subscription_id, "cancelled",
                     clock.to_iso(clock.utc_now()))
    log.info("event=subscription_cancelled id=%s", subscription_id)


def _report_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise AppError("SUB_BAD_DATE", "Дата должна иметь формат YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise AppError("SUB_BAD_DATE", f"Некорректная дата: {value}") from None
    return value + "T00:00:00+00:00"


def revenue_report(conn, date_from: str, date_to: str) -> str:
    start, end = _report_date(date_from), _report_date(date_to)
    if start > end:
        raise AppError("SUB_BAD_PERIOD", "Начало периода позже конца")
    total = sum(db.subscription_prices(conn, start, end))
    return f"{total // 100}.{total % 100:02d}"
