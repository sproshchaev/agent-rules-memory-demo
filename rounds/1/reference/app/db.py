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


def insert_subscription(
    conn: sqlite3.Connection, user_id: int, plan: str, price_kop: int, created_at: str
) -> int:
    cur = conn.execute(
        "INSERT INTO subscriptions (user_id, plan, price_kop, created_at) VALUES (?, ?, ?, ?)",
        (user_id, plan, price_kop, created_at),
    )
    conn.commit()
    return cur.lastrowid


def mark_subscription_cancelled(
    conn: sqlite3.Connection, subscription_id: int, cancelled_at: str
) -> bool:
    """Отмена одним условным UPDATE: две параллельные отмены не пройдут обе."""
    cur = conn.execute(
        "UPDATE subscriptions SET cancelled_at = ? WHERE id = ? AND cancelled_at IS NULL",
        (cancelled_at, subscription_id),
    )
    conn.commit()
    return cur.rowcount == 1


def sum_active_subscriptions_kop(conn: sqlite3.Connection, date_from: str, date_to: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(price_kop), 0) AS total FROM subscriptions"
        " WHERE cancelled_at IS NULL AND created_at >= ? AND created_at < ?",
        (date_from, date_to),
    ).fetchone()
    return row["total"]
