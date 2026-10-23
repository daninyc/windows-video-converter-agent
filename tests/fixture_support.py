from pathlib import Path

from media_converter.devtools.fixtures import safe_fixture_path, verify_manifest


def load_fixture_manifest(root: Path) -> dict:
    return verify_manifest(root.resolve())


def fixture_file(root: Path, relative: str) -> Path:
    return safe_fixture_path(root.resolve(), relative)


def probed_fixture(root: Path, relative: str):
    from media_converter.media.models import FileFingerprint, MediaAsset
    from media_converter.media.probe import parse_probe

    manifest = load_fixture_manifest(root)
    item = next(item for item in manifest["files"] if item["path"] == relative)
    path = fixture_file(root, relative)
    asset = MediaAsset(
        root_id="fixture-root",
        relative_path=relative,
        resolved_path=path,
        fingerprint=FileFingerprint.from_path(path),
    )
    observed = item["observed"]
    return parse_probe(
        asset,
        {
            "streams": observed["streams"],
            "format": {
                "format_name": observed["format"],
                "duration": str(observed["duration_us"] / 1_000_000),
            },
        },
    )
