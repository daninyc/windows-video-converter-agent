import json
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from media_converter.agent.settings_proposals import ProposalContent

pytestmark = pytest.mark.live_api


@pytest.fixture(scope="module")
def report():
    path = Path("artifacts/reports/agent-5-sessions.json")
    if not path.exists():
        pytest.fail("Run bench-agent after human acceptance and credential setup")
    return json.loads(path.read_text("utf-8"))


def tool_calls(record, name):
    return [call for call in record["invocations"] if call["tool_name"] == name]


def test_real_provider_report_contains_five_isolated_sessions_of_three_rounds(report):
    assert report["online_called"] is True and report["automatic_passed"] is True
    assert report["ok"] is True
    assert report["provider"] == "deepseek-v4-pro"
    assert len(report["sessions"]) == 15
    assert len({row["turn_id"] for row in report["sessions"]}) == 15
    assert len({row["trace_id"] for row in report["sessions"]}) == 15
    conversations = defaultdict(list)
    for record in report["sessions"]:
        conversations[record["conversation_id"]].append(record)
        assert record["state"] == "SUCCEEDED" and record["error_code"] is None
        assert record["checks"] and all(value is True for value in record["checks"].values())
        assert record["expected_marker"] in record["answer_text"]
    assert len(conversations) == 5
    markers = set()
    for records in conversations.values():
        assert sorted(row["round"] for row in records) == [1, 2, 3]
        assert len({row["session"] for row in records}) == 1
        assert len({row["expected_marker"] for row in records}) == 1
        markers.add(records[0]["expected_marker"])
    assert len(markers) == 5
    for record in report["sessions"]:
        assert not any(
            marker in record["answer_text"] for marker in markers - {record["expected_marker"]}
        )


def test_every_provider_response_has_actual_model_and_numeric_usage(report):
    totals = {key: 0 for key in ("input_tokens", "output_tokens", "total_tokens")}
    for record in report["sessions"]:
        assert record["returned_models"]
        assert all(model == report["provider"] for model in record["returned_models"])
        assert len(record["usage"]) == len(record["returned_models"])
        for usage in record["usage"]:
            assert isinstance(usage, dict)
            for key in totals:
                assert type(usage[key]) is int and usage[key] >= 0
                totals[key] += usage[key]
            assert usage["input_tokens"] > 0
            assert usage["total_tokens"] == usage["input_tokens"] + usage["output_tokens"]
    assert report["usage_totals"] == totals


def test_tool_results_keep_context_and_model_or_host_origin(report):
    for record in report["sessions"]:
        assert record["invocations"]
        for call in record["invocations"]:
            assert call["turn_id"] == record["turn_id"]
            assert call["state"] == "SUCCEEDED"
            result = json.loads(call["result_json"])
            assert result["ok"] is True and result["error"] is None
            assert isinstance(call["arguments"], dict)
            for key in ("conversation_id", "turn_id", "trace_id"):
                assert result["meta"][key] == record[key]
            assert result["meta"]["invocation_id"] == call["invocation_id"]
            if call["provider_call_id"].startswith("host-search-"):
                assert call["origin"] == "host_fallback" and call["tool_name"] == "search_web"
            else:
                assert call["origin"] == "model"


def test_first_round_model_actually_reads_authorized_file_and_nonempty_rag(report):
    for record in report["sessions"]:
        if record["round"] != 1:
            continue
        reads = tool_calls(record, "read_local_file")
        searches = tool_calls(record, "rag_search")
        assert reads and searches and record["reference_ids"]
        assert all(call["origin"] == "model" for call in reads + searches)
        assert any(
            record["expected_marker"] in json.loads(call["result_json"])["data"]["text"]
            for call in reads
        )
        for call in reads:
            assert call["arguments"]["file_ref_id"] in record["reference_ids"]
            assert json.loads(call["result_json"])["data"]["file_ref_id"] in record["reference_ids"]
        for call in searches:
            result = json.loads(call["result_json"])
            assert result["data"]["chunks"] and result["data"]["knowledge_version"]
            assert all(chunk["text"] and chunk["source"] for chunk in result["data"]["chunks"])
            assert result["sources"]


def test_second_round_queries_rules_and_either_previews_changes_or_keeps_settings_unchanged(report):
    for record in report["sessions"]:
        if record["round"] != 2:
            continue
        rules = tool_calls(record, "lookup_technical_rules")
        assert rules and all(call["origin"] == "model" for call in rules)
        assert any(json.loads(call["result_json"])["data"]["rules"] for call in rules)
        assert any(json.loads(call["result_json"])["sources"] for call in rules)
        match = re.search(
            r"```(?:settings_proposal|json)\s*\n(.*?)```", record["answer_text"], re.S
        )
        assert match, "Advice must include a complete, sourced proposal payload"
        content = ProposalContent.model_validate_json(match[1])
        actual_sources = {source["source_id"] for group in record["sources"] for source in group}
        assert set(content.source_ids) <= actual_sources
        if not content.patch.model_dump(exclude_unset=True):
            assert record["proposals"] == []
            assert record["proposal_outcome"] == {
                "status": "unchanged",
                "source_ids": list(content.source_ids),
            }
            continue
        assert record["proposals"]
        assert record["proposal_outcome"] == {
            "status": "pending",
            "proposal_ids": [proposal["proposal_id"] for proposal in record["proposals"]],
        }
        for proposal in record["proposals"]:
            assert proposal["status"] == "PENDING"
            assert proposal["conversation_id"] == record["conversation_id"]
            assert proposal["turn_id"] == record["turn_id"]


def test_third_round_uses_history_without_file_authorization_and_performs_relevant_search(report):
    for record in report["sessions"]:
        if record["round"] != 3:
            continue
        assert record["reference_ids"] == []
        assert not tool_calls(record, "read_local_file")
        searches = tool_calls(record, "search_web")
        relevant = [
            call for call in searches if "xyzvideo" in call["arguments"].get("query", "").lower()
        ]
        assert relevant
        for call in relevant:
            data = json.loads(call["result_json"])["data"]
            assert data["results"]
            for source in data["results"]:
                url = urlsplit(source["url"])
                assert url.scheme in {"http", "https"} and url.hostname and source["title"]
