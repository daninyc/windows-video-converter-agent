import json
import shutil
from pathlib import Path

from media_converter.config import AppPaths
from media_converter.devtools.build_windows import sha
from media_converter.media.toolchain import inspect_toolchain, run_tool


def generate(root, data_dir):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "manifest.json"
    if manifest.exists():
        value = json.loads(manifest.read_text("utf-8"))
        assert value["generator"] == "agreed-pressure-v1"
        for item in value["files"]:
            assert sha(root / item["path"]) == item["sha256"]
        return value
    if any(root.iterdir()):
        raise ValueError("pressure directory is not empty")
    binary = inspect_toolchain(AppPaths(Path(data_dir))).ffmpeg.path
    commands = []

    def ff(args):
        commands.append(args)
        run_tool(binary, ["-v", "error", "-n", *args], timeout=300)

    seed = root / "loop-source-1080p.mp4"
    pattern = (
        "smptebars=size=1920x1080:rate=30,"
        "drawbox=x=100:y=100:w=200:h=200:color=white:t=fill:enable=between(t\\,2\\,3)"
    )
    ff(
        [
            "-f",
            "lavfi",
            "-i",
            pattern,
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            "10",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-threads",
            "2",
            "-c:a",
            "aac",
            str(seed),
        ]
    )
    long = root / "01_30分钟_1080p.mp4"
    ff(["-stream_loop", "179", "-i", str(seed), "-t", "1800", "-c", "copy", str(long)])
    four = root / "02_1分钟_4K.mp4"
    ff(
        [
            "-f",
            "lavfi",
            "-i",
            "smptebars=size=3840x2160:rate=30",
            "-t",
            "60",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-threads",
            "2",
            str(four),
        ]
    )
    short = root / "short-source.mp4"
    ff(["-i", str(seed), "-t", "1", "-c", "copy", str(short)])
    paths = [(long, 1800, 1920, 1080), (four, 60, 3840, 2160)]
    queue = root / "50短视频"
    queue.mkdir()
    for i in range(50):
        file = queue / f"短视频_{i + 1:02}.mp4"
        shutil.copy2(short, file)
        paths.append((file, 1, 1920, 1080))
    value = {
        "generator": "agreed-pressure-v1",
        "content": "self-generated repeated SMPTE bars and pulse; not natural-scene complexity",
        "fps": 30,
        "license": "self-generated test data",
        "commands": commands,
        "files": [
            {
                "path": p.relative_to(root).as_posix(),
                "seconds": seconds,
                "width": w,
                "height": h,
                "sha256": sha(p),
                "bytes": p.stat().st_size,
            }
            for p, seconds, w, h in paths
        ],
    }
    manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
    return value
