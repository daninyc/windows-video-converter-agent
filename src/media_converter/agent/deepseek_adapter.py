import json
from dataclasses import dataclass

from media_converter.common.errors import AppError, ErrorCode


def http_error(status):
    return AppError(
        {
            401: ErrorCode.AUTH_FAILED,
            403: ErrorCode.AUTH_FAILED,
            402: ErrorCode.QUOTA_EXHAUSTED,
            429: ErrorCode.RATE_LIMITED,
        }.get(status, ErrorCode.DEPENDENCY_UNAVAILABLE)
    )


class SSEParser:
    def __init__(self):
        self.buffer = ""
        self.last_sequence = -1

    def feed(self, text):
        self.buffer = (self.buffer + text).replace("\r\n", "\n")
        if len(self.buffer) > 2_000_000:
            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
        events = []
        while "\n\n" in self.buffer:
            block, self.buffer = self.buffer.split("\n\n", 1)
            data = "\n".join(
                line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")
            )
            if not data:
                continue
            try:
                event = json.loads(data)
                sequence = event.get("sequence_number")
                if sequence is not None:
                    if not isinstance(sequence, int) or sequence <= self.last_sequence:
                        raise ValueError("sequence")
                    self.last_sequence = sequence
                if not isinstance(event.get("type"), str):
                    raise ValueError("type")
                events.append(event)
            except (ValueError, TypeError, AttributeError) as error:
                raise AppError(ErrorCode.PROTOCOL_MISMATCH) from error
        return events


@dataclass(frozen=True)
class ModelResponse:
    text: str
    output: tuple[dict, ...]
    calls: tuple[dict, ...]
    usage: dict | None
    model: str | None
    incomplete: bool = False


def normalize_response(response):
    output = response.get("output", [])
    calls, texts, identifiers = [], [], set()
    if not isinstance(output, list):
        raise AppError(ErrorCode.PROTOCOL_MISMATCH)
    for item in output:
        if item.get("type") == "function_call":
            try:
                arguments = json.loads(item["arguments"])
                call_id = item["call_id"]
                if not isinstance(arguments, dict) or not call_id or call_id in identifiers:
                    raise ValueError("call")
                calls.append({"call_id": call_id, "name": item["name"], "arguments": arguments})
                identifiers.add(call_id)
            except (ValueError, KeyError, TypeError) as error:
                raise AppError(ErrorCode.PROTOCOL_MISMATCH) from error
        elif item.get("type") == "message":
            texts.extend(
                part.get("text", "")
                for part in item.get("content", [])
                if part.get("type") == "output_text"
            )
        elif item.get("type") != "reasoning":
            # No provider-native tool is permitted to bypass the MCP boundary.
            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
    usage = response.get("usage")
    if usage is not None and not isinstance(usage, dict):
        raise AppError(ErrorCode.PROTOCOL_MISMATCH)
    return ModelResponse(
        "".join(texts),
        tuple(output),
        tuple(calls),
        usage,
        response.get("model"),
        response.get("status") == "incomplete",
    )


class DeepSeekAdapter:
    def __init__(self, config_service, *, transport=None):
        self.config_service, self.transport = config_service, transport

    async def respond(self, items, tools, on_delta=lambda text: None, *, max_output_tokens=8192):
        import httpx

        config, key = self.config_service.request_config()
        body = {
            "model": config.model,
            "input": items,
            "tools": tools,
            "stream": True,
            "max_output_tokens": max_output_tokens,
            "tool_choice": "auto",
        }
        parser, terminal, total = SSEParser(), None, 0
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=config.timeout_seconds, follow_redirects=False
            ) as client:
                async with client.stream(
                    "POST",
                    config.base_url + "/responses",
                    headers={"Authorization": "Bearer " + key},
                    json=body,
                ) as response:
                    if response.status_code != 200:
                        failure = http_error(response.status_code)
                        self.config_service.mark_unavailable(config.version, failure.info.code)
                        raise failure
                    async for text in response.aiter_text():
                        total += len(text)
                        if total > 8_000_000:
                            raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                        for event in parser.feed(text):
                            kind = event["type"]
                            if kind == "response.output_text.delta":
                                on_delta(event.get("delta", ""))
                            elif kind in {"response.completed", "response.incomplete"}:
                                if terminal is not None:
                                    raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                                terminal = event.get("response")
                            elif kind in {"response.failed", "error"}:
                                raise AppError(ErrorCode.PROCESS_FAILED)
            if terminal is None or parser.buffer.strip():
                raise AppError(ErrorCode.PROTOCOL_MISMATCH)
            return normalize_response(terminal)
        except httpx.TimeoutException as error:
            raise AppError(ErrorCode.TIMEOUT) from error
        except httpx.HTTPError as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error

    async def connection_test(self):
        import httpx

        config, key = self.config_service.request_config(force=True)
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=10, follow_redirects=False
            ) as client:
                response = await client.get(
                    config.base_url + "/models", headers={"Authorization": "Bearer " + key}
                )
                if response.status_code != 200:
                    failure = http_error(response.status_code)
                    self.config_service.mark_unavailable(config.version, failure.info.code)
                    raise failure
                models = [item["id"] for item in response.json().get("data", [])]
                self.config_service.clear_unavailable(config.version)
                return {
                    "connected": True,
                    "configured_model_available": config.model in models,
                    "models": models,
                }
        except httpx.HTTPError as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
