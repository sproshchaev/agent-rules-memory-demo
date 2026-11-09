CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users (id),
    plan TEXT NOT NULL,
    price_kop INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    cancelled_at TEXT
);
