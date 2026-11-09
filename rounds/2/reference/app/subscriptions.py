import re
import uuid

from app import db, users
from app.clock import to_iso, utc_now
from app.errors import AppError
from app.log import get_logger

log = get_logger(__name__)
PRICE = re.compile(r"(\d+)(?:\.(\d{1,2}))?")


def parse_price_kop(price_rub: str) -> int:
    match = PRICE.fullmatch(price_rub.strip())
    if match is None:
        raise AppError("SUB_BAD_PRICE", f"Некорректная цена: {price_rub}")
    rub, kop = match.group(1), (match.group(2) or "0").ljust(2, "0")
    return int(rub) * 100 + int(kop)


def format_rub(amount_kop: int) -> str:
    return f"{amount_kop // 100}.{amount_kop % 100:02d}"


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> str:
    users.get_user(conn, user_id)
    price_kop = parse_price_kop(price_rub)
    sub_id = str(uuid.uuid4())
    now = to_iso(utc_now())
    db.insert_subscription(conn, sub_id, user_id, plan, price_kop, now)
    db.add_audit(conn, "subscription", sub_id, "created", now)
    log.info("event=subscription_created id=%s user_id=%s", sub_id, user_id)
    return sub_id


def cancel_subscription(conn, subscription_id: str) -> None:
    now = to_iso(utc_now())
    if not db.mark_subscription_cancelled(conn, subscription_id, now):
        raise AppError("SUB_NOT_FOUND", f"Активная подписка {subscription_id} не найдена")
    db.add_audit(conn, "subscription", subscription_id, "cancelled", now)
    log.info("event=subscription_cancelled id=%s", subscription_id)


def revenue_report(conn, date_from: str, date_to: str) -> str:
    return format_rub(db.sum_active_subscriptions_kop(conn, date_from, date_to))
