CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan TEXT NOT NULL,
    price_kop INTEGER NOT NULL CHECK (price_kop > 0),
    created_at TEXT NOT NULL,
    cancelled_at TEXT
);

CREATE INDEX subscriptions_created_at ON subscriptions(created_at)
WHERE cancelled_at IS NULL;
