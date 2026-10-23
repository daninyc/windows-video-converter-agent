import base64
import hashlib
import json
import os
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode

MAX_FILE_BYTES = 20 * 1024 * 1024


def authorized_bytes(reference):
    path = Path(reference.resolved_path)
    try:
        if path.resolve(strict=True) != path:
            raise AppError(ErrorCode.FILE_CHANGED)
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            fp = reference.fingerprint
            if (before.st_size, before.st_mtime_ns, f"{before.st_dev}:{before.st_ino}") != (
                fp.size_bytes,
                fp.mtime_ns,
                fp.file_identity,
            ):
                raise AppError(ErrorCode.FILE_CHANGED)
            if before.st_size > MAX_FILE_BYTES:
                raise AppError(ErrorCode.FILE_TOO_LARGE)
            data = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
            if len(data) > MAX_FILE_BYTES:
                raise AppError(ErrorCode.FILE_TOO_LARGE)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise AppError(ErrorCode.FILE_CHANGED)
        return data
    except OSError as error:
        raise AppError(ErrorCode.FILE_CHANGED) from error


def decode_text(data):
    try:
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeError as error:
        # Ambiguous legacy encodings require explicit conversion, never replacement text.
        raise AppError(ErrorCode.INVALID_ARGUMENT) from error


def cursor_key(reference):
    return hashlib.sha256(reference.model_dump_json().encode()).hexdigest()


def read_cursor(reference, arguments):
    if arguments.cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(arguments.cursor))
            if (
                decoded["key"] != cursor_key(reference)
                or not isinstance(decoded["unit"], int)
                or not isinstance(decoded["offset"], int)
                or min(decoded["unit"], decoded["offset"]) < 0
            ):
                raise ValueError("cursor")
            return decoded["unit"], decoded["offset"]
        except (ValueError, KeyError, TypeError) as error:
            raise AppError(ErrorCode.INVALID_ARGUMENT) from error
    extension = Path(reference.resolved_path).suffix.lower()
    return (
        arguments.page_start - 1 if extension == ".pdf" else arguments.block_start
    ), arguments.offset


def page_result(reference, units, arguments, *, kind):
    unit, offset = read_cursor(reference, arguments)
    if unit > len(units) or unit < len(units) and offset > len(units[unit][1]):
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    remaining, parts, start = arguments.max_chars, [], unit
    while unit < len(units) and (kind != "page" or unit - start < arguments.page_count):
        if parts:
            if remaining <= 1:
                break
            remaining -= 1
        location, text = units[unit]
        piece = text[offset : offset + remaining]
        if piece:
            parts.append({"location": location, "char_start": offset, "text": piece})
        remaining -= len(piece)
        offset += len(piece)
        if offset == len(text):
            unit, offset = unit + 1, 0
        if remaining == 0:
            break
    next_cursor = None
    if unit < len(units):
        next_cursor = base64.urlsafe_b64encode(
            json.dumps({"key": cursor_key(reference), "unit": unit, "offset": offset}).encode()
        ).decode()
    return {
        "text": "\n".join(part["text"] for part in parts),
        "locations": parts,
        "fingerprint": reference.fingerprint.model_dump(mode="json"),
        "encoding": "utf-8/utf-16 BOM" if kind == "text" else None,
        "truncated": next_cursor is not None,
        "next_cursor": next_cursor,
        "file_ref_id": reference.reference_id,
    }
