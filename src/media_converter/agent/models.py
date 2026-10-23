import json
from typing import Literal

from pydantic import Field

from media_converter.common.context import new_id
from media_converter.media.models import FileFingerprint, FrozenModel

TurnState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"]
ACTIVE_TURNS = {"QUEUED", "RUNNING"}


class Conversation(FrozenModel):
    conversation_id: str = Field(default_factory=new_id)
    instance_id: str
    title: str = Field(default="新会话", min_length=1, max_length=100)


class Reference(FrozenModel):
    reference_id: str = Field(default_factory=new_id)
    conversation_id: str
    kind: Literal["video", "task", "file"]
    entity_id: str
    label: str
    resolved_path: str | None = None
    fingerprint: FileFingerprint | None = None
    snapshot_json: str = "{}"

    def public_snapshot(self):
        data = json.loads(self.snapshot_json)
        # Local paths are capabilities for tools, not model-visible arguments.
        for key in ("resolved_path", "source_path", "output_path", "output_dir"):
            data.pop(key, None)
        return {
            "reference_id": self.reference_id,
            "kind": self.kind,
            "label": self.label,
            "data": data,
        }


class TurnContext(FrozenModel):
    turn_id: str = Field(default_factory=new_id)
    trace_id: str = Field(default_factory=new_id)
    conversation_id: str
    instance_id: str
    references: tuple[Reference, ...] = ()
    settings_version: int = Field(ge=1)
    settings_json: str
    deadline_at: float
    scope_version: str


class Turn(FrozenModel):
    context: TurnContext
    state: TurnState = "QUEUED"
    error_code: str | None = None
    usage_json: str = "[]"
    returned_models: tuple[str, ...] = ()


class Message(FrozenModel):
    conversation_id: str
    sequence: int
    turn_id: str | None
    role: Literal["user", "assistant", "tool", "system"]
    text: str
    provider_json: str = "[]"
    sources_json: str = "[]"


class ToolInvocation(FrozenModel):
    invocation_id: str = Field(default_factory=new_id)
    turn_id: str
    provider_call_id: str
    tool_name: str
    arguments_hash: str
    state: str
    cache_state: Literal["miss", "hit", "merged"] = "miss"
    result_json: str | None = None


class SettingsProposal(FrozenModel):
    proposal_id: str = Field(default_factory=new_id)
    conversation_id: str
    turn_id: str
    base_settings_version: int
    patch_json: str
    reason: str
    sources_json: str
    status: Literal["PENDING", "APPLIED", "REJECTED"] = "PENDING"
