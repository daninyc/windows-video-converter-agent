import httpx
import pytest

from media_converter.common.errors import AppError
from media_converter.services.config import APIConfig, ConfigService
from media_converter.tools.schemas import SearchQuery
from media_converter.tools.web_search import WebSearch, safe_query

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("has_snippet", [False, True])
async def test_search_context_is_bounded_and_prefers_short_provider_snippet(tmp_path, has_snippet):
    class Context:
        references = ()

    service = ConfigService(tmp_path)
    service.save(APIConfig(), "sentinel")
    item = {"title": "source", "url": "https://ffmpeg.org/ffmpeg.html", "summary": "长" * 2000}
    if has_snippet:
        item["snippet"] = "提供方短摘要"
    search = WebSearch(
        service,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"results": [item]})
        ),
    )
    result = (await search.search(SearchQuery(query="FFmpeg"), Context()))["results"][0]
    assert result["snippet"] == ("提供方短摘要" if has_snippet else "长" * 400)
    assert result["snippet_truncated"] is (not has_snippet)
    assert result["url"] == item["url"]


async def test_simulated_search_empty_errors_and_real_source_fields(tmp_path):
    class Context:
        references = ()

    context = Context()
    for query in [r"D:\private\video.mp4", "api_key=secret", "log\nlog"]:
        with pytest.raises(AppError):
            safe_query(query, context)
    service = ConfigService(tmp_path)
    service.save(APIConfig(), "sentinel")
    responses = [
        httpx.Response(200, json={"results": []}),
        httpx.Response(401),
        httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "official",
                        "url": "https://ffmpeg.org/ffmpeg.html",
                        "summary": "source",
                    }
                ]
            },
        ),
    ]
    search = WebSearch(service, transport=httpx.MockTransport(lambda r: responses.pop(0)))
    assert (await search.search(SearchQuery(query="libx264"), context))["empty"]
    with pytest.raises(AppError):
        await search.search(SearchQuery(query="libx264"), context)
    # Authentication failure blocks this configuration until explicit reconfiguration.
    service.save(service.load())
    result = await search.search(SearchQuery(query="libx264"), context)
    assert result["results"][0]["url"] == "https://ffmpeg.org/ffmpeg.html"


@pytest.mark.parametrize("title", ["", "  "])
async def test_untitled_search_hit_uses_actual_hostname_without_losing_other_sources(
    tmp_path, title
):
    class Context:
        references = ()

    service = ConfigService(tmp_path)
    service.save(APIConfig(), "sentinel")
    items = [
        {"title": "FFmpeg", "url": "https://ffmpeg.org/ffmpeg.html", "snippet": "manual"},
        {
            "title": title,
            "url": "https://raw.githubusercontent.com/example/note.md",
            "snippet": "note",
        },
    ]
    search = WebSearch(
        service,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results": items})),
    )
    results = (await search.search(SearchQuery(query="FFmpeg xyzvideo"), Context()))["results"]
    assert len(results) == 2
    assert results[0]["title"] == "FFmpeg" and results[0]["title_fallback"] is False
    assert results[1]["title"] == "raw.githubusercontent.com"
    assert results[1]["title_fallback"] is True
    assert results[1]["url"] == items[1]["url"]


async def test_untitled_result_still_rejects_credential_url(tmp_path):
    class Context:
        references = ()

    service = ConfigService(tmp_path)
    service.save(APIConfig(), "sentinel")
    search = WebSearch(
        service,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"results": [{"title": "", "url": "https://user:pass@example.com"}]}
            )
        ),
    )
    with pytest.raises(AppError) as failure:
        await search.search(SearchQuery(query="FFmpeg"), Context())
    assert failure.value.info.code == "PROTOCOL_MISMATCH"
