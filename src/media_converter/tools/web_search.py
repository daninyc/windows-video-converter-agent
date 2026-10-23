import re
from datetime import UTC, datetime
from urllib.parse import urlsplit

from media_converter.agent.deepseek_adapter import http_error
from media_converter.common.errors import AppError, ErrorCode


def safe_query(query, context, secrets=()):
    if not query.strip() or len(query) > 128 or len(query.splitlines()) > 1:
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    if re.search(
        r"(?i)([a-z]:[\\/]|\\\\|/users/|/home/|bearer\s|api[_-]?key|password|sk-[a-z0-9]{8,}|[a-z0-9]{32,})",
        query,
    ):
        raise AppError(ErrorCode.ACCESS_DENIED)
    if any(secret and secret in query for secret in secrets):
        raise AppError(ErrorCode.ACCESS_DENIED)
    for reference in context.references:
        if reference.resolved_path and reference.resolved_path.casefold() in query.casefold():
            raise AppError(ErrorCode.ACCESS_DENIED)
        if reference.kind == "file" and reference.label.casefold() in query.casefold():
            raise AppError(ErrorCode.ACCESS_DENIED)
    return query.strip()


class WebSearch:
    def __init__(self, config_service, *, transport=None):
        self.config_service, self.transport = config_service, transport

    async def search(self, arguments, context):
        import httpx

        config, key = self.config_service.request_config()
        query = safe_query(arguments.query, context, (key,))
        try:
            async with httpx.AsyncClient(
                transport=self.transport, timeout=20, follow_redirects=False
            ) as client:
                result = await client.post(
                    config.base_url.removesuffix("/v1") + "/v1/tools/search",
                    headers={"Authorization": "Bearer " + key},
                    json={"query": query, "count": arguments.count, "need_content": False},
                )
                if result.status_code != 200:
                    failure = http_error(result.status_code)
                    self.config_service.mark_unavailable(config.version, failure.info.code)
                    raise failure
                data = result.json()
            if not isinstance(data.get("results"), list):
                raise AppError(ErrorCode.PROTOCOL_MISMATCH)
            sources = []
            for item in data["results"][: arguments.count]:
                snippet = item.get("snippet") or item.get("summary") or ""
                title = item.get("title", "")
                if not isinstance(snippet, str) or not isinstance(title, str):
                    raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                url = urlsplit(item.get("url", ""))
                if (
                    url.scheme not in {"http", "https"}
                    or not url.hostname
                    or url.username
                    or url.password
                ):
                    raise AppError(ErrorCode.PROTOCOL_MISMATCH)
                sources.append(
                    {
                        "title": title.strip() or url.hostname,
                        "title_fallback": not bool(title.strip()),
                        "url": item["url"],
                        "snippet": snippet[:400],
                        "snippet_truncated": len(snippet) > 400,
                        "published_at": item.get("date"),
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    }
                )
            return {"results": sources, "empty": not sources}
        except httpx.TimeoutException as error:
            raise AppError(ErrorCode.TIMEOUT) from error
        except (httpx.HTTPError, ValueError) as error:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from error
