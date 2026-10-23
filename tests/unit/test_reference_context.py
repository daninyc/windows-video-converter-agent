import json

import pytest

from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


def test_model_file_reference_is_distinct_from_citation_without_exposing_path(tmp_path):
    from media_converter.agent.context_builder import ContextBuilder

    file = tmp_path / "private-note.txt"
    file.write_text("scope-only text", encoding="utf-8")
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        chat = chats.create()
        reference = chats.add_reference(chat.conversation_id, "file", str(file))
        turn = chats.begin(chat.conversation_id, "读取授权文档", ConversionSettings())
        items = ContextBuilder(chats).build(turn.context, [])
        facts = json.loads(items[1]["content"].split("：", 1)[1])
        document = facts["references"][0]
        assert document["file_ref_id"] == reference.reference_id
        assert document["source_id"].startswith("src-")
        assert document["file_ref_id"] != document["source_id"]
        assert str(tmp_path) not in json.dumps(items)
        assert "scope-only text" not in json.dumps(items)


def test_reference_snapshot_replacement_revocation_and_cross_scope(tmp_path):
    file = tmp_path / "中文.txt"
    file.write_text("original", encoding="utf-8")
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        a, b = chats.create(), chats.create()
        ref = chats.add_reference(a.conversation_id, "file", str(file))
        turn = chats.begin(a.conversation_id, "读资料", ConversionSettings())
        assert turn.context.references == (ref,)
        assert "resolved_path" not in ref.public_snapshot()["data"]
        with pytest.raises(AppError) as error:
            chats.begin(b.conversation_id, "越权", ConversionSettings(), [ref.reference_id])
        assert error.value.info.code == ErrorCode.ACCESS_DENIED
        file.write_text("replacement", encoding="utf-8")
        with pytest.raises(AppError) as error:
            chats.begin(a.conversation_id, "变化", ConversionSettings())
        assert error.value.info.code == ErrorCode.FILE_CHANGED
        chats.revoke(a.conversation_id, ref.reference_id)
        assert not chats.references(a.conversation_id)
        assert turn.context.references == (ref,)
