import pytest

from media_converter.agent.models import Reference
from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import FileFingerprint
from media_converter.tools.schemas import FileQuery
from media_converter.tools.text_reader import authorized_bytes, decode_text, page_result

pytestmark = pytest.mark.unit


def test_open_checks_file_identity_and_text_encoding_and_cursor(tmp_path):
    path = tmp_path / "文字.txt"
    path.write_text("中文" * 30, encoding="utf-8")
    ref = Reference(
        conversation_id="chat",
        kind="file",
        entity_id="file",
        label=path.name,
        resolved_path=str(path.resolve()),
        fingerprint=FileFingerprint.from_path(path),
    )
    text = decode_text(authorized_bytes(ref))
    args = FileQuery(file_ref_id=ref.reference_id, max_chars=5)
    first = page_result(ref, [("text", text)], args, kind="text")
    second = page_result(
        ref, [("text", text)], args.model_copy(update={"cursor": first["next_cursor"]}), kind="text"
    )
    assert first["text"] + second["text"] == text[:10]
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(AppError) as error:
        authorized_bytes(ref)
    assert error.value.info.code == ErrorCode.FILE_CHANGED
    with pytest.raises(AppError):
        decode_text(b"\xffnot-utf8")
