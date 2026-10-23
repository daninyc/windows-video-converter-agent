import hashlib
import hmac
import json
import time

from media_converter.common.errors import AppError, ErrorCode

META_NAMESPACE = "media_converter/context"


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def signed_metadata(key, context, invocation_id, name, arguments):
    value = {
        "turn_id": context.turn_id,
        "conversation_id": context.conversation_id,
        "instance_id": context.instance_id,
        "scope_version": context.scope_version,
        "trace_id": context.trace_id,
        "deadline_at": context.deadline_at,
        "invocation_id": invocation_id,
        "tool_name": name,
        "arguments_hash": hashlib.sha256(canonical(arguments)).hexdigest(),
    }
    return {
        META_NAMESPACE: {
            "value": value,
            "signature": hmac.new(key, canonical(value), hashlib.sha256).hexdigest(),
        }
    }


def validate_metadata(key, reader, meta, name, arguments):
    try:
        grant = meta[META_NAMESPACE]
        value = grant["value"]
        expected = hmac.new(key, canonical(value), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, grant["signature"]):
            raise ValueError("signature")
        turn = reader.turn(value["turn_id"])
        context = turn.context
        if turn.state != "RUNNING":
            raise ValueError("state")
        for field in (
            "turn_id",
            "conversation_id",
            "instance_id",
            "scope_version",
            "trace_id",
            "deadline_at",
        ):
            if value[field] != getattr(context, field):
                raise ValueError("context")
        if (
            name != value["tool_name"]
            or hashlib.sha256(canonical(arguments)).hexdigest() != value["arguments_hash"]
        ):
            raise ValueError("arguments")
        active = {r.reference_id for r in reader.references(context.conversation_id)}
        if not {r.reference_id for r in context.references} <= active:
            raise ValueError("revoked")
        if reader.conversation(context.conversation_id).instance_id != context.instance_id:
            raise ValueError("instance")
        if context.deadline_at <= time.time():
            raise AppError(ErrorCode.TIMEOUT)
        return context, value["invocation_id"]
    except AppError:
        raise
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise AppError(ErrorCode.ACCESS_DENIED) from error
