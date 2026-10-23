CREATE TABLE settings (entity_id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE presets (entity_id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE assets (entity_id TEXT PRIMARY KEY, version INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE job_attempts (
    entity_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    payload TEXT NOT NULL,
    state TEXT NOT NULL
);
CREATE INDEX job_attempts_state ON job_attempts(state);
