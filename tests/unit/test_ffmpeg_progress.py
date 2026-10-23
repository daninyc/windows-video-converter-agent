import pytest

from media_converter.jobs.ffmpeg_process import ProgressParser

pytestmark = pytest.mark.unit


def test_fragmented_progress_microseconds_unknown_duration_and_end_is_not_success():
    parser = ProgressParser()
    assert not parser.feed(b"out_time_u")
    events = parser.feed(
        b"s=250000\nspeed=1.5x\nprogress=continue\nout_time_us=N/A\nprogress=end\n"
    )
    assert events[0].processed_us == 250000 and events[0].speed == 1.5
    assert events[0].percentage(None) is None
    assert events[0].percentage(1_000_000) == 25
    assert events[1].ended and events[1].processed_us == 250000
    assert events[1].percentage(1) == 99
