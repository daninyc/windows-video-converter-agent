import hashlib
import json
import sys
import time
from pathlib import Path


def main():
    import torch
    from sentence_transformers import CrossEncoder

    config = json.loads(sys.stdin.readline())
    root = Path(config["model_path"]).resolve()
    for item in config["files"]:
        path = (root / item["file"]).resolve()
        if not path.is_relative_to(root) or path.stat().st_size != item["bytes"]:
            raise ValueError("model file identity mismatch")
        if item["algorithm"] == "sha256":
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        else:
            raw = path.read_bytes()
            digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if digest != item["digest"]:
            raise ValueError("model file checksum mismatch")
    torch.set_num_threads(4)
    started = time.perf_counter()
    model = CrossEncoder(
        config["model_path"],
        device="cpu",
        local_files_only=True,
        trust_remote_code=False,
        max_length=1024,
    )
    print(
        json.dumps(
            {
                "ready": True,
                "load_seconds": time.perf_counter() - started,
                "threads": 4,
                "device": "cpu",
                "verified_revision": config["revision"],
            }
        ),
        flush=True,
    )
    for line in sys.stdin:
        request = json.loads(line)
        started = time.perf_counter()
        pairs = [(request["query"], text) for text in request["texts"]]
        lengths = [len(model.tokenizer(a, b, truncation=False)["input_ids"]) for a, b in pairs]
        scores = model.predict(pairs, batch_size=2).tolist()
        print(
            json.dumps(
                {
                    "request_id": request["request_id"],
                    "scores": scores,
                    "seconds": time.perf_counter() - started,
                    "max_tokens": 1024,
                    "truncated_pairs": sum(n > 1024 for n in lengths),
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
