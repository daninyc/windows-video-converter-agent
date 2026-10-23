# Conservative copy rules; real fixture coverage is listed in CONVERSION_REPORT.md.
COPY_AUDIO = {
    "mp4": {"aac"},
    "mkv": {"aac", "opus", "vorbis", "mp3", "flac", "pcm_s16le"},
    "webm": {"opus", "vorbis"},
}
COPY_SUBTITLES = {
    "mp4": {"mov_text"},
    "mkv": {"subrip", "ass", "ssa", "webvtt", "hdmv_pgs_subtitle", "dvd_subtitle"},
    "webm": {"webvtt"},
}
ENCODER_CODECS = {"libx264": "h264", "libvpx-vp9": "vp9", "aac": "aac", "libopus": "opus"}


def output_default(source, container, kind, index, retained):
    if "default" in source.disposition:
        return True
    # MP4 enables its first video/audio track when no retained track is marked default.
    return (
        container == "mp4"
        and kind in {"video", "audio"}
        and index == 0
        and not any("default" in stream.disposition for stream in retained)
    )
