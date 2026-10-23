"""Pinned first-party component inventory. Missing release artifacts stay missing."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from media_converter.common.errors import AppError, ErrorCode


def relative_name(name):
    path = PurePosixPath(name.replace("\\", "/"))
    reserved = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(10)),
        *(f"LPT{i}" for i in range(10)),
    }
    if (
        path.is_absolute()
        or not path.parts
        or any(
            p in {".", ".."}
            or ":" in p
            or p.rstrip(" .") != p
            or p.split(".")[0].upper() in reserved
            for p in path.parts
        )
    ):
        raise AppError(ErrorCode.ACCESS_DENIED)
    return path.as_posix()


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    url: str
    digest: str
    size: int
    destination: str
    license: str
    algorithm: str = "sha256"
    archive: bool = False
    expanded_limit: int = 0
    adjacent_only: bool = False

    def __post_init__(self):
        relative_name(self.destination)
        if not re.fullmatch(r"[a-z0-9-]+", self.name):
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        parsed = urlsplit(self.url)
        if not (self.adjacent_only and not self.url) and (
            parsed.username
            or parsed.password
            or not (
                parsed.scheme == "https"
                or parsed.scheme == "http"
                and parsed.hostname == "127.0.0.1"
            )
        ):
            raise AppError(ErrorCode.ACCESS_DENIED)
        length = 64 if self.algorithm == "sha256" else 40
        if (
            self.algorithm not in {"sha256", "git-blob-sha1"}
            or not re.fullmatch(f"[0-9a-f]{{{length}}}", self.digest)
            or self.size <= 0
        ):
            raise AppError(ErrorCode.INVALID_ARGUMENT)


def file_matches(path, artifact):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != artifact.size:
        return False
    algorithm = "sha256" if artifact.algorithm == "sha256" else "sha1"
    digest = hashlib.new(algorithm)
    if algorithm == "sha1":
        digest.update(f"blob {artifact.size}\0".encode())
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest() == artifact.digest


def inventory():
    value = json.loads(Path(__file__).with_name("components.json").read_text("utf-8"))
    return [Artifact(**item) for item in value["artifacts"]]
