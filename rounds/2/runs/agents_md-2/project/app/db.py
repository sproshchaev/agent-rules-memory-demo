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


def insert_subscription(conn, subscription_id, user_id, plan, price_kop, created_at):
    conn.execute(
        "INSERT INTO subscriptions (id, user_id, plan, price_kop, status, created_at) "
        "VALUES (?, ?, ?, ?, 'active', ?)",
        (subscription_id, user_id, plan, price_kop, created_at),
    )


def find_subscription(conn, subscription_id):
    return conn.execute(
        "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
    ).fetchone()


def cancel_subscription(conn, subscription_id):
    return conn.execute(
        "UPDATE subscriptions SET status = 'cancelled' WHERE id = ? AND status = 'active'",
        (subscription_id,),
    ).rowcount > 0


def subscription_prices(conn, date_from, date_to):
    # Sum in Python so totals can exceed SQLite's 64-bit aggregate limit.
    return (row['price_kop'] for row in conn.execute(
        "SELECT price_kop FROM subscriptions "
        "WHERE status = 'active' AND created_at >= ? AND created_at < ?",
        (date_from, date_to),
    ))
