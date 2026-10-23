"""Owned one-request process; document parsers never run in Qt or MCP's event loop."""

import io
import json
import sys
import zipfile
from pathlib import Path

from media_converter.agent.models import Reference
from media_converter.common.errors import AppError, ErrorCode
from media_converter.tools.schemas import FileQuery
from media_converter.tools.text_reader import authorized_bytes, decode_text, page_result


def parse_document(reference, arguments):
    data = authorized_bytes(reference)
    suffix = Path(reference.resolved_path).suffix.lower()
    if suffix in {".txt", ".md", ".log"}:
        return page_result(reference, [("characters", decode_text(data))], arguments, kind="text")
    if suffix == ".pdf":
        from pypdf import PdfReader

        document = PdfReader(io.BytesIO(data))
        if document.is_encrypted:
            raise AppError(ErrorCode.ACCESS_DENIED)
        # Only requested pages are extracted, while cursor positions remain document-relative.
        from media_converter.tools.text_reader import read_cursor

        start, _ = read_cursor(reference, arguments)
        end = min(len(document.pages), start + arguments.page_count)
        units = [(f"page:{i + 1}", "") for i in range(len(document.pages))]
        for i in range(start, end):
            units[i] = (f"page:{i + 1}", document.pages[i].extract_text() or "")
        if not any(text.strip() for _, text in units[start:end]) and end == len(units):
            raise AppError(ErrorCode.NO_EXTRACTABLE_TEXT)
        return page_result(reference, units, arguments, kind="page")
    if suffix == ".docx":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > 10000
                or sum(e.file_size for e in entries) > 100 * 1024 * 1024
                or any(e.file_size > max(e.compress_size, 1) * 200 for e in entries)
            ):
                raise AppError(ErrorCode.FILE_TOO_LARGE)
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document, units = Document(io.BytesIO(data)), []
        for index, element in enumerate(document.element.body.iterchildren()):
            if element.tag.endswith("}p"):
                units.append((f"paragraph:{index}", Paragraph(element, document).text))
            elif element.tag.endswith("}tbl"):
                table = Table(element, document)
                for r, row in enumerate(table.rows):
                    for c, cell in enumerate(row.cells):
                        units.append((f"table:{index}/row:{r}/cell:{c}", cell.text))
        if not any(text.strip() for _, text in units):
            raise AppError(ErrorCode.NO_EXTRACTABLE_TEXT)
        return page_result(reference, units, arguments, kind="block")
    raise AppError(ErrorCode.INVALID_ARGUMENT)


def main():
    try:
        request = json.loads(sys.stdin.buffer.read(100000))

        def check_grant():
            if request.get("reader_path"):
                from media_converter.storage.conversations import ConversationReader

                reader = ConversationReader(request["reader_path"])
                turn = reader.turn(request["turn_id"])
                refs = reader.references(turn.context.conversation_id)
                if turn.state != "RUNNING" or request["reference"]["reference_id"] not in {
                    r.reference_id for r in refs
                }:
                    raise AppError(ErrorCode.ACCESS_DENIED)

        check_grant()
        result = parse_document(
            Reference.model_validate(request["reference"]),
            FileQuery.model_validate(request["arguments"]),
        )
        check_grant()
        response = {"ok": True, "data": result}
    except Exception as error:
        code = error.info.code if isinstance(error, AppError) else ErrorCode.INVALID_ARGUMENT
        response = {"ok": False, "error_code": code}
    sys.stdout.write(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
