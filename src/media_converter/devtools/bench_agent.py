"""Explicitly gated live acceptance. A missing prerequisite never selects a mock provider."""

import asyncio
import json
import re
from pathlib import Path

from media_converter.agent.service import AgentService
from media_converter.agent.settings_proposals import ProposalContent
from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.devtools.bench_mcp import write_report
from media_converter.media.models import ConversionSettings
from media_converter.services.config import ConfigService
from media_converter.storage.local_store import LocalStore


def preflight(data_dir, live_api):
    root = Path(data_dir).resolve()
    missing = []
    if not live_api:
        missing.append("explicit --live-api")
    receipt = root / "manual-acceptance.json"
    try:
        human = json.loads(receipt.read_text("utf-8"))
    except (OSError, ValueError):
        human = {}
    for field in ("desktop_passed", "media_playback_passed"):
        if human.get(field) is not True:
            missing.append(field)
    if not ConfigService(root).load().credential_ref:
        missing.append("saved provider credential")
    return missing


def proposal_outcome(record):
    proposals = record["proposals"]
    if proposals:
        if all(proposal["status"] == "PENDING" for proposal in proposals):
            return {"status": "pending", "proposal_ids": [p.get("proposal_id") for p in proposals]}
        return {"status": "missing_or_invalid"}
    match = re.search(r"```(?:settings_proposal|json)\s*\n(.*?)```", record["answer_text"], re.S)
    if match:
        try:
            value = ProposalContent.model_validate_json(match[1])
            allowed = {
                source["source_id"] for group in record.get("sources", []) for source in group
            }
            if not value.patch.model_dump(exclude_unset=True) and set(value.source_ids) <= allowed:
                return {"status": "unchanged", "source_ids": list(value.source_ids)}
        except ValueError:
            pass
    return {"status": "missing_or_invalid"}


def turn_checks(record, marker, other_markers, configured_model):
    successful = [
        call
        for call in record["invocations"]
        if call["state"] == "SUCCEEDED" and json.loads(call["result_json"])["ok"]
    ]
    selected = {
        call["tool_name"]
        for call in successful
        if not call["provider_call_id"].startswith("host-search-")
    }
    required = {1: {"read_local_file", "rag_search"}, 2: {"lookup_technical_rules"}, 3: set()}
    checks = {
        "turn_succeeded": record["state"] == "SUCCEEDED",
        "configured_model_returned": bool(record["returned_models"])
        and all(model == configured_model for model in record["returned_models"]),
        "actual_usage": bool(record["usage"])
        and all(
            isinstance(item, dict)
            and all(
                type(item.get(key)) is int and item[key] >= 0
                for key in ("input_tokens", "output_tokens")
            )
            for item in record["usage"]
        ),
        "required_tools_model_selected": required[record["round"]] <= selected,
        "scope_marker_recalled": marker in record["answer_text"],
        "no_other_scope_marker": not any(value in record["answer_text"] for value in other_markers),
        "tool_contexts_match": all(
            all(
                json.loads(call["result_json"])["meta"].get(key) == record[key]
                for key in ("conversation_id", "turn_id", "trace_id")
            )
            and json.loads(call["result_json"])["meta"]["invocation_id"] == call["invocation_id"]
            for call in record["invocations"]
            if call.get("result_json")
        ),
        "no_tool_failed": all(call["state"] == "SUCCEEDED" for call in record["invocations"]),
    }
    if record["round"] == 2:
        checks["proposal_pending_or_unchanged"] = proposal_outcome(record)["status"] in {
            "pending",
            "unchanged",
        }
    if record["round"] == 3:
        checks["relevant_search_succeeded"] = any(
            call["tool_name"] == "search_web"
            and "xyzvideo" in call.get("arguments", {}).get("query", "").lower()
            and bool(json.loads(call["result_json"])["data"]["results"])
            for call in successful
        )
    return checks


async def benchmark(data_dir, output, *, live_api=False, sessions=5, turns_per_session=3):
    root = Path(data_dir).resolve()
    missing = preflight(root, live_api)
    if missing:
        result = {
            "ok": False,
            "status": "blocked",
            "online_called": False,
            "missing": missing,
            "sessions": [],
        }
        write_report(output, result)
        return result
    if sessions != 5 or turns_per_session != 3:
        raise ValueError("acceptance requires five sessions of three turns")
    from PySide6.QtCore import QLockFile

    from media_converter.services.preparer import SetupService

    lease = QLockFile(str(root / "application.lock"))
    if not lease.tryLock(0):
        result = {
            "ok": False,
            "status": "blocked",
            "online_called": False,
            "missing": ["close the desktop using this data directory"],
            "sessions": [],
        }
        write_report(output, result)
        return result
    setup = SetupService(root)
    try:
        local = (
            await setup.prepare(mode="reuse")
            if (root / "private-components.json").exists()
            else await setup.inspect()
        )
        if not local["ok"]:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
        return await _benchmark(root, output, local)
    except AppError as error:
        result = {
            "ok": False,
            "status": "failed",
            "online_called": False,
            "error_code": str(error.info.code),
            "sessions": [],
        }
        write_report(output, result)
        return result
    finally:
        try:
            await setup.close()
        finally:
            lease.unlock()


async def _benchmark(root, output, local):
    # Credential availability is checked without writing or echoing the value.
    ConfigService(root).request_config()
    run_id = new_id().split("-", 1)[0]
    markers = [f"ACCEPTANCE_SCOPE_{run_id}_{i}" for i in range(5)]
    report = {
        "ok": False,
        "status": "running",
        "online_called": True,
        "provider": ConfigService(root).load().model,
        "sessions": [],
        "run_id": run_id,
        "local_preflight": local,
        "history_reload": "AgentService rebuilt after round 2; not an application/process restart",
        "remaining_manual": [
            "confirm proposal in GUI",
            "packaged restart follow-up",
            "inspect external source links and evidence conflicts",
        ],
    }
    with LocalStore(root / "state.sqlite3") as store:
        from media_converter.agent.settings_proposals import ProposalService
        from media_converter.config import AppPaths
        from media_converter.media.toolchain import inspect_toolchain

        proposals = ProposalService(store, inspect_toolchain(AppPaths(root)))
        agent = AgentService(store, root, proposals=proposals)
        chats = [agent.chats.create(f"真实验收 {run_id} / {i + 1}") for i in range(5)]
        note_root = root / "live-acceptance-notes" / run_id
        note_root.mkdir(parents=True, exist_ok=True)
        references = []
        for i, chat in enumerate(chats):
            note = note_root / f"scope-{i}.txt"
            note.write_text(f"本会话独有标记 {markers[i]}。目标：保留音频，生成 MP4。", "utf-8")
            references.append(agent.chats.add_reference(chat.conversation_id, "file", str(note)))
        prompts = (
            (
                "请实际读取本轮授权文档并复述其中的独有标记与目标；"
                "检索本应用 MP4 默认设置（最多2个片段）并给出来源，回答控制在200字内。"
            ),
            (
                "沿用上轮文档，先复述本会话独有标记，再实际查询数据库技术规则，"
                "给出适合文档目标的转换参数建议与 settings_proposal，"
                "先不要应用；正文控制在200字内。"
            ),
            (
                "不重新读取文档，先回忆第一轮的独有标记与目标。"
                "然后检索本地资料核实 FFmpeg 是否支持未知扩展名 .xyzvideo；"
                "缺乏可靠依据时自动搜索，查询必须包含 xyzvideo 和 FFmpeg。"
                "不要编造支持或链接，给出有依据的处理建议，正文控制在250字内。"
            ),
        )
        try:
            for index, prompt in enumerate(prompts):
                if index == 2:
                    await agent.close()
                    # Restart the actual service and read committed conversation history.
                    agent = AgentService(store, root, proposals=proposals)
                failed = False
                batches = [[0], [1, 2, 3, 4]] if index == 0 else [list(range(5))]
                for batch in batches:
                    submitted = await asyncio.gather(
                        *[
                            agent.submit(
                                chats[i].conversation_id,
                                prompt,
                                ConversionSettings(),
                                [references[i].reference_id] if index < 2 else [],
                            )
                            for i in batch
                        ]
                    )
                    completed = await asyncio.gather(
                        *[agent.wait(t.context.turn_id) for t in submitted]
                    )
                    for session_index, turn in zip(batch, completed, strict=True):
                        messages = agent.chats.messages(turn.context.conversation_id)
                        invocations = [
                            json.loads(row[0])
                            for row in agent.chats._rows(
                                "SELECT payload FROM tool_invocations WHERE turn_id=?",
                                (turn.context.turn_id,),
                            )
                        ]
                        current = [m for m in messages if m.turn_id == turn.context.turn_id]
                        calls = {
                            item["call_id"]: json.loads(item["arguments"])
                            for message in current
                            for item in json.loads(message.provider_json)
                            if item.get("type") == "function_call"
                        }
                        for invocation in invocations:
                            invocation["arguments"] = calls.get(invocation["provider_call_id"], {})
                            invocation["origin"] = (
                                "host_fallback"
                                if invocation["provider_call_id"].startswith("host-search-")
                                else "model"
                            )
                        answers = [m.text for m in current if m.role == "assistant" and m.text]
                        proposals_for_chat = [
                            json.loads(row[0])
                            for row in agent.chats._rows(
                                "SELECT payload FROM settings_proposals WHERE conversation_id=?",
                                (turn.context.conversation_id,),
                            )
                        ]
                        sources = [
                            json.loads(m.sources_json)
                            for m in messages
                            if m.turn_id == turn.context.turn_id and m.role == "assistant"
                        ]
                        report["sessions"].append(
                            {
                                "session": session_index + 1,
                                "round": index + 1,
                                "conversation_id": turn.context.conversation_id,
                                "turn_id": turn.context.turn_id,
                                "trace_id": turn.context.trace_id,
                                "state": turn.state,
                                "error_code": turn.error_code,
                                "prompt": prompt,
                                "expected_marker": markers[session_index],
                                "answer_text": answers[-1] if answers else "",
                                "assistant_answers": answers,
                                "reference_ids": [
                                    ref.reference_id for ref in turn.context.references
                                ],
                                "returned_models": turn.returned_models,
                                "usage": json.loads(turn.usage_json),
                                "invocations": invocations,
                                "sources": sources,
                                "history_messages": len(messages),
                                "proposals": [
                                    p
                                    for p in proposals_for_chat
                                    if p["turn_id"] == turn.context.turn_id
                                ],
                            }
                        )
                        record = report["sessions"][-1]
                        if record["round"] == 2:
                            record["proposal_outcome"] = proposal_outcome(record)
                        record["checks"] = turn_checks(
                            record,
                            markers[session_index],
                            [marker for i, marker in enumerate(markers) if i != session_index],
                            report["provider"],
                        )
                    write_report(output, report)
                    if any(
                        not all(row["checks"].values())
                        for row in report["sessions"]
                        if row["round"] == index + 1
                    ):
                        failed = True
                        break
                if failed:
                    break
        except AppError as error:
            report["error_code"] = error.info.code
        finally:
            await agent.close()
    report["automatic_passed"] = len(report["sessions"]) == 15 and all(
        all(r["checks"].values()) for r in report["sessions"]
    )
    report["usage_totals"] = {
        key: sum(
            item.get(key, 0)
            for row in report["sessions"]
            for item in row["usage"]
            if isinstance(item, dict) and type(item.get(key)) is int
        )
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    report["ok"] = report["automatic_passed"]
    # This command cannot attest to human judgement, GUI consent or clean-machine online testing.
    report["status"] = "manual_review_required" if report["automatic_passed"] else "failed"
    write_report(output, report)
    return report
