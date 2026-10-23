from dataclasses import dataclass


@dataclass(frozen=True)
class OutboxEvent:
    event_id: int
    entity_type: str
    entity_id: str
    version: int
    payload: str
    created_at: str
    synced_at: str | None
    retry_count: int
    last_error_code: str | None
