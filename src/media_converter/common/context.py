from dataclasses import dataclass, field, replace
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


INSTANCE_ID = new_id()


@dataclass(frozen=True)
class CallContext:
    instance_id: str = INSTANCE_ID
    trace_id: str = field(default_factory=new_id)
    conversation_id: str | None = None
    turn_id: str | None = None
    invocation_id: str | None = None

    def new_turn(self, conversation_id: str) -> "CallContext":
        return replace(self, conversation_id=conversation_id, turn_id=new_id())

    def new_invocation(self) -> "CallContext":
        return replace(self, invocation_id=new_id())
