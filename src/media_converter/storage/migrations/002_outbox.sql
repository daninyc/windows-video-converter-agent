CREATE TABLE outbox_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    synced_at TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    UNIQUE(entity_type, entity_id, version)
);
CREATE INDEX outbox_pending ON outbox_events(synced_at, event_id);
