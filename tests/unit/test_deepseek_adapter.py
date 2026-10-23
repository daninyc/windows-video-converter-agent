import json

import httpx
import pytest

from media_converter.agent.deepseek_adapter import DeepSeekAdapter, SSEParser, normalize_response
from media_converter.common.errors import AppError, ErrorCode
from media_converter.services.config import APIConfig, ConfigService

pytestmark = pytest.mark.unit


def test_simulated_crlf_split_and_repeated_sequence_rejected():
    parser = SSEParser()
    source = 'data: {"type":"response.created","sequence_number":0}\r\n\r\n'
    received = []
    for character in source:
        received.extend(parser.feed(character))
    assert len(received) == 1
    with pytest.raises(AppError) as error:
        parser.feed(source)
    assert error.value.info.code == ErrorCode.PROTOCOL_MISMATCH


def test_simulated_split_sse_and_function_pairing():
    parser = SSEParser()
    source = (
        "event: response.output_text.delta\ndata: "
        '{"type":"response.output_text.delta","sequence_number":0,"delta":"中文"}\n\n'
    )
    received = []
    for character in source:
        received.extend(parser.feed(character))
    assert received[0]["delta"] == "中文"
    response = normalize_response(
        {
            "model": "returned-model",
            "output": [
                {
                    "type": "reasoning",
                    "content": [{"type": "reasoning_text", "text": "opaque reasoning"}],
                },
                {
                    "type": "function_call",
                    "call_id": "second",
                    "name": "rag_search",
                    "arguments": '{"query":"mp4"}',
                },
                {
                    "type": "function_call",
                    "call_id": "first",
                    "name": "search_web",
                    "arguments": '{"query":"webm"}',
                },
            ],
        }
    )
    assert [c["call_id"] for c in response.calls] == ["second", "first"]
    assert response.usage is None and response.output[0]["type"] == "reasoning"
    with pytest.raises(AppError):
        normalize_response(
            {
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "x",
                        "name": "rag_search",
                        "arguments": "[]",
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    "status,code", [(401, "AUTH_FAILED"), (402, "QUOTA_EXHAUSTED"), (429, "RATE_LIMITED")]
)
async def test_simulated_http_errors_do_not_expose_keys(tmp_path, status, code):
    service = ConfigService(tmp_path)
    service.save(APIConfig(), "sentinel-online-key")
    adapter = DeepSeekAdapter(
        service,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(status, json={"error": "sentinel-online-key"})
        ),
    )
    with pytest.raises(AppError) as error:
        await adapter.respond([], [])
    assert error.value.info.code == ErrorCode(code)
    assert "sentinel" not in str(error.value)


async def test_simulated_complete_stream_and_broken_stream_not_replayed(tmp_path):
    service = ConfigService(tmp_path)
    service.save(APIConfig(), "sentinel")
    terminal = {
        "type": "response.completed",
        "sequence_number": 1,
        "response": {
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "完成"}],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 2},
            "model": "actual-model",
        },
    }
    content = (
        'data: {"type":"response.output_text.delta","sequence_number":0,"delta":"完成"}\n\n'
        + "data: "
        + json.dumps(terminal)
        + "\n\n"
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=content)

    adapter = DeepSeekAdapter(service, transport=httpx.MockTransport(handler))
    deltas = []
    result = await adapter.respond([], [], deltas.append)
    assert result.text == "完成" and result.usage["output_tokens"] == 2 and deltas == ["完成"]
    content = content.split("data: " + json.dumps(terminal))[0]
    with pytest.raises(AppError):
        await adapter.respond([], [])
    assert len(requests) == 2
