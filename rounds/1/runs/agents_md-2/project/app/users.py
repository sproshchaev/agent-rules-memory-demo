from app import db
from app.clock import to_iso, utc_now
from app.errors import AppError
from app.log import get_logger

log = get_logger(__name__)


def add_user(conn, email: str) -> int:
    if "@" not in email:
        raise AppError("bad_email", f"Некорректный email: {email}")
    user_id = db.insert_user(conn, email.strip().lower(), to_iso(utc_now()))
    log.info("user created id=%s", user_id)
    return user_id


def get_user(conn, user_id: int):
    row = db.find_user(conn, user_id)
    if row is None:
        raise AppError("user_not_found", f"Пользователь {user_id} не найден")
    return row


def remove_user(conn, user_id: int) -> None:
    get_user(conn, user_id)
    db.mark_user_deleted(conn, user_id, to_iso(utc_now()))
    log.info("user removed id=%s", user_id)
