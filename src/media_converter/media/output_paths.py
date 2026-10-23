import os
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from uuid import UUID

from media_converter.common.errors import AppError, ErrorCode


def safe_component(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    if not value:
        value = "未命名"
    if value.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(prefix + str(number) for prefix in ("COM", "LPT") for number in range(1, 10)),
    }:
        value = "_" + value
    return value


def path_key(path):
    return os.path.normcase(str(path.resolve()))


def contained_path(root: Path, candidate: Path) -> Path:
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved == root.resolve():
        raise AppError(ErrorCode.ACCESS_DENIED)
    return resolved


def available_path(candidate: Path, source: Path, reserved=()) -> Path:
    for number in range(10000):
        option = (
            candidate
            if number == 0
            else candidate.with_name(f"{candidate.stem} ({number}){candidate.suffix}")
        )
        if (
            path_key(option) != path_key(source)
            and path_key(option) not in reserved
            and not option.exists()
        ):
            return option
    raise AppError(ErrorCode.ACCESS_DENIED)


@dataclass(frozen=True)
class OutputPaths:
    root: Path
    temporary: Path
    final: Path


def plan_output_paths(asset, root, settings, attempt_id: str, reserved=()) -> OutputPaths:
    try:
        UUID(attempt_id)
    except ValueError as error:
        raise AppError(ErrorCode.INVALID_ARGUMENT) from error
    source = asset.resolved_path.resolve()
    relative = PureWindowsPath(asset.relative_path)
    if relative.drive or relative.is_absolute() or ".." in relative.parts:
        raise AppError(ErrorCode.ACCESS_DENIED)
    if settings.output_mode == "beside_source":
        base = source.parent / "转换结果"
        if not base.resolve().is_relative_to(source.parent):
            raise AppError(ErrorCode.ACCESS_DENIED)
        directory = base
    else:
        if settings.output_dir is None or not settings.output_dir.is_absolute():
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        base = settings.output_dir.resolve()
        directory = base
        if settings.preserve_hierarchy:
            group = safe_component(root.display_group) + "-" + root.root_id[:8]
            directory = base / group
            for part in relative.parts[:-1]:
                directory /= safe_component(part)
    final = contained_path(base, directory / f"{safe_component(source.stem)}.{settings.container}")
    final = available_path(final, source, reserved)
    temporary = (
        final.parent
        / f".media-converter-{attempt_id}"
        / (f"{final.stem}.{attempt_id}.partial.{settings.container}")
    )
    return OutputPaths(base.resolve(), contained_path(base, temporary), final)
