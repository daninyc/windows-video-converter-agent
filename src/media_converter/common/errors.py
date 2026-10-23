import asyncio
from concurrent.futures import CancelledError as FutureCancelledError
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from media_converter.common.context import CallContext


class ErrorCode(StrEnum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    ACCESS_DENIED = "ACCESS_DENIED"
    FILE_CHANGED = "FILE_CHANGED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    NO_EXTRACTABLE_TEXT = "NO_EXTRACTABLE_TEXT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    INCOMPATIBLE_STREAM = "INCOMPATIBLE_STREAM"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    QUEUE_FULL = "QUEUE_FULL"
    TURN_LIMIT_REACHED = "TURN_LIMIT_REACHED"
    MCP_DISCONNECTED = "MCP_DISCONNECTED"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    INVALID_STATE = "INVALID_STATE"
    PROCESS_FAILED = "PROCESS_FAILED"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    DISK_FULL = "DISK_FULL"
    STORE_WRITE_FAILED = "STORE_WRITE_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# Public text never comes from an external exception, command line or server response.
_POLICY = {
    ErrorCode.INVALID_ARGUMENT: (False, "参数不合法", "检查输入参数"),
    ErrorCode.ACCESS_DENIED: (False, "没有访问权限", "重新选择并授权引用"),
    ErrorCode.FILE_CHANGED: (False, "文件已变化", "重新选择文件"),
    ErrorCode.FILE_TOO_LARGE: (False, "文件或读取范围超限", "缩小范围"),
    ErrorCode.NO_EXTRACTABLE_TEXT: (False, "没有可提取的文字", "提供文字版文档"),
    ErrorCode.DEPENDENCY_UNAVAILABLE: (True, "依赖未就绪", "检查组件路径或本地服务"),
    ErrorCode.TIMEOUT: (True, "操作超时", "检查依赖后重试"),
    ErrorCode.RATE_LIMITED: (True, "请求受到限流", "稍后重试"),
    ErrorCode.AUTH_FAILED: (False, "认证失败", "在配置中检查凭据及有效期"),
    ErrorCode.QUOTA_EXHAUSTED: (False, "在线额度不足", "在提供方检查额度"),
    ErrorCode.INCOMPATIBLE_STREAM: (False, "轨道与输出不兼容", "调整格式或编码"),
    ErrorCode.CONSENT_REQUIRED: (False, "需要确认轨道丢失", "查看并确认本次转换计划"),
    ErrorCode.QUEUE_FULL: (True, "队列已满", "等待现有任务完成"),
    ErrorCode.TURN_LIMIT_REACHED: (False, "本轮调用已达上限", "缩小问题后开启新一轮"),
    ErrorCode.MCP_DISCONNECTED: (True, "工具连接中断", "检查工具组件后重试"),
    ErrorCode.PROTOCOL_MISMATCH: (False, "工具协议不兼容", "检查组件版本"),
    ErrorCode.INVALID_STATE: (False, "当前状态不允许此操作", "刷新任务状态"),
    ErrorCode.PROCESS_FAILED: (True, "外部进程执行失败", "查看错误摘要并检查组件"),
    ErrorCode.OUTPUT_INVALID: (False, "输出未通过验证", "检查源文件和输出参数后重试"),
    ErrorCode.DISK_FULL: (True, "输出磁盘空间不足", "释放空间或更换输出目录后重试"),
    ErrorCode.STORE_WRITE_FAILED: (
        True,
        "运行记录保存失败",
        "检查运行目录空间与权限；已发布结果会保留",
    ),
    ErrorCode.INTERNAL_ERROR: (False, "操作失败", "查看诊断记录后重试"),
}


@dataclass(frozen=True)
class ErrorInfo:
    code: ErrorCode
    message: str
    retryable: bool
    suggested_action: str


class AppError(Exception):
    def __init__(self, code: ErrorCode):
        retryable, message, action = _POLICY[code]
        self.info = ErrorInfo(code, message, retryable, action)
        super().__init__(message)


def normalize_error(error: BaseException) -> AppError:
    if isinstance(error, (asyncio.CancelledError, FutureCancelledError)):
        raise error
    if not isinstance(error, Exception):
        raise error
    if isinstance(error, AppError):
        return error
    if isinstance(error, TimeoutError):
        return AppError(ErrorCode.TIMEOUT)
    if isinstance(error, ImportError):
        return AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    return AppError(ErrorCode.INTERNAL_ERROR)


def result_envelope(
    context: CallContext,
    *,
    data: Any = None,
    error: BaseException | None = None,
    sources: tuple = (),
    data_version: str | None = None,
) -> dict:
    info = normalize_error(error).info if error is not None else None
    return {
        "ok": info is None,
        "data": data if info is None else None,
        "sources": list(sources),
        "error": asdict(info) if info else None,
        "meta": {**asdict(context), "data_version": data_version},
    }
