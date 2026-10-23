from dataclasses import dataclass

from pydantic import ValidationError

from media_converter.media.models import ConversionSettings

DEFAULT_ENCODERS = {
    "mp4": ("libx264", "aac", 23),
    "mkv": ("libx264", "aac", 23),
    "webm": ("libvpx-vp9", "libopus", 32),
}
VIDEO_ENCODERS = {"mp4": ("libx264",), "mkv": ("libx264", "libvpx-vp9"), "webm": ("libvpx-vp9",)}
AUDIO_ENCODERS = {
    "mp4": ("auto", "aac", "copy"),
    "mkv": ("auto", "aac", "libopus", "copy"),
    "webm": ("auto", "libopus", "copy"),
}


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


@dataclass(frozen=True)
class SettingsValidation:
    settings: ConversionSettings | None
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self):
        return not self.issues


class SettingsService:
    def __init__(self, capabilities):
        self.capabilities = capabilities

    def validate(self, value, *, require_output=False) -> SettingsValidation:
        try:
            settings = ConversionSettings.model_validate(value)
        except ValidationError as error:
            return SettingsValidation(
                None,
                tuple(
                    ValidationIssue(
                        ".".join(map(str, item["loc"])) or "quality_mode",
                        "请输入有效的数值，质量模式与码率模式不能同时启用",
                    )
                    for item in error.errors(include_input=False)
                ),
            )
        issues = []

        def issue(field, message):
            issues.append(ValidationIssue(field, message))

        if settings.video_encoder not in VIDEO_ENCODERS[settings.container]:
            issue("video_encoder", "视频编码与目标格式不匹配")
        elif settings.video_encoder not in self.capabilities.encoders:
            issue("video_encoder", "本机缺少选定的视频编码器")
        if settings.audio_encoder not in AUDIO_ENCODERS[settings.container]:
            issue("audio_encoder", "音频编码与目标格式不匹配")
        actual_audio = (
            DEFAULT_ENCODERS[settings.container][1]
            if settings.audio_encoder == "auto"
            else settings.audio_encoder
        )
        if actual_audio != "copy" and actual_audio not in self.capabilities.encoders:
            issue("audio_encoder", "本机缺少选定的音频编码器")
        muxer = "matroska" if settings.container == "mkv" else settings.container
        if muxer not in self.capabilities.muxers:
            issue("container", "本机缺少目标封装能力")
        limit = 63 if settings.video_encoder == "libvpx-vp9" else 51
        if settings.quality_mode == "crf" and not 0 <= settings.quality_value <= limit:
            issue("quality_value", f"此编码器 CRF 范围为 0–{limit}")
        if settings.resolution and (
            settings.resolution.width % 2 or settings.resolution.height % 2
        ):
            issue("resolution", "目标尺寸的宽高须为正偶数，画面会按比例缩放")
        if settings.output_mode == "beside_source" and settings.preserve_hierarchy:
            issue("preserve_hierarchy", "源文件旁保存不使用来源层级选项")
        if require_output and settings.output_mode == "unified":
            if settings.output_dir is None or not settings.output_dir.is_absolute():
                issue("output_dir", "请选择绝对路径的输出目录")
            elif settings.output_dir.exists() and not settings.output_dir.is_dir():
                issue("output_dir", "输出位置必须是文件夹")
        return SettingsValidation(settings, tuple(issues))

    def update(self, current: ConversionSettings, patch: dict) -> SettingsValidation:
        data = current.model_dump()
        data.update(patch)
        data["settings_version"] = current.settings_version
        if data != current.model_dump():
            data["settings_version"] += 1
        return self.validate(data)
