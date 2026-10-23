"""Live-report checks run locally; these tests never construct a provider or MCP client."""

import json
from copy import deepcopy

import pytest

from media_converter.devtools.bench_agent import proposal_outcome, turn_checks

pytestmark = pytest.mark.unit

MODEL = "deepseek-v4-pro"
MARKER = "ACCEPTANCE_SCOPE_0"
OTHER_MARKERS = ["ACCEPTANCE_SCOPE_1", "ACCEPTANCE_SCOPE_2"]


def invocation(record, tool_name, *, host_fallback=False):
    identity = f"invoke-{tool_name}"
    return {
        "invocation_id": identity,
        "provider_call_id": ("host-search-" if host_fallback else "model-call-") + identity,
        "tool_name": tool_name,
        "state": "SUCCEEDED",
        "origin": "host_fallback" if host_fallback else "model",
        "arguments": {"query": "FFmpeg .xyzvideo"} if tool_name == "search_web" else {},
        "result_json": json.dumps(
            {
                "ok": True,
                "data": {
                    "text": MARKER,
                    "chunks": [{"text": "MP4 default"}],
                    "rules": [{"rule_id": "mp4"}],
                    "results": [{"title": "FFmpeg formats", "url": "https://ffmpeg.org/"}],
                },
                "meta": {
                    **{key: record[key] for key in ("conversation_id", "turn_id", "trace_id")},
                    "invocation_id": identity,
                },
            }
        ),
    }


def record_for(round_number):
    record = {
        "round": round_number,
        "conversation_id": "conversation-0",
        "turn_id": f"turn-{round_number}",
        "trace_id": f"trace-{round_number}",
        "state": "SUCCEEDED",
        "returned_models": [MODEL],
        "usage": [{"input_tokens": 50, "output_tokens": 20, "total_tokens": 70}],
        "answer_text": f"{MARKER}。目标：保留音频，生成 MP4。",
        "proposals": [{"status": "PENDING", "proposal_id": "proposal-0"}]
        if round_number == 2
        else [],
        "sources": [[{"source_id": "known-source", "title": "MP4 defaults"}]],
    }
    tools = {
        1: ["read_local_file", "rag_search"],
        2: ["lookup_technical_rules"],
        3: ["rag_search", "search_web"],
    }[round_number]
    record["invocations"] = [invocation(record, tool) for tool in tools]
    return record


def checks(record):
    return turn_checks(record, MARKER, OTHER_MARKERS, MODEL)


@pytest.mark.parametrize("round_number", [1, 2, 3])
def test_realistic_successful_report_passes_each_round(round_number):
    assert all(checks(record_for(round_number)).values())


@pytest.mark.parametrize("round_number", [1, 2, 3])
def test_a_successful_answer_without_tool_execution_is_not_accepted(round_number):
    record = record_for(round_number)
    record["invocations"] = []
    assert not all(checks(record).values())


@pytest.mark.parametrize(
    "usage",
    [
        [],
        [None],
        [{"input_tokens": 1}],
        [{"input_tokens": True, "output_tokens": 20}],
        [{"input_tokens": 50, "output_tokens": -1}],
    ],
)
def test_missing_or_invalid_provider_usage_is_not_actual_usage(usage):
    record = record_for(1)
    record["usage"] = usage
    assert checks(record)["actual_usage"] is False


def test_another_conversation_marker_fails_isolation():
    record = record_for(1)
    record["answer_text"] += " " + OTHER_MARKERS[0]
    assert checks(record)["no_other_scope_marker"] is False


def test_own_marker_cannot_be_replaced_with_a_plausible_answer():
    record = record_for(3)
    record["answer_text"] = "目标：保留音频，生成 MP4，但无法回忆独有标记。"
    assert checks(record)["scope_marker_recalled"] is False


@pytest.mark.parametrize("field", ["conversation_id", "turn_id", "trace_id", "invocation_id"])
def test_tool_results_cannot_be_paired_with_another_context(field):
    record = record_for(1)
    call = record["invocations"][0]
    result = json.loads(call["result_json"])
    result["meta"][field] = "from-another-session"
    call["result_json"] = json.dumps(result)
    assert checks(record)["tool_contexts_match"] is False


@pytest.mark.parametrize(
    "proposals",
    [
        [],
        [{"status": "APPLIED"}],
        [{"status": "REJECTED"}],
        [{"status": "PENDING"}, {"status": "APPLIED"}],
    ],
)
def test_parameter_advice_must_remain_pending_user_confirmation(proposals):
    record = record_for(2)
    record["proposals"] = proposals
    assert checks(record)["proposal_pending_or_unchanged"] is False


def test_valid_empty_patch_with_actual_sources_is_an_unchanged_outcome():
    record = record_for(2)
    record["proposals"] = []
    content = {"patch": {}, "reason": "默认设置已经符合目标", "source_ids": ["known-source"]}
    record["answer_text"] += "\n```settings_proposal\n" + json.dumps(content) + "\n```"
    assert proposal_outcome(record) == {"status": "unchanged", "source_ids": ["known-source"]}
    assert all(checks(record).values())


def test_pending_proposal_stays_distinct_from_a_no_change_outcome():
    record = record_for(2)
    assert proposal_outcome(record) == {"status": "pending", "proposal_ids": ["proposal-0"]}
    assert checks(record)["proposal_pending_or_unchanged"] is True


@pytest.mark.parametrize(
    "content",
    [
        {"patch": {}, "reason": "空来源", "source_ids": []},
        {"patch": {}, "reason": "伪造来源", "source_ids": ["invented-source"]},
        {"patch": {}, "source_ids": ["known-source"]},
        {"patch": {}, "reason": "额外动作", "source_ids": ["known-source"], "apply": True},
        {"patch": {"command": "arbitrary"}, "reason": "危险参数", "source_ids": ["known-source"]},
        {
            "patch": {"quality_value": None},
            "reason": "非空无效变更",
            "source_ids": ["known-source"],
        },
        {"reason": "缺少patch", "source_ids": ["known-source"]},
    ],
)
def test_invalid_or_unsourced_empty_patch_cannot_bypass_proposal_review(content):
    record = record_for(2)
    record["proposals"] = []
    record["answer_text"] += "\n```json\n" + json.dumps(content) + "\n```"
    assert proposal_outcome(record) == {"status": "missing_or_invalid"}
    assert checks(record)["proposal_pending_or_unchanged"] is False


def test_empty_patch_source_id_must_exist_in_the_actual_turn_sources():
    record = record_for(2)
    record["proposals"], record["sources"] = [], []
    content = {"patch": {}, "reason": "保持原设置", "source_ids": ["known-source"]}
    record["answer_text"] += "\n```json\n" + json.dumps(content) + "\n```"
    assert proposal_outcome(record) == {"status": "missing_or_invalid"}
    assert checks(record)["proposal_pending_or_unchanged"] is False


def test_malformed_json_is_not_evidence_of_an_unchanged_outcome():
    record = record_for(2)
    record["proposals"] = []
    record["answer_text"] += '\n```json\n{"patch":\n```'
    assert proposal_outcome(record) == {"status": "missing_or_invalid"}
    assert checks(record)["proposal_pending_or_unchanged"] is False


def test_host_generated_calls_cannot_count_as_model_selected_required_tools():
    record = record_for(1)
    record["invocations"] = [
        invocation(record, "read_local_file", host_fallback=True),
        invocation(record, "rag_search", host_fallback=True),
    ]
    assert checks(record)["required_tools_model_selected"] is False


def test_success_state_without_successful_result_does_not_prove_tool_selection():
    record = record_for(1)
    call = record["invocations"][0]
    result = json.loads(call["result_json"])
    result["ok"] = False
    call["result_json"] = json.dumps(result)
    assert checks(record)["required_tools_model_selected"] is False


def test_generic_host_fallback_does_not_verify_the_unknown_extension():
    record = record_for(3)
    fallback = invocation(record, "search_web", host_fallback=True)
    fallback["arguments"] = {"query": "视频编码 格式兼容 FFmpeg"}
    record["invocations"][-1] = fallback
    result = checks(record)
    assert result["relevant_search_succeeded"] is False
    assert not all(result.values())


def test_relevant_host_search_is_valid_automatic_search_with_its_origin_preserved():
    record = record_for(3)
    fallback = invocation(record, "search_web", host_fallback=True)
    record["invocations"][-1] = fallback
    assert checks(record)["relevant_search_succeeded"] is True
    assert fallback["origin"] == "host_fallback"
    assert fallback["provider_call_id"].startswith("host-search-")


def test_empty_search_results_do_not_prove_external_evidence_was_found():
    record = record_for(3)
    search = record["invocations"][-1]
    result = json.loads(search["result_json"])
    result["data"]["results"] = []
    search["result_json"] = json.dumps(result)
    assert checks(record)["relevant_search_succeeded"] is False


def test_returned_model_must_match_the_configured_model():
    record = record_for(1)
    record["returned_models"] = [MODEL, "another-provider-model"]
    assert checks(record)["configured_model_returned"] is False


def test_checking_does_not_modify_the_original_evidence():
    record = record_for(3)
    before = deepcopy(record)
    checks(record)
    assert record == before
