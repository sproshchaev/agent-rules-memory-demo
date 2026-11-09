import re
import uuid
from datetime import date

from app import clock, db
from app.errors import AppError
from app.log import get_logger

log = get_logger(__name__)


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> str:
    if not isinstance(price_rub, str) or not re.fullmatch(r"[0-9]+\.[0-9]{2}", price_rub):
        raise AppError("SUB_BAD_PRICE", "Цена должна иметь формат 349.90")
    digits = price_rub.replace(".", "").lstrip("0")
    if len(digits) > 19:
        raise AppError("SUB_BAD_PRICE", "Цена слишком велика")
    price_kop = int(digits or "0")
    if not 0 < price_kop <= 9223372036854775807:
        raise AppError("SUB_BAD_PRICE", "Цена должна быть положительной и помещаться в INTEGER")
    if db.find_user(conn, user_id) is None:
        raise AppError("SUB_USER_NOT_FOUND", f"Пользователь {user_id} не найден")
    subscription_id = str(uuid.uuid4())
    with conn:
        db.insert_subscription(
            conn, subscription_id, user_id, plan, price_kop, clock.to_iso(clock.utc_now())
        )
        db.add_audit(conn, "subscription", subscription_id, "created", clock.to_iso(clock.utc_now()))
    log.info("event=subscription_created id=%s user_id=%s", subscription_id, user_id)
    return subscription_id


def cancel_subscription(conn, subscription_id: str) -> None:
    row = db.find_subscription(conn, subscription_id)
    if row is None:
        raise AppError("SUB_NOT_FOUND", f"Подписка {subscription_id} не найдена")
    if row["status"] == "cancelled":
        return
    with conn:
        db.mark_subscription_cancelled(conn, subscription_id)
        db.add_audit(conn, "subscription", subscription_id, "cancelled", clock.to_iso(clock.utc_now()))
    log.info("event=subscription_cancelled id=%s", subscription_id)


def revenue_report(conn, date_from: str, date_to: str) -> str:
    for value in (date_from, date_to):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise AppError("SUB_BAD_DATE", "Дата должна иметь формат YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError:
            raise AppError("SUB_BAD_DATE", f"Некорректная дата: {value}") from None
    if date_from > date_to:
        raise AppError("SUB_BAD_PERIOD", "Начало периода позже конца")
    total = db.subscription_revenue_kop(conn, date_from, date_to)
    return f"{total // 100}.{total % 100:02d}"
