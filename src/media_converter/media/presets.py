from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import ConversionSettings
from media_converter.media.settings import SettingsService, ValidationIssue


@dataclass(frozen=True)
class RestoredSettings:
    settings: ConversionSettings | None
    issues: tuple[ValidationIssue, ...]


class PresetService:
    def __init__(self, store, capabilities):
        self.store = store
        self.validation = SettingsService(capabilities)

    def save(self, name, settings):
        name = name.strip()
        if not name or len(name) > 80 or not self.validation.validate(settings).valid:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        preset_id = str(uuid5(NAMESPACE_URL, "user-preset:" + name.casefold()))
        self.store.save_preset(preset_id, name, settings)
        return preset_id

    def list(self):
        return self.store.list_presets()

    def load(self, preset_id):
        record = self.store.get_preset(preset_id)
        if record is None:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        result = self.validation.validate(record["settings"])
        return RestoredSettings(result.settings if result.valid else None, result.issues)

    def remember(self, settings):
        if not self.validation.validate(settings, require_output=True).valid:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        self.store.save_settings(settings)

    def restore(self):
        try:
            settings = self.store.get_settings()
        except (ValidationError, ValueError):
            return RestoredSettings(
                None, (ValidationIssue("settings", "上次保存的设置无法读取，请重新配置"),)
            )
        if settings is None:
            return RestoredSettings(ConversionSettings(), ())
        result = self.validation.validate(settings, require_output=True)
        return RestoredSettings(settings, result.issues)


def open_output_location(output_path: str | Path):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    directory = Path(output_path).resolve().parent
    if not directory.is_dir():
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    return directory
