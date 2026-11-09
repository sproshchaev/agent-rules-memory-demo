import re

from app import db, users
from app.clock import to_iso, utc_now
from app.errors import AppError
from app.log import get_logger

log = get_logger(__name__)
PRICE = re.compile(r"(\d+)(?:\.(\d{1,2}))?")


def parse_price_kop(price_rub: str) -> int:
    match = PRICE.fullmatch(price_rub.strip())
    if match is None:
        raise AppError("bad_price", f"Некорректная цена: {price_rub}")
    rub, kop = match.group(1), (match.group(2) or "0").ljust(2, "0")
    return int(rub) * 100 + int(kop)


def format_rub(amount_kop: int) -> str:
    return f"{amount_kop // 100}.{amount_kop % 100:02d}"


def create_subscription(conn, user_id: int, plan: str, price_rub: str) -> int:
    users.get_user(conn, user_id)
    price_kop = parse_price_kop(price_rub)
    sub_id = db.insert_subscription(conn, user_id, plan, price_kop, to_iso(utc_now()))
    log.info("subscription created id=%s", sub_id)
    return sub_id


def cancel_subscription(conn, subscription_id: int) -> None:
    if not db.mark_subscription_cancelled(conn, subscription_id, to_iso(utc_now())):
        raise AppError("subscription_not_found", f"Активная подписка {subscription_id} не найдена")
    log.info("subscription cancelled id=%s", subscription_id)


def revenue_report(conn, date_from: str, date_to: str) -> str:
    return format_rub(db.sum_active_subscriptions_kop(conn, date_from, date_to))
