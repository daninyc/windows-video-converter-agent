import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from media_converter.agent.models import (
    Conversation,
    Message,
    Reference,
    Turn,
    TurnContext,
)
from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import FileFingerprint


class ConversationReader:
    """MCP only reads committed state; opening it must never recover active jobs/turns."""

    def __init__(self, path):
        self.path = Path(path).resolve()

    def _rows(self, sql, parameters=()):
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)) as c:
            return c.execute(sql, parameters).fetchall()

    def conversation(self, conversation_id):
        rows = self._rows(
            "SELECT payload FROM conversations WHERE conversation_id=?", (conversation_id,)
        )
        if not rows:
            raise AppError(ErrorCode.ACCESS_DENIED)
        return Conversation.model_validate_json(rows[0][0])

    def list_conversations(self):
        return [
            Conversation.model_validate_json(r[0])
            for r in self._rows("SELECT payload FROM conversations ORDER BY rowid DESC")
        ]

    def references(self, conversation_id):
        return tuple(
            Reference.model_validate_json(r[0])
            for r in self._rows(
                "SELECT payload FROM agent_references WHERE conversation_id=? "
                "AND revoked=0 ORDER BY rowid",
                (conversation_id,),
            )
        )

    def messages(self, conversation_id):
        return tuple(
            Message.model_validate_json(r[0])
            for r in self._rows(
                "SELECT payload FROM messages WHERE conversation_id=? ORDER BY sequence",
                (conversation_id,),
            )
        )

    def turn(self, turn_id):
        rows = self._rows("SELECT payload FROM agent_turns WHERE turn_id=?", (turn_id,))
        if not rows:
            raise AppError(ErrorCode.ACCESS_DENIED)
        return Turn.model_validate_json(rows[0][0])


class ConversationStore(ConversationReader):
    def __init__(self, store):
        super().__init__(store.path)
        self.store = store

        def initialize(c):
            c.execute("INSERT OR IGNORE INTO agent_meta VALUES('instance_id',?)", (new_id(),))
            for row in c.execute(
                "SELECT payload FROM agent_turns WHERE state IN ('QUEUED','RUNNING')"
            ).fetchall():
                turn = Turn.model_validate_json(row[0]).model_copy(
                    update={"state": "INTERRUPTED", "error_code": "INTERRUPTED"}
                )
                self._save_turn(c, turn)
            return c.execute("SELECT value FROM agent_meta WHERE key='instance_id'").fetchone()[0]

        self.instance_id = store._write(initialize)

    def create(self, title="新会话"):
        value = Conversation(instance_id=self.instance_id, title=title)
        self.store._write(
            lambda c: c.execute(
                "INSERT INTO conversations VALUES(?,?)",
                (value.conversation_id, value.model_dump_json()),
            )
        )
        return value

    def add_reference(self, conversation_id, kind, entity_id):
        self.conversation(conversation_id)
        if kind == "file":
            path = Path(entity_id).resolve(strict=True)
            if path.suffix.lower() not in {".txt", ".md", ".log", ".pdf", ".docx"}:
                raise AppError(ErrorCode.INVALID_ARGUMENT)
            value = Reference(
                conversation_id=conversation_id,
                kind=kind,
                entity_id=new_id(),
                label=path.name,
                resolved_path=str(path),
                fingerprint=FileFingerprint.from_path(path),
            )
        elif kind == "video":
            asset = self.store.get_asset(entity_id)
            if asset is None:
                raise AppError(ErrorCode.ACCESS_DENIED)
            value = Reference(
                conversation_id=conversation_id,
                kind=kind,
                entity_id=entity_id,
                label=Path(asset.resolved_path).name,
                resolved_path=str(asset.resolved_path),
                fingerprint=asset.fingerprint,
                snapshot_json=asset.model_dump_json(),
            )
        elif kind == "task":
            attempt = self.store.get_attempt(entity_id)
            if attempt is None:
                raise AppError(ErrorCode.ACCESS_DENIED)
            value = Reference(
                conversation_id=conversation_id,
                kind=kind,
                entity_id=entity_id,
                label=f"任务 {attempt.state}",
                snapshot_json=attempt.model_dump_json(),
            )
        else:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        self.store._write(
            lambda c: c.execute(
                "INSERT INTO agent_references(reference_id,conversation_id,payload) VALUES(?,?,?)",
                (value.reference_id, conversation_id, value.model_dump_json()),
            )
        )
        return value

    def revoke(self, conversation_id, reference_id):
        self.store._write(
            lambda c: c.execute(
                "UPDATE agent_references SET revoked=1 WHERE reference_id=? AND conversation_id=?",
                (reference_id, conversation_id),
            )
        )

    @staticmethod
    def _message(c, conversation_id, turn_id, role, text, provider_json="[]", sources_json="[]"):
        sequence = c.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()[0]
        message = Message(
            conversation_id=conversation_id,
            sequence=sequence,
            turn_id=turn_id,
            role=role,
            text=text,
            provider_json=provider_json,
            sources_json=sources_json,
        )
        c.execute(
            "INSERT INTO messages VALUES(?,?,?,?)",
            (conversation_id, sequence, turn_id, message.model_dump_json()),
        )
        return message

    def append(self, conversation_id, turn_id, role, text, provider_items=(), sources=()):
        self.conversation(conversation_id)
        return self.store._write(
            lambda c: self._message(
                c,
                conversation_id,
                turn_id,
                role,
                text,
                json.dumps(provider_items, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
            )
        )

    @staticmethod
    def _save_turn(c, turn):
        c.execute(
            "INSERT INTO agent_turns VALUES(?,?,?,?) ON CONFLICT(turn_id) "
            "DO UPDATE SET state=excluded.state,payload=excluded.payload",
            (
                turn.context.turn_id,
                turn.context.conversation_id,
                turn.state,
                turn.model_dump_json(),
            ),
        )

    def save_turn(self, turn):
        self.store._write(lambda c: self._save_turn(c, turn))

    def begin(self, conversation_id, text, settings, reference_ids=None, timeout=300):
        conversation = self.conversation(conversation_id)
        if conversation.instance_id != self.instance_id or not text.strip() or len(text) > 32_000:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        available = self.references(conversation_id)
        selected = tuple(
            r for r in available if reference_ids is None or r.reference_id in reference_ids
        )
        if reference_ids is not None and set(reference_ids) != {r.reference_id for r in selected}:
            raise AppError(ErrorCode.ACCESS_DENIED)
        for reference in selected:
            if reference.resolved_path:
                try:
                    if (
                        FileFingerprint.from_path(Path(reference.resolved_path))
                        != reference.fingerprint
                    ):
                        raise AppError(ErrorCode.FILE_CHANGED)
                except OSError as error:
                    raise AppError(ErrorCode.FILE_CHANGED) from error
        scope = hashlib.sha256(
            json.dumps([r.model_dump(mode="json") for r in selected], sort_keys=True).encode()
        ).hexdigest()
        context = TurnContext(
            conversation_id=conversation_id,
            instance_id=self.instance_id,
            references=selected,
            settings_version=settings.settings_version,
            settings_json=settings.model_dump_json(),
            deadline_at=time.time() + timeout,
            scope_version=scope,
        )
        turn = Turn(context=context)

        def operation(c):
            self._save_turn(c, turn)
            self._message(c, conversation_id, context.turn_id, "user", text)

        self.store._write(operation)
        return turn
