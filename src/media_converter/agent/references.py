import hashlib
import json


def source_with_id(source):
    value = dict(source)
    value["source_id"] = (
        "src-"
        + hashlib.sha256(
            json.dumps(source, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]
    )
    return value


def reference_source(reference):
    return source_with_id(
        {"reference_id": reference.reference_id, "kind": reference.kind, "title": reference.label}
    )
