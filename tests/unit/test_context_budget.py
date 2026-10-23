import json

import pytest

from media_converter.agent.context_builder import (
    ContextBuilder,
    complete_group,
    estimate_tokens,
    extend_provider_items,
)
from media_converter.common.errors import AppError
from media_converter.media.models import ConversionSettings
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


def test_legacy_host_search_is_coalesced_with_original_reasoning_without_changing_records():
    reasoning = {"type": "reasoning", "content": [{"type": "reasoning_text", "text": "opaque"}]}
    original = [
        reasoning,
        {"type": "function_call", "call_id": "rag"},
        {"type": "function_call_output", "call_id": "rag", "output": "{}"},
    ]
    legacy = [
        {"type": "function_call", "call_id": "host-search-1"},
        {"type": "function_call_output", "call_id": "host-search-1", "output": "{}"},
    ]
    before = json.dumps([original, legacy])
    items = list(original)
    extend_provider_items(items, legacy)
    assert [i["type"] for i in items] == [
        "reasoning",
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]
    assert items[0] is reasoning and complete_group(items)
    assert json.dumps([original, legacy]) == before


def test_budget_extracts_failures_without_deleting_originals_or_splitting_pairs(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        for i in range(5):
            turn = chats.begin(conversation.conversation_id, "中文" * 1400, ConversionSettings())
            pair = [
                {
                    "type": "function_call",
                    "call_id": str(i),
                    "name": "rag_search",
                    "arguments": "{}",
                },
                {"type": "function_call_output", "call_id": str(i), "output": '{"ok":false}'},
            ]
            chats.append(
                conversation.conversation_id, turn.context.turn_id, "assistant", "失败事实", pair
            )
            chats.save_turn(turn.model_copy(update={"state": "FAILED", "error_code": "TIMEOUT"}))
        current = chats.begin(conversation.conversation_id, "继续", ConversionSettings())
        before = chats.messages(conversation.conversation_id)
        builder = ContextBuilder(chats, input_budget=22000)
        items = builder.build(current.context, [])
        assert complete_group(items) and builder.last_metrics["summarized_turns"] > 0
        assert chats.messages(conversation.conversation_id) == before
        summary = json.loads(chats._rows("SELECT payload FROM agent_summaries")[0][0])
        assert summary["state_counts"]["FAILED"] > 0
        assert "TIMEOUT" in json.dumps(summary)
        with pytest.raises(AppError):
            ContextBuilder(chats, input_budget=100).build(current.context, [])


def append_tool_results(chats, turn, tools):
    provider = []
    for index, (name, data) in enumerate(tools):
        call_id = f"{turn.context.turn_id}-{index}"
        provider.extend(
            [
                {"type": "function_call", "call_id": call_id, "name": name, "arguments": "{}"},
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps({"ok": True, "data": data}),
                },
            ]
        )
    chats.append(
        turn.context.conversation_id,
        turn.context.turn_id,
        "assistant",
        "先检索，再给出结论。",
        provider,
    )
    return provider


def test_large_recent_history_can_shrink_to_current_turn_without_losing_marker_or_pairs(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        marker = "ACCEPTANCE_SCOPE_context_budget_0"
        answers = []
        for index in range(2):
            turn = chats.begin(
                conversation.conversation_id, f"第{index + 1}轮取证", ConversionSettings()
            )
            append_tool_results(
                chats,
                turn,
                [
                    ("rag_search", {"chunks": [{"text": "r" * 8000}]}),
                    ("lookup_technical_rules", {"rules": [{"rule_json": {"text": "q" * 7000}}]}),
                ],
            )
            answer = "有来源的参数解释。" * 25 + f" {marker}。目标：保留音频，生成 MP4。"
            answers.append(
                chats.append(
                    conversation.conversation_id,
                    turn.context.turn_id,
                    "assistant",
                    answer,
                    [{"type": "message", "content": [{"type": "output_text", "text": answer}]}],
                )
            )
            chats.save_turn(turn.model_copy(update={"state": "SUCCEEDED"}))
        current = chats.begin(
            conversation.conversation_id, "回忆目标并查询未知扩展名", ConversionSettings()
        )
        current_pairs = append_tool_results(
            chats,
            current,
            [
                ("rag_search", {"chunks": [{"text": "r" * 9000}]}),
                ("search_web", {"results": [{"snippet": "s" * 8000}]}),
            ],
        )
        before = chats.messages(conversation.conversation_id)
        builder = ContextBuilder(chats)
        items = builder.build(current.context, [])
        assert builder.last_metrics["summarized_turns"] == 2
        assert builder.last_metrics["input_budget"] == 32768
        assert estimate_tokens({"input": items, "tools": []}) <= 32768
        assert items[-len(current_pairs) :] == current_pairs
        assert complete_group(items)
        assert chats.messages(conversation.conversation_id) == before
        summary = json.loads(chats._rows("SELECT payload FROM agent_summaries")[0][0])
        assert summary["state_counts"] == {"SUCCEEDED": 2}
        assert summary["through_sequence"] == answers[-1].sequence
        for entry, answer in zip(summary["recent_archived_entries"], answers, strict=True):
            excerpt = entry["excerpts"][-1]
            assert excerpt == {
                "sequence": answer.sequence,
                "role": "assistant",
                "text": answer.text,
            }
            assert marker in excerpt["text"] and "目标：保留音频，生成 MP4" in excerpt["text"]
            assert answer.sequence in entry["message_sequences"]


def test_two_rounds_can_summarize_the_completed_round_when_current_alone_fits(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        old = chats.begin(conversation.conversation_id, "旧问题" * 6000, ConversionSettings())
        answer = chats.append(
            conversation.conversation_id, old.context.turn_id, "assistant", "保留目标"
        )
        chats.save_turn(old.model_copy(update={"state": "FAILED", "error_code": "TIMEOUT"}))
        current = chats.begin(conversation.conversation_id, "继续", ConversionSettings())
        before = chats.messages(conversation.conversation_id)
        builder = ContextBuilder(chats)
        items = builder.build(current.context, [])
        assert complete_group(items) and builder.last_metrics["summarized_turns"] == 1
        assert chats.messages(conversation.conversation_id) == before
        summary = json.loads(chats._rows("SELECT payload FROM agent_summaries")[0][0])
        assert summary["state_counts"] == {"FAILED": 1}
        assert summary["recent_archived_entries"][0]["error_code"] == "TIMEOUT"
        assert summary["through_sequence"] == answer.sequence


def test_oversized_current_turn_still_fails_without_dropping_tool_results(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        current = chats.begin(conversation.conversation_id, "查询", ConversionSettings())
        append_tool_results(chats, current, [("rag_search", {"chunks": [{"text": "x" * 33000}]})])
        before = chats.messages(conversation.conversation_id)
        builder = ContextBuilder(chats)
        with pytest.raises(AppError) as error:
            builder.build(current.context, [])
        assert error.value.info.code == "TURN_LIMIT_REACHED"
        assert builder.last_metrics["input_estimate"] > builder.last_metrics["input_budget"]
        assert chats.messages(conversation.conversation_id) == before


def test_oversized_summary_keeps_the_limit_instead_of_truncating_the_last_answer(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        old = chats.begin(conversation.conversation_id, "旧问题", ConversionSettings())
        chats.append(conversation.conversation_id, old.context.turn_id, "assistant", "x" * 33000)
        chats.save_turn(old.model_copy(update={"state": "SUCCEEDED"}))
        current = chats.begin(conversation.conversation_id, "继续", ConversionSettings())
        before = chats.messages(conversation.conversation_id)
        with pytest.raises(AppError) as error:
            ContextBuilder(chats).build(current.context, [])
        assert error.value.info.code == "TURN_LIMIT_REACHED"
        assert chats.messages(conversation.conversation_id) == before


def test_an_earlier_active_turn_is_not_presented_as_completed_or_summarized(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        old = chats.begin(conversation.conversation_id, "尚未完成" * 4000, ConversionSettings())
        current = chats.begin(conversation.conversation_id, "继续", ConversionSettings())
        with pytest.raises(AppError) as error:
            ContextBuilder(chats).build(current.context, [])
        assert error.value.info.code == "TURN_LIMIT_REACHED"
        assert chats.turn(old.context.turn_id).state == "QUEUED"
        assert chats._rows("SELECT payload FROM agent_summaries") == []
