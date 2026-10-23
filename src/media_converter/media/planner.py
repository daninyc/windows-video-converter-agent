from fractions import Fraction

from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.compatibility import COPY_AUDIO, COPY_SUBTITLES, output_default
from media_converter.media.models import ConversionPlan, FileFingerprint, LossItem, StreamMapping
from media_converter.media.output_paths import path_key, plan_output_paths
from media_converter.media.settings import DEFAULT_ENCODERS, SettingsService


def output_dimensions(asset, settings):
    width, height = asset.width, asset.height
    if not width or not height or asset.rotation_deg not in (None, 0, 90, 180, 270):
        raise AppError(ErrorCode.INCOMPATIBLE_STREAM)
    sar = dict(asset.color_info).get("sample_aspect_ratio", "1:1")
    try:
        pixel_ratio = Fraction(sar.replace(":", "/"))
        if pixel_ratio <= 0:
            pixel_ratio = Fraction(1)
    except (ValueError, ZeroDivisionError):
        pixel_ratio = Fraction(1)
    if asset.rotation_deg in (90, 270):
        width, height = height, width
        pixel_ratio = 1 / pixel_ratio
    if settings.resolution:
        ratio = width * pixel_ratio / height
        target = settings.resolution
        scaled_width = min(Fraction(target.width), target.height * ratio)
        scaled_height = min(Fraction(target.height), target.width / ratio)
        return (
            max(2, int(scaled_width / 2 + Fraction(1, 2)) * 2),
            max(2, int(scaled_height / 2 + Fraction(1, 2)) * 2),
        )
    return (width + 1) // 2 * 2, (height + 1) // 2 * 2


class ConversionPlanner:
    def __init__(self, capabilities):
        self.capabilities = capabilities
        self.settings_service = SettingsService(capabilities)

    def plan(self, settings, assets, roots) -> tuple[ConversionPlan, ...]:
        validation = self.settings_service.validate(settings, require_output=True)
        if not validation.valid:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        reserved = set()
        plans = []
        for asset in assets:
            plan = self.plan_one(settings, asset, roots[asset.root_id], reserved=reserved)
            reserved.add(path_key(plan.final_path))
            plans.append(plan)
        return tuple(plans)

    def plan_one(self, settings, asset, root, *, reserved=()):
        validation = self.settings_service.validate(settings, require_output=True)
        if not validation.valid or asset.probe_status != "succeeded":
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        if FileFingerprint.from_path(asset.resolved_path) != asset.fingerprint:
            raise AppError(ErrorCode.FILE_CHANGED)
        videos = [
            stream
            for stream in asset.streams
            if stream.kind == "video" and not stream.attached_picture
        ]
        if len(videos) != 1:
            raise AppError(ErrorCode.INCOMPATIBLE_STREAM)
        colors = dict(asset.color_info)
        if colors.get("color_transfer") in {"smpte2084", "arib-std-b67"} or colors.get(
            "hdr_metadata"
        ):
            # SDR/yuv420p output cannot silently preserve HDR or Dolby Vision fidelity.
            raise AppError(ErrorCode.INCOMPATIBLE_STREAM)
        output_dimensions(asset, settings)
        mappings = [
            StreamMapping(
                source_index=videos[0].stream_index,
                kind="video",
                action="transcode",
                encoder=settings.video_encoder,
            )
        ]
        losses = []
        for kind in ("audio", "subtitle"):
            for stream in asset.streams:
                if stream.kind != kind:
                    continue
                if kind == "subtitle":
                    if stream.codec in COPY_SUBTITLES[settings.container]:
                        mappings.append(
                            StreamMapping(
                                source_index=stream.stream_index, kind=kind, action="copy"
                            )
                        )
                    else:
                        losses.append(
                            LossItem(
                                stream_index=stream.stream_index,
                                kind=kind,
                                reason=(
                                    f"字幕 {stream.codec or '未知编码'} 未纳入本应用的 "
                                    f"{settings.container.upper()} 保留规则"
                                ),
                            )
                        )
                else:
                    compatible = stream.codec in COPY_AUDIO[settings.container]
                    encoder = settings.audio_encoder
                    copy = encoder in ("auto", "copy") and compatible
                    if encoder == "copy" and not compatible:
                        losses.append(
                            LossItem(
                                stream_index=stream.stream_index,
                                kind=kind,
                                reason=(
                                    f"音频 {stream.codec or '未知编码'} 无法按仅复制规则写入 "
                                    f"{settings.container.upper()}"
                                ),
                            )
                        )
                    else:
                        if encoder == "auto":
                            encoder = DEFAULT_ENCODERS[settings.container][1]
                        mappings.append(
                            StreamMapping(
                                source_index=stream.stream_index,
                                kind=kind,
                                action="copy" if copy else "transcode",
                                encoder=None if copy else encoder,
                            )
                        )
        mapped = {mapping.source_index for mapping in mappings}
        accounted = mapped | {loss.stream_index for loss in losses}
        for stream in asset.streams:
            if stream.stream_index not in accounted:
                losses.append(
                    LossItem(
                        stream_index=stream.stream_index,
                        kind=stream.kind,
                        reason="封面、附件或数据流不属于本次视频输出，确认后才丢弃",
                    )
                )
        attempt_id = new_id()
        paths = plan_output_paths(asset, root, settings, attempt_id, reserved)
        args = [
            "-hide_banner",
            "-n",
            "-progress",
            "pipe:1",
            "-nostats",
            "-i",
            str(asset.resolved_path),
        ]
        for mapping in mappings:
            args += ["-map", f"0:{mapping.source_index}"]
        args += ["-c:v:0", settings.video_encoder, "-threads:v:0", "2", "-pix_fmt:v:0", "yuv420p"]
        if settings.quality_mode == "crf":
            args += ["-crf:v:0", str(settings.quality_value)]
            if settings.video_encoder == "libvpx-vp9":
                args += ["-b:v:0", "0"]
        else:
            args += ["-b:v:0", str(settings.video_bitrate_bps)]
        if settings.resolution:
            size = settings.resolution
            args += [
                "-vf",
                f"scale={size.width}:{size.height}:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1",
            ]
        elif asset.width % 2 or asset.height % 2:
            args += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
        if settings.frame_rate:
            rate = settings.frame_rate
            args += ["-r:v:0", f"{rate.numerator}/{rate.denominator}", "-fps_mode:v:0", "cfr"]
        else:
            args += ["-fps_mode:v:0", "passthrough"]
        counters = {"video": 0, "audio": 0, "subtitle": 0}
        for mapping in mappings:
            index = counters[mapping.kind]
            counters[mapping.kind] += 1
            letter = {"video": "v", "audio": "a", "subtitle": "s"}[mapping.kind]
            specifier = f"{letter}:{index}"
            source = next(
                stream for stream in asset.streams if stream.stream_index == mapping.source_index
            )
            if mapping.kind != "video":
                args += [f"-c:{specifier}", "copy" if mapping.action == "copy" else mapping.encoder]
            if mapping.kind == "audio" and mapping.action != "copy" and settings.audio_bitrate_bps:
                args += [f"-b:{specifier}", str(settings.audio_bitrate_bps)]
            if source.language:
                args += [f"-metadata:s:{specifier}", f"language={source.language}"]
            retained = [
                stream
                for stream in asset.streams
                if any(
                    other.source_index == stream.stream_index and other.kind == mapping.kind
                    for other in mappings
                )
            ]
            flags = (
                ["default"]
                if output_default(source, settings.container, mapping.kind, index, retained)
                else []
            )
            if "forced" in source.disposition:
                flags.append("forced")
            args += [f"-disposition:{specifier}", "+".join(flags) if flags else "0"]
        args += [
            "-metadata:s:v:0",
            "rotate=0",
            "-f",
            "matroska" if settings.container == "mkv" else settings.container,
            str(paths.temporary),
        ]
        return ConversionPlan(
            asset_id=asset.asset_id,
            attempt_id=attempt_id,
            source_path=asset.resolved_path,
            source_fingerprint=asset.fingerprint,
            source_asset=asset,
            settings_snapshot=settings,
            stream_mapping=tuple(mappings),
            loss_items=tuple(losses),
            ffmpeg_args=tuple(args),
            temporary_path=paths.temporary,
            final_path=paths.final,
            output_root=paths.root,
        )
