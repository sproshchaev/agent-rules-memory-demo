import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    return conn


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
    applied = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if file.name in applied:
            continue
        conn.executescript(file.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (file.name,))
    conn.commit()


def insert_user(conn: sqlite3.Connection, email: str, created_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, created_at) VALUES (?, ?)", (email, created_at)
    )
    conn.commit()
    return cur.lastrowid


def find_user(conn: sqlite3.Connection, user_id: int):
    return conn.execute(
        "SELECT id, email, created_at FROM users WHERE id = ? AND deleted_at IS NULL",
        (user_id,),
    ).fetchone()


def mark_user_deleted(conn: sqlite3.Connection, user_id: int, deleted_at: str) -> None:
    conn.execute("UPDATE users SET deleted_at = ? WHERE id = ?", (deleted_at, user_id))
    conn.commit()


def add_audit(conn: sqlite3.Connection, entity: str, entity_id: str, action: str, at: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (entity, entity_id, action, at) VALUES (?, ?, ?, ?)",
        (entity, str(entity_id), action, at),
    )
    conn.commit()


def insert_subscription(
    conn: sqlite3.Connection, sub_id: str, user_id: int, plan: str, price_kop: int, now: str
) -> None:
    conn.execute(
        "INSERT INTO subscriptions (id, user_id, plan, price_kop, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'active', ?, ?)",
        (sub_id, user_id, plan, price_kop, now, now),
    )
    conn.commit()


def find_active_subscription(conn: sqlite3.Connection, sub_id: str):
    return conn.execute(
        "SELECT id FROM subscriptions WHERE id = ? AND status = 'active'", (sub_id,)
    ).fetchone()


def set_subscription_status(conn: sqlite3.Connection, sub_id: str, status: str, now: str) -> None:
    conn.execute(
        "UPDATE subscriptions SET status = ?, updated_at = ? WHERE id = ?", (status, now, sub_id)
    )
    conn.commit()


def sum_active_subscriptions_kop(conn: sqlite3.Connection, date_from: str, date_to: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(price_kop), 0) AS total FROM subscriptions"
        " WHERE status = 'active' AND created_at >= ? AND created_at < ?",
        (date_from, date_to),
    ).fetchone()
    return row["total"]
