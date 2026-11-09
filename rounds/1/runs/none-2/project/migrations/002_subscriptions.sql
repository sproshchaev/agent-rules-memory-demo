CREATE TABLE subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    plan TEXT NOT NULL,
    price_kopecks INTEGER NOT NULL CHECK (price_kopecks > 0),
    created_at TEXT NOT NULL,
    cancelled_at TEXT
);

CREATE INDEX subscriptions_created_at_idx ON subscriptions(created_at);
