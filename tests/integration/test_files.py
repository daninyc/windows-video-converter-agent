import pytest

from media_converter.agent.models import Turn
from media_converter.common.errors import AppError
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore
from media_converter.tools.local_files import LocalFiles
from media_converter.tools.schemas import FileQuery

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("name", ["说明.txt", "说明.md", "运行.log", "说明.pdf", "说明.docx"])
async def test_text_and_document_real_parsers(name, fixture_root, tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        reference = chats.add_reference(
            conversation.conversation_id, "file", str(fixture_root / "documents" / name)
        )
        turn = chats.begin(conversation.conversation_id, "读", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        service = LocalFiles(store.path)
        try:
            result = await service.read(FileQuery(file_ref_id=reference.reference_id), turn.context)
            assert result["text"].strip() and result["locations"]
        finally:
            await service.close()


@pytest.mark.parametrize("name", ["加密.pdf", "无文字.pdf", "损坏.pdf", "损坏.docx"])
async def test_document_real_failure_is_not_empty_success(name, fixture_root, tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        ref = chats.add_reference(
            conversation.conversation_id, "file", str(fixture_root / "documents" / name)
        )
        turn = chats.begin(conversation.conversation_id, "读", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        service = LocalFiles(store.path)
        try:
            with pytest.raises(AppError):
                await service.read(FileQuery(file_ref_id=ref.reference_id), turn.context)
        finally:
            await service.close()
