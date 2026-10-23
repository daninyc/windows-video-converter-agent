import pytest

from media_converter.agent.mcp_context import META_NAMESPACE, signed_metadata, validate_metadata
from media_converter.agent.models import Turn
from media_converter.common.errors import AppError
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


def test_host_context_signature_is_bound_to_turn_tool_and_arguments(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as local:
        chats = ConversationStore(local)
        a, b = chats.create(), chats.create()
        turn = chats.begin(a.conversation_id, "hi", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        arguments = {"query": "libx264"}
        metadata = signed_metadata(b"secret", turn.context, "invocation", "rag_search", arguments)
        assert (
            validate_metadata(b"secret", chats, metadata, "rag_search", arguments)[0]
            == turn.context
        )
        with pytest.raises(AppError):
            validate_metadata(b"secret", chats, metadata, "rag_search", {"query": "other"})
        metadata[META_NAMESPACE]["value"]["conversation_id"] = b.conversation_id
        with pytest.raises(AppError):
            validate_metadata(b"secret", chats, metadata, "rag_search", arguments)
