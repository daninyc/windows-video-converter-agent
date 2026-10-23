from concurrent.futures import ThreadPoolExecutor

import pytest

from media_converter.agent.models import Turn
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationReader, ConversationStore
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


def test_sequences_isolation_restart_and_interruption(tmp_path):
    path = tmp_path / "state.sqlite3"
    with LocalStore(path) as store:
        chats = ConversationStore(store)
        conversations = [chats.create(str(i)) for i in range(5)]
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(
                pool.map(
                    lambda i: chats.append(
                        conversations[i % 5].conversation_id, None, "user", str(i)
                    ),
                    range(50),
                )
            )
        for conversation in conversations:
            messages = chats.messages(conversation.conversation_id)
            assert [m.sequence for m in messages] == list(range(1, 11))
        turn = chats.begin(conversations[0].conversation_id, "问题", ConversionSettings())
        chats.save_turn(Turn(context=turn.context, state="RUNNING"))
        assert ConversationReader(path).turn(turn.context.turn_id).state == "RUNNING"
    with LocalStore(path) as store:
        chats = ConversationStore(store)
        assert chats.turn(turn.context.turn_id).state == "INTERRUPTED"
        assert len(chats.messages(conversations[0].conversation_id)) == 11
        retry = chats.begin(conversations[0].conversation_id, "重试", ConversionSettings())
        assert retry.context.turn_id != turn.context.turn_id
