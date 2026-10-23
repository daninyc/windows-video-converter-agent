import asyncio
import json
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from media_converter.common.errors import AppError, ErrorCode
from media_converter.common.process import capture_process
from media_converter.media.models import FileFingerprint, FrameRate, MediaAsset, StreamInfo


def positive_int(value):
    try:
        result = int(value)
        return result if result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def rate(value):
    try:
        fraction = Fraction(value)
        if fraction > 0:
            return FrameRate(numerator=fraction.numerator, denominator=fraction.denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return None


def duration_us(value):
    try:
        number = Decimal(str(value))
        return int(number * 1_000_000) if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def parse_probe(asset: MediaAsset, document: dict) -> MediaAsset:
    streams = []
    for item in document.get("streams", []):
        kind = item.get("codec_type", "unknown")
        if kind not in {"video", "audio", "subtitle", "data", "attachment"}:
            kind = "unknown"
        codec = item.get("codec_name")
        streams.append(
            StreamInfo(
                stream_index=int(item["index"]),
                kind=kind,
                codec=codec,
                language=item.get("tags", {}).get("language"),
                disposition=tuple(
                    key for key, value in item.get("disposition", {}).items() if value == 1
                ),
                channels=positive_int(item.get("channels")),
                sample_rate_hz=positive_int(item.get("sample_rate")),
                subtitle_type=(
                    "text"
                    if codec in {"ass", "ssa", "subrip", "mov_text", "webvtt", "text"}
                    else "bitmap"
                    if codec in {"dvd_subtitle", "hdmv_pgs_subtitle", "dvb_subtitle"}
                    else None
                ),
                attached_picture=bool(item.get("disposition", {}).get("attached_pic")),
            )
        )
    video = next(
        (
            item
            for item in document.get("streams", [])
            if item.get("codec_type") == "video"
            and not item.get("disposition", {}).get("attached_pic")
        ),
        {},
    )
    if not video:
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    rotation = next(
        (entry["rotation"] for entry in video.get("side_data_list", []) if "rotation" in entry),
        video.get("tags", {}).get("rotate"),
    )
    try:
        rotation = round(float(rotation)) % 360 if rotation is not None else None
    except (TypeError, ValueError, OverflowError):
        rotation = None
    format_info = document.get("format", {})
    data = {
        **asset.model_dump(),
        "container": format_info.get("format_name"),
        "duration_us": duration_us(format_info.get("duration", video.get("duration"))),
        "width": positive_int(video.get("width")),
        "height": positive_int(video.get("height")),
        "rotation_deg": rotation,
        "bitrate_bps": positive_int(format_info.get("bit_rate")),
        "frame_rate": rate(video.get("r_frame_rate")),
        "average_frame_rate": rate(video.get("avg_frame_rate")),
        "variable_frame_rate": None,
        "color_info": tuple(
            (key, str(video[key]))
            for key in (
                "color_space",
                "color_transfer",
                "color_primaries",
                "color_range",
                "sample_aspect_ratio",
            )
            if key in video
        )
        + tuple(
            ("hdr_metadata", str(entry["side_data_type"]))
            for entry in video.get("side_data_list", [])
            if any(
                marker in entry.get("side_data_type", "").lower()
                for marker in ("dovi", "mastering display", "content light")
            )
        ),
        "streams": tuple(streams),
        "probe_status": "succeeded",
        "probe_error_code": None,
    }
    return MediaAsset.model_validate(data)


class ProbeService:
    def __init__(self, ffprobe, store=None, *, timeout=15):
        self.ffprobe = ffprobe
        self.store = store
        self.timeout = timeout
        self._slots = asyncio.Semaphore(2)
        self._pending = 0

    async def probe(self, asset: MediaAsset, *, force=False) -> MediaAsset:
        self._pending += 1
        try:
            if self._pending > 130:
                raise AppError(ErrorCode.QUEUE_FULL)
            fresh = FileFingerprint.from_path(asset.resolved_path)
            if not force and fresh == asset.fingerprint and asset.probe_status == "succeeded":
                return asset
            asset = MediaAsset.model_validate({**asset.model_dump(), "fingerprint": fresh})
            async with asyncio.timeout(30):
                async with self._slots:
                    output = await capture_process(
                        self.ffprobe,
                        [
                            "-v",
                            "error",
                            "-show_streams",
                            "-show_format",
                            "-of",
                            "json",
                            str(asset.resolved_path),
                        ],
                        timeout=self.timeout,
                    )
            if FileFingerprint.from_path(asset.resolved_path) != fresh:
                raise AppError(ErrorCode.FILE_CHANGED)
            asset = parse_probe(asset, json.loads(output))
        except (AppError, OSError, ValueError, KeyError, TimeoutError) as error:
            code = (
                error.info.code
                if isinstance(error, AppError)
                else ErrorCode.TIMEOUT
                if isinstance(error, TimeoutError)
                else ErrorCode.PROCESS_FAILED
            )
            asset = MediaAsset(
                asset_id=asset.asset_id,
                root_id=asset.root_id,
                relative_path=asset.relative_path,
                resolved_path=asset.resolved_path,
                fingerprint=asset.fingerprint,
                probe_status="failed",
                probe_error_code=code,
            )
        finally:
            self._pending -= 1
        if self.store:
            await asyncio.to_thread(self.store.save_asset, asset)
        return asset
