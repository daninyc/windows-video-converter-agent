import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import FrozenModel
from media_converter.storage.credentials import CredentialStore


class APIConfig(FrozenModel):
    version: int = Field(default=1, ge=1)
    base_url: str = "https://api.deepseek.com"
    model: str = Field(default="deepseek-v4-pro", min_length=1, max_length=100)
    timeout_seconds: int = Field(default=120, ge=1, le=300)
    credential_ref: str | None = None

    @field_validator("base_url")
    @classmethod
    def check_url(cls, value):
        parsed = urlsplit(value)
        if (
            (
                parsed.scheme != "https"
                and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
            )
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("API 地址须为 HTTPS，且不含账号、查询参数或片段")
        return value.rstrip("/")


class ConfigService:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "api.json"
        self.credentials = CredentialStore(Path(data_dir) / "private")

    def load(self):
        try:
            return (
                APIConfig.model_validate_json(self.path.read_text(encoding="utf-8"))
                if self.path.exists()
                else APIConfig()
            )
        except (ValueError, OSError) as error:
            raise AppError(ErrorCode.INVALID_ARGUMENT) from error

    def save(self, config: APIConfig, key: str | None = None, *, clear=False):
        old = self.load()
        reference = self.credentials.save(key) if key else None if clear else old.credential_ref
        saved = APIConfig.model_validate(
            {**config.model_dump(), "version": old.version + 1, "credential_ref": reference}
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.partial")
        try:
            temporary.write_text(saved.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            if reference != old.credential_ref:
                self.credentials.clear(reference)
            raise
        if old.credential_ref != reference:
            self.credentials.clear(old.credential_ref)
        return saved

    def mark_unavailable(self, version, code):
        if code not in {ErrorCode.AUTH_FAILED, ErrorCode.QUOTA_EXHAUSTED}:
            return
        target = self.path.parent / f"api-blocked-{version}.json"
        temporary = target.with_suffix(f".{secrets.token_hex(8)}.partial")
        try:
            temporary.write_text(json.dumps({"version": version, "code": code}), encoding="utf-8")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def clear_unavailable(self, version):
        (self.path.parent / f"api-blocked-{version}.json").unlink(missing_ok=True)

    def request_config(self, *, force=False):
        config = self.load()
        marker = self.path.parent / f"api-blocked-{config.version}.json"
        if marker.exists() and not force:
            try:
                code = ErrorCode(json.loads(marker.read_text(encoding="utf-8"))["code"])
            except (OSError, ValueError, KeyError) as error:
                raise AppError(ErrorCode.AUTH_FAILED) from error
            raise AppError(code)
        return config, self.credentials.read(config.credential_ref)


def read_ai_components(data_dir):
    path = Path(data_dir) / "ai-components.json"
    if not path.is_file():
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    return json.loads(path.read_text(encoding="utf-8"))
