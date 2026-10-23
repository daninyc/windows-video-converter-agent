import os
import sys
from dataclasses import dataclass
from pathlib import Path


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path

    @classmethod
    def from_argument(cls, data_dir: str | Path | None = None) -> "AppPaths":
        selected = data_dir or os.environ.get("MEDIA_CONVERTER_DATA_DIR")
        return cls(Path(selected).resolve() if selected else application_root() / "data")

    def ensure(self) -> "AppPaths":
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self
