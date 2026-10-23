import pytest

from media_converter.media.probe import parse_probe
from tests.unit.test_conversion_models import make_asset

pytestmark = pytest.mark.unit


def test_unknowns_cover_rotation_and_fractional_rates(tmp_path):
    asset = make_asset(tmp_path)
    parsed = parse_probe(
        asset,
        {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "video",
                    "width": 100,
                    "height": 80,
                    "r_frame_rate": "30000/1001",
                    "avg_frame_rate": "0/0",
                    "side_data_list": [{"rotation": -90}],
                },
                {"index": 1, "codec_type": "video", "disposition": {"attached_pic": 1}},
                {
                    "index": 2,
                    "codec_type": "audio",
                    "sample_rate": "48000",
                    "tags": {"language": "zho"},
                },
            ]
        },
    )
    assert parsed.duration_us is None and parsed.bitrate_bps is None
    assert parsed.frame_rate.denominator == 1001 and parsed.average_frame_rate is None
    assert parsed.rotation_deg == 270 and parsed.streams[1].attached_picture
    assert parsed.streams[2].sample_rate_hz == 48000
