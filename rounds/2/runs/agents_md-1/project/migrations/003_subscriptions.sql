CREATE TABLE subscriptions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan TEXT NOT NULL,
    price_kop INTEGER NOT NULL CHECK (price_kop > 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'cancelled')),
    created_at TEXT NOT NULL
);

CREATE INDEX subscriptions_report ON subscriptions(status, created_at);
