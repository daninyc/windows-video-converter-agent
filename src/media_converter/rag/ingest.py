import base64
import hashlib
import json
import re
from pathlib import Path

from media_converter.common.errors import AppError, ErrorCode

CHUNK_VERSION = "gguf-sentencepiece-v1-target650-max800-overlap80"


def lexical(text):
    return " ".join(re.findall(r"-?[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.casefold()))


def actual_tokenizer(info):
    from sentencepiece import SentencePieceProcessor
    from sentencepiece import sentencepiece_model_pb2 as pb

    model = pb.ModelProto()
    model.trainer_spec.model_type = pb.TrainerSpec.UNIGRAM
    for name, key in [
        ("unk_id", "unknown_token_id"),
        ("bos_id", "bos_token_id"),
        ("eos_id", "eos_token_id"),
        ("pad_id", "padding_token_id"),
    ]:
        setattr(model.trainer_spec, name, info["tokenizer.ggml." + key])
    for token, score, kind in zip(
        info["tokenizer.ggml.tokens"],
        info["tokenizer.ggml.scores"],
        info["tokenizer.ggml.token_type"],
        strict=True,
    ):
        piece = model.pieces.add()
        piece.piece, piece.score, piece.type = token, score, kind
    model.normalizer_spec.precompiled_charsmap = base64.b64decode(
        info["tokenizer.ggml.precompiled_charsmap"]
    )
    model.normalizer_spec.add_dummy_prefix = info["tokenizer.ggml.add_space_prefix"]
    model.normalizer_spec.remove_extra_whitespaces = info["tokenizer.ggml.remove_extra_whitespaces"]
    raw = model.SerializeToString()
    return SentencePieceProcessor(model_proto=raw), hashlib.sha256(raw).hexdigest()


def chunk_section(text, tokenizer, *, target=650, maximum=800, overlap=80):
    if not 0 <= overlap < target <= maximum:
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    # Character boundaries retain original spelling/locations; token counts use this GGUF's model.
    result, start = [], 0
    while start < len(text):
        lo, hi = start + 1, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if len(tokenizer.encode(text[start:mid])) <= target:
                lo = mid
            else:
                hi = mid - 1
        end = lo
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end))
            if boundary > start and len(tokenizer.encode(text[start : boundary + 1])) >= 500:
                end = boundary + 1
        count = len(tokenizer.encode(text[start:end]))
        if count + 2 > maximum + 2:
            raise AppError(ErrorCode.FILE_TOO_LARGE)
        result.append((start, end, text[start:end], count + 2))
        if end == len(text):
            break
        overlap_start = end
        while (
            overlap_start > start + 1
            and len(tokenizer.encode(text[overlap_start - 1 : end])) <= overlap
        ):
            overlap_start -= 1
        start = max(start + 1, overlap_start)
    return result


def load_chunks(root, tokenizer):
    root = Path(root).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    chunks = []
    for document in manifest["documents"]:
        path = (root / document["path"]).resolve()
        if not path.is_relative_to(root):
            raise AppError(ErrorCode.ACCESS_DENIED)
        content = path.read_text(encoding="utf-8")
        if hashlib.sha256(path.read_bytes()).hexdigest() != document["content_sha256"]:
            raise AppError(ErrorCode.FILE_CHANGED)
        for section in document["sections"]:
            marker = "## " + section["heading"]
            start = content.index(marker) + len(marker)
            end = content.find("\n## ", start)
            text = content[start : end if end >= 0 else len(content)].strip()
            for index, (begin, finish, piece, count) in enumerate(chunk_section(text, tokenizer)):
                chunks.append(
                    {
                        "chunk_id": f"{document['document_id']}:{section['id']}:{index}",
                        "section_id": section["id"],
                        "document_id": document["document_id"],
                        "section": section["heading"],
                        "text": piece,
                        "char_start": begin,
                        "char_end": finish,
                        "token_count": count,
                        "content_hash": hashlib.sha256(piece.encode()).hexdigest(),
                        "source": {
                            "document_id": document["document_id"],
                            "section": section["heading"],
                            "source_url": section.get("source_url"),
                            "source_path": document["path"],
                            "evidence_path": section["source_path"],
                            "license": document["license"],
                        },
                    }
                )
    if len({c["chunk_id"] for c in chunks}) != len(chunks):
        raise AppError(ErrorCode.INVALID_ARGUMENT)
    return manifest, chunks
