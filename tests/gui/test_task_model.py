import pytest

from media_converter.media.thumbnail import ThumbnailResult
from media_converter.ui.task_model import TaskModel
from tests.unit.test_conversion_models import make_asset

pytestmark = pytest.mark.gui


def test_removed_asset_late_thumbnail_never_changes_reused_row(qapp, tmp_path):
    model = TaskModel()
    removed = make_asset(tmp_path)
    replacement = removed.model_copy(update={"asset_id": "replacement"})
    model.add(removed)
    model.remove(removed.asset_id)
    model.add(replacement)
    model.set_thumbnail(removed, ThumbnailResult(tmp_path / "old.jpg"))
    assert model.rowCount() == 1 and model.rows[0].asset.asset_id == "replacement"
    assert model.rows[0].icon is None
