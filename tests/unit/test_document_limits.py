import io
import zipfile

import pytest

from media_converter.agent.models import Reference
from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import FileFingerprint
from media_converter.tools.document_worker import parse_document
from media_converter.tools.schemas import FileQuery

pytestmark = pytest.mark.unit


def test_zip_expansion_limit_rejected_before_docx_parser(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"A" * 1_000_000)
    path = tmp_path / "bomb.docx"
    path.write_bytes(buffer.getvalue())
    ref = Reference(
        conversation_id="a",
        kind="file",
        entity_id="a",
        label="doc",
        resolved_path=str(path.resolve()),
        fingerprint=FileFingerprint.from_path(path),
    )
    with pytest.raises(AppError) as error:
        parse_document(ref, FileQuery(file_ref_id=ref.reference_id))
    assert error.value.info.code == ErrorCode.FILE_TOO_LARGE
