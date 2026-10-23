from media_converter.common.context import new_id
from media_converter.media.models import ConversionSettings, ImportRoot
from media_converter.media.output_paths import path_key, plan_output_paths
from tests.unit.test_conversion_models import make_asset


def test_grouping_flattening_beside_and_protect_source(tmp_path):
    asset = make_asset(tmp_path)
    first = ImportRoot(resolved_path=tmp_path, display_group="来源")
    second = ImportRoot(resolved_path=tmp_path, display_group="来源")
    settings = ConversionSettings(output_dir=tmp_path / "outputs", preserve_hierarchy=True)
    one = plan_output_paths(asset, first, settings, new_id())
    two = plan_output_paths(asset, second, settings, new_id())
    assert one.final.parent != two.final.parent
    flat = ConversionSettings(output_dir=tmp_path)
    result = plan_output_paths(asset, first, flat, new_id())
    assert path_key(result.final) != path_key(asset.resolved_path)
    reserved = {path_key(result.final)}
    assert plan_output_paths(asset, first, flat, new_id(), reserved).final != result.final
    beside = ConversionSettings(output_mode="beside_source")
    assert plan_output_paths(asset, first, beside, new_id()).final.parent == tmp_path / "转换结果"
