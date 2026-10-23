from typing import Literal

from pydantic import Field

from media_converter.media.models import FrozenModel


class RagQuery(FrozenModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=5)


class RulesQuery(FrozenModel):
    rule_kind: str | None = Field(
        default=None,
        max_length=80,
        description="精确规则分类，内置值 container、subtitle、quality、error；不确定时省略。",
    )
    format: str | None = Field(
        default=None,
        max_length=40,
        description="精确封装名，如 mp4、webm、mkv；不确定其他字段时只按此项查询。",
    )
    codec: str | None = Field(
        default=None,
        max_length=80,
        description=(
            "精确匹配规则字段，如 h264、vp9、mov_text、libx264；"
            "编码器名不等于编码名，不确定时省略。"
        ),
    )
    error_code: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=20, ge=1, le=100)


class PresetsQuery(FrozenModel):
    preset_name: str | None = Field(default=None, max_length=100)
    container: Literal["mp4", "mkv", "webm"] | None = None
    limit: int = Field(default=20, ge=1, le=100)


class HistoryQuery(FrozenModel):
    task_id: str | None = Field(default=None, max_length=64)
    status: (
        Literal["SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED", "RUNNING", "QUEUED"] | None
    ) = None
    since: str | None = Field(default=None, max_length=40)
    until: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=20, ge=1, le=100)


class FileQuery(FrozenModel):
    file_ref_id: str = Field(
        min_length=1,
        max_length=64,
        description=(
            "本轮固定事实 references 中的 file_ref_id，值为授权 UUID（同 reference_id）。"
            "不能传 src-开头的 source_id、文件名或路径。"
        ),
    )
    offset: int = Field(default=0, ge=0)
    page_start: int = Field(default=1, ge=1)
    page_count: int = Field(default=20, ge=1, le=20)
    block_start: int = Field(default=0, ge=0)
    max_chars: int = Field(default=20000, ge=1, le=20000)
    cursor: str | None = Field(default=None, max_length=2048)


class SearchQuery(FrozenModel):
    query: str = Field(min_length=1, max_length=128)
    count: int = Field(default=5, ge=1, le=5)


SCHEMAS = {
    "rag_search": RagQuery,
    "lookup_technical_rules": RulesQuery,
    "list_conversion_presets": PresetsQuery,
    "query_conversion_history": HistoryQuery,
    "read_local_file": FileQuery,
    "search_web": SearchQuery,
}
CATEGORIES = {
    name: "sql"
    for name in ("lookup_technical_rules", "list_conversion_presets", "query_conversion_history")
}
CATEGORIES.update(rag_search="rag", read_local_file="file", search_web="search")
DESCRIPTIONS = {
    "rag_search": "检索内置知识，返回两路召回、融合、重排与可定位片段；证据不足时需进一步查证。",
    "lookup_technical_rules": "查询有来源的格式、编码和错误规则；仅接受固定过滤条件。",
    "list_conversion_presets": "查询当前实例的内置/用户转换预设并返回同步新鲜度。",
    "query_conversion_history": "查询当前实例授权任务历史；返回同步新鲜度，不接受 SQL。",
    "read_local_file": "只读本轮明确授权的 file_ref_id；返回位置、截断状态和续读游标。",
    "search_web": "本地依据不足、冲突或需核实最新信息时搜索；禁止包含本地路径、凭据和整段日志。",
}
