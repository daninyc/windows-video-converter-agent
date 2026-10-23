import os

import pytest

from media_converter.common.context import new_id
from media_converter.common.errors import AppError
from media_converter.jobs.output_commit import OutputLease
from media_converter.media.models import ConversionPlan, ConversionSettings, ImportRoot
from media_converter.media.output_paths import plan_output_paths
from tests.unit.test_conversion_models import make_asset

pytestmark = pytest.mark.integration


def plan_for(tmp_path):
    asset = make_asset(tmp_path)
    settings = ConversionSettings(output_dir=tmp_path / "out")
    identity = new_id()
    paths = plan_output_paths(
        asset, ImportRoot(resolved_path=tmp_path, display_group="root"), settings, identity
    )
    return ConversionPlan(
        asset_id=asset.asset_id,
        attempt_id=identity,
        source_path=asset.resolved_path,
        source_fingerprint=asset.fingerprint,
        settings_snapshot=settings,
        stream_mapping=(),
        ffmpeg_args=(),
        temporary_path=paths.temporary,
        final_path=paths.final,
        output_root=paths.root,
    )


def test_no_replace_on_collision_and_only_owned_cleanup(tmp_path, monkeypatch):
    plan = plan_for(tmp_path)
    original = plan.source_path.read_bytes()
    lease = OutputLease(plan)
    lease.acquire()
    plan.temporary_path.write_bytes(b"converted")
    link = os.link
    raced = []

    def race(source, target):
        if not raced:
            target.write_bytes(b"other user result")
            raced.append(target)
        return link(source, target)

    monkeypatch.setattr(os, "link", race)
    result = lease.commit()
    assert result != plan.final_path and result.read_bytes() == b"converted"
    assert raced[0].read_bytes() == b"other user result"
    assert plan.source_path.read_bytes() == original
    lease.cleanup()
    assert not plan.temporary_path.parent.exists()
    with pytest.raises(AppError):
        OutputLease(plan.model_copy(update={"output_root": tmp_path / "elsewhere"})).acquire()


def test_existing_attempt_directory_is_never_owned_or_cleaned(tmp_path):
    plan = plan_for(tmp_path)
    plan.temporary_path.parent.mkdir(parents=True)
    plan.temporary_path.write_bytes(b"existing user file")
    lease = OutputLease(plan)
    with pytest.raises(AppError):
        lease.acquire()
    lease.cleanup()
    assert plan.temporary_path.read_bytes() == b"existing user file"
