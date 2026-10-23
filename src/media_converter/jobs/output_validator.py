import json
from fractions import Fraction

from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.process import capture_process
from media_converter.media.compatibility import ENCODER_CODECS, output_default
from media_converter.media.planner import output_dimensions
from media_converter.media.probe import duration_us


class OutputValidator:
    def __init__(self, capabilities):
        self.capabilities = capabilities

    async def validate(self, plan):
        path = plan.temporary_path
        if not path.is_file() or path.stat().st_size == 0 or plan.source_asset is None:
            raise AppError(ErrorCode.OUTPUT_INVALID)
        document = json.loads(
            await capture_process(
                self.capabilities.ffprobe.path,
                [
                    "-v",
                    "error",
                    "-show_streams",
                    "-show_format",
                    "-of",
                    "json",
                    str(path),
                ],
            )
        )
        actual = document.get("streams", [])
        if len(actual) != len(plan.stream_mapping):
            raise AppError(ErrorCode.OUTPUT_INVALID)
        source = plan.source_asset
        expected_muxer = {"mp4": "mp4", "mkv": "matroska", "webm": "webm"}[
            plan.settings_snapshot.container
        ]
        if expected_muxer not in document.get("format", {}).get("format_name", "").split(","):
            raise AppError(ErrorCode.OUTPUT_INVALID)
        counters = {"video": 0, "audio": 0, "subtitle": 0}
        for stream, mapping in zip(actual, plan.stream_mapping, strict=True):
            original = next(
                item for item in source.streams if item.stream_index == mapping.source_index
            )
            codec = original.codec if mapping.action == "copy" else ENCODER_CODECS[mapping.encoder]
            if stream.get("codec_type") != mapping.kind or stream.get("codec_name") != codec:
                raise AppError(ErrorCode.OUTPUT_INVALID)
            if original.language and original.language != "und":
                if stream.get("tags", {}).get("language") != original.language:
                    raise AppError(ErrorCode.OUTPUT_INVALID)
            retained = [
                item
                for item in source.streams
                if any(
                    other.source_index == item.stream_index and other.kind == mapping.kind
                    for other in plan.stream_mapping
                )
            ]
            default = output_default(
                original,
                plan.settings_snapshot.container,
                mapping.kind,
                counters[mapping.kind],
                retained,
            )
            counters[mapping.kind] += 1
            if bool(stream.get("disposition", {}).get("default")) != default:
                raise AppError(ErrorCode.OUTPUT_INVALID)
            if bool(stream.get("disposition", {}).get("forced")) != (
                "forced" in original.disposition
            ):
                raise AppError(ErrorCode.OUTPUT_INVALID)
        video = next(stream for stream in actual if stream["codec_type"] == "video")
        expected_width, expected_height = output_dimensions(source, plan.settings_snapshot)
        tolerance = 2 if plan.settings_snapshot.resolution else 0
        if (
            abs(video.get("width", 0) - expected_width) > tolerance
            or abs(video.get("height", 0) - expected_height) > tolerance
        ):
            raise AppError(ErrorCode.OUTPUT_INVALID)
        rotations = [item.get("rotation", 0) % 360 for item in video.get("side_data_list", [])]
        if any(rotations):
            raise AppError(ErrorCode.OUTPUT_INVALID)
        rate = plan.settings_snapshot.frame_rate
        if rate and Fraction(video.get("avg_frame_rate", "0")) != Fraction(
            rate.numerator, rate.denominator
        ):
            raise AppError(ErrorCode.OUTPUT_INVALID)
        actual_duration = duration_us(document.get("format", {}).get("duration"))
        if actual_duration is None or actual_duration <= 0:
            raise AppError(ErrorCode.OUTPUT_INVALID)
        if source.duration_us is not None:
            # Container/audio padding and one video frame are tolerated; gross truncation is not.
            frame = source.frame_rate
            frame_us = frame.denominator * 1_000_000 / frame.numerator if frame else 0
            allowance = max(250_000, frame_us * 2)
            if abs(actual_duration - source.duration_us) > allowance:
                raise AppError(ErrorCode.OUTPUT_INVALID)
        if actual_duration <= 30_000_000:
            await capture_process(
                self.capabilities.ffmpeg.path,
                [
                    "-v",
                    "error",
                    "-xerror",
                    "-nostdin",
                    "-i",
                    str(path),
                    "-map",
                    "0:v",
                    "-map",
                    "0:a?",
                    "-f",
                    "null",
                    "-",
                ],
                timeout=60,
            )
        return {
            "duration_us": actual_duration,
            "streams": actual,
            "width": video["width"],
            "height": video["height"],
            "full_decode": actual_duration <= 30_000_000,
        }
