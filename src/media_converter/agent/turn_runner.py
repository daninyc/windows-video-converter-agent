import asyncio
import hashlib
import json
import re
from pathlib import Path

from media_converter.agent.context_builder import ContextBuilder
from media_converter.agent.models import ToolInvocation
from media_converter.agent.references import reference_source, source_with_id
from media_converter.agent.tool_dedup import cache_key
from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import FileFingerprint
from media_converter.rag.index_store import IndexStore
from media_converter.tools.schemas import CATEGORIES, SCHEMAS
from media_converter.tools.web_search import safe_query


def needs_evidence_search(name, result):
    if name not in {"rag_search", "lookup_technical_rules"}:
        return False
    if not result["ok"]:
        return (result.get("error") or {}).get("code") in {
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            ErrorCode.TIMEOUT,
            ErrorCode.RATE_LIMITED,
            ErrorCode.QUEUE_FULL,
            ErrorCode.MCP_DISCONNECTED,
            ErrorCode.PROCESS_FAILED,
        }
    data = result.get("data") or {}
    return bool(data.get("evidence_sufficient") is False or data.get("conflict"))


def evidence_search_query(question, context):
    # Search technical terms, never whole local questions or document identifiers.
    text = question
    for reference in context.references:
        for private in (reference.resolved_path, reference.label):
            if private:
                text = re.sub(re.escape(private), " ", text, flags=re.I)
    text = re.sub(r"\S*[\\/]\S*", " ", text)
    text = re.sub(
        r"(?i)\b(?:api[_-]?key|password|token|secret)\s*[:=]\s*"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;，；]+)|\bbearer\s+\S+",
        " ",
        text,
    )
    terms = set(
        re.findall(
            r"libx264|mov_text|MP4|WebM|MKV|AV1|H\.264|HEVC|VP9|AAC|Opus|FFmpeg",
            text,
            re.I,
        )
    )
    terms.update(re.findall(r"(?<![\w./\\:-])\.[A-Za-z][A-Za-z0-9]{0,15}(?![\w./\\-])", text))
    query = "视频编码 格式兼容"
    for term in sorted(terms):
        if len(query) + len(term) + 1 <= 128:
            query += " " + term
    return safe_query(query, context)


class TurnRunner:
    def __init__(
        self,
        chats,
        adapter,
        mcp,
        dispatcher,
        dedup,
        data_dir,
        emit,
        proposals=None,
        *,
        cancelled=lambda: False,
    ):
        self.chats, self.adapter, self.mcp = chats, adapter, mcp
        self.dispatcher, self.dedup, self.data_dir = dispatcher, dedup, data_dir
        self.emit, self.proposals = emit, proposals
        self.contexts = ContextBuilder(chats)
        self.cancelled = cancelled

    def check_cancelled(self):
        if self.cancelled():
            raise asyncio.CancelledError

    def data_version(self, name, context):
        if name == "rag_search":
            try:
                return IndexStore(self.data_dir).active()["knowledge_version"]
            except AppError:
                return "unavailable"
        if CATEGORIES.get(name) == "sql":
            return self.chats._rows("SELECT COALESCE(MAX(event_id),0) FROM outbox_events")[0][
                0
            ], self.chats._rows("SELECT COUNT(*) FROM outbox_events WHERE synced_at IS NULL")[0][0]
        if name == "search_web":
            return context.turn_id
        return context.scope_version

    async def execute(self, turn):
        context = turn.context
        sources = {}
        for reference in context.references:
            value = reference_source(reference)
            sources[value["source_id"]] = value
        tools = await self.mcp.model_tools()
        usage, models, partial = [], [], []
        calls_used = 0
        searched = False
        branch_slots = asyncio.Semaphore(4)

        async def invoke(call):
            name, arguments = call["name"], call["arguments"]
            invocation_id = new_id()
            digest = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
            invocation = ToolInvocation(
                invocation_id=invocation_id,
                turn_id=context.turn_id,
                provider_call_id=call["call_id"],
                tool_name=name,
                arguments_hash=digest,
                state="RUNNING",
            )

            def save(value):
                self.chats.store._write(
                    lambda c: c.execute(
                        "INSERT INTO tool_invocations VALUES(?,?,?) ON CONFLICT(invocation_id) "
                        "DO UPDATE SET payload=excluded.payload",
                        (value.invocation_id, value.turn_id, value.model_dump_json()),
                    )
                )

            await asyncio.to_thread(save, invocation)
            self.emit({"kind": "tool", "context": context, "tool_name": name, "state": "RUNNING"})
            state = "miss"
            try:
                if name not in SCHEMAS:
                    raise AppError(ErrorCode.INVALID_ARGUMENT)
                SCHEMAS[name].model_validate(arguments)
                # Check revocation even when an authorized cached result exists.
                active = {r.reference_id for r in self.chats.references(context.conversation_id)}
                if not {r.reference_id for r in context.references} <= active:
                    raise AppError(ErrorCode.ACCESS_DENIED)
                if name == "read_local_file":
                    reference = next(
                        (
                            r
                            for r in context.references
                            if r.reference_id == arguments.get("file_ref_id") and r.kind == "file"
                        ),
                        None,
                    )
                    if reference is None:
                        raise AppError(ErrorCode.ACCESS_DENIED)
                    try:
                        if (
                            FileFingerprint.from_path(Path(reference.resolved_path))
                            != reference.fingerprint
                        ):
                            raise AppError(ErrorCode.FILE_CHANGED)
                    except OSError as error:
                        raise AppError(ErrorCode.FILE_CHANGED) from error
                key = cache_key(context, name, arguments, self.data_version(name, context))

                async def backend():
                    async with branch_slots:
                        return await self.dispatcher.submit(
                            CATEGORIES[name],
                            lambda: self.mcp.call(name, arguments, context, invocation_id),
                            context.deadline_at,
                        )

                result, state = await self.dedup.call(key, backend, context.deadline_at)
                self.check_cancelled()
            except asyncio.CancelledError:
                await asyncio.to_thread(save, invocation.model_copy(update={"state": "CANCELLED"}))
                raise
            except Exception as error:
                code = (
                    error.info.code if isinstance(error, AppError) else ErrorCode.INVALID_ARGUMENT
                )
                result = {"ok": False, "data": None, "sources": [], "error": {"code": code}}
            result["sources"] = [source_with_id(s) for s in result.get("sources", [])]
            for source in result["sources"]:
                sources[source["source_id"]] = source
            # A merged/cache subscriber gets its own call identity, never the first caller's IDs.
            result["meta"] = {
                "instance_id": context.instance_id,
                "conversation_id": context.conversation_id,
                "turn_id": context.turn_id,
                "trace_id": context.trace_id,
                "invocation_id": invocation_id,
            }
            final = invocation.model_copy(
                update={
                    "state": "SUCCEEDED" if result["ok"] else "FAILED",
                    "cache_state": state,
                    "result_json": json.dumps(result, ensure_ascii=False),
                }
            )
            await asyncio.to_thread(save, final)
            self.emit(
                {
                    "kind": "tool",
                    "context": context,
                    "tool_name": name,
                    "state": final.state,
                    "cache_state": state,
                }
            )
            return {
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": json.dumps(result, ensure_ascii=False),
            }, result

        def delta(text):
            if self.cancelled():
                return
            partial.append(text)
            self.emit({"kind": "delta", "context": context, "text": text})

        try:
            for _ in range(8):
                self.check_cancelled()
                items = await asyncio.to_thread(self.contexts.build, context, tools)
                response = await self.adapter.respond(
                    items, tools, delta, max_output_tokens=self.contexts.output_budget
                )
                usage.append(response.usage)
                if response.model:
                    models.append(response.model)
                self.check_cancelled()
                if response.calls:
                    if calls_used + len(response.calls) > 16:
                        raise AppError(ErrorCode.TURN_LIMIT_REACHED)
                    calls_used += len(response.calls)
                    results = await asyncio.gather(*(invoke(call) for call in response.calls))
                    provider = list(response.output)
                    outputs = [item for item, _ in results]
                    searched = searched or any(c["name"] == "search_web" for c in response.calls)
                    needs_search = any(
                        needs_evidence_search(call["name"], result)
                        for call, (_, result) in zip(response.calls, results, strict=True)
                    )
                    if needs_search and not searched:
                        question = next(
                            m.text
                            for m in self.chats.messages(context.conversation_id)
                            if m.turn_id == context.turn_id and m.role == "user"
                        )
                        query = evidence_search_query(question, context)
                        if calls_used >= 16:
                            raise AppError(ErrorCode.TURN_LIMIT_REACHED)
                        synthetic = {
                            "type": "function_call",
                            "call_id": "host-search-" + new_id(),
                            "name": "search_web",
                            "arguments": json.dumps({"query": query, "count": 5}),
                        }
                        try:
                            output, _ = await invoke(
                                {**synthetic, "arguments": {"query": query, "count": 5}}
                            )
                        except BaseException:
                            await asyncio.to_thread(
                                self.chats.append,
                                context.conversation_id,
                                context.turn_id,
                                "assistant",
                                response.text,
                                provider + outputs,
                                list(sources.values()),
                            )
                            raise
                        calls_used += 1
                        searched = True
                        # Keep the host call in the original assistant's tool batch.
                        # A separate assistant tool batch has no provider reasoning
                        # and is rejected by DeepSeek's thinking-mode continuation.
                        provider.append(synthetic)
                        outputs.append(output)
                    await asyncio.to_thread(
                        self.chats.append,
                        context.conversation_id,
                        context.turn_id,
                        "assistant",
                        response.text,
                        provider + outputs,
                        list(sources.values()),
                    )
                    partial.clear()
                    continue
                if response.incomplete:
                    raise AppError(ErrorCode.TURN_LIMIT_REACHED)
                if not response.text.strip():
                    raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                await asyncio.to_thread(
                    self.chats.append,
                    context.conversation_id,
                    context.turn_id,
                    "assistant",
                    response.text,
                    list(response.output),
                    list(sources.values()),
                )
                if self.proposals:
                    self.check_cancelled()
                    try:
                        proposal = await asyncio.to_thread(
                            self.proposals.from_answer,
                            context,
                            response.text,
                            list(sources.values()),
                        )
                        if proposal:
                            self.emit(
                                {"kind": "proposal", "context": context, "proposal": proposal}
                            )
                    except AppError:
                        self.emit({"kind": "proposal_invalid", "context": context})
                return usage, tuple(models)
            raise AppError(ErrorCode.TURN_LIMIT_REACHED)
        except BaseException:
            if partial:
                await asyncio.to_thread(
                    self.chats.append,
                    context.conversation_id,
                    context.turn_id,
                    "assistant",
                    "".join(partial) + "\n（本轮未完成）",
                    (),
                    list(sources.values()),
                )
            raise
        finally:
            self.last_usage = usage
            self.last_models = tuple(models)
