import json
from types import SimpleNamespace

import pytest

from media_converter.agent.settings_proposals import ProposalService
from media_converter.common.errors import AppError
from media_converter.config import AppPaths
from media_converter.media.models import ConversionSettings
from media_converter.media.toolchain import inspect_toolchain
from media_converter.storage.conversations import ConversationStore
from media_converter.storage.local_store import LocalStore

pytestmark = pytest.mark.unit


REAL_MODEL_JSON_ANSWER = """标记：ACCEPTANCE_SCOPE_fee0b978_2。规则库（app-mp4）规定 MP4 默认
libx264、AAC、CRF 23，保持原分辨率/帧率，已契合“保留音频、生成 MP4”目标，无需改参数。

```json
{"patch":{"quality_value":23},
"reason":"沿用规则默认 CRF23、libx264 与 AAC，保持原分辨率帧率以保留音频并生成 MP4",
"source_ids":["src-24443822335a4e7d"]}
```"""


@pytest.fixture
def proposal_case(tmp_path):
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        chat = chats.create()
        context = chats.begin(chat.conversation_id, "建议", ConversionSettings()).context
        capabilities = SimpleNamespace(encoders={"libx264", "aac"}, muxers={"mp4"})
        yield ProposalService(store, capabilities), context, store


@pytest.mark.parametrize("fence", ["settings_proposal", "json"])
def test_real_model_json_proposal_is_saved_pending_without_applying(proposal_case, fence):
    service, context, store = proposal_case
    sources = [{"source_id": "src-24443822335a4e7d", "title": "MP4 defaults"}]
    answer = REAL_MODEL_JSON_ANSWER.replace("```json", "```" + fence)
    proposal = service.from_answer(context, answer, sources)
    assert proposal.status == "PENDING"
    assert proposal.conversation_id == context.conversation_id
    assert proposal.turn_id == context.turn_id
    assert json.loads(proposal.patch_json) == {"quality_value": 23}
    assert service.get(proposal.proposal_id) == proposal
    assert store.get_settings() is None
    assert json.loads(context.settings_json)["quality_value"] == 23


@pytest.mark.parametrize("fence", ["settings_proposal", "json"])
def test_valid_sourced_empty_patch_means_unchanged_and_creates_no_proposal(proposal_case, fence):
    service, context, store = proposal_case
    payload = {
        "patch": {},
        "reason": "默认设置已符合目标，保持原设置",
        "source_ids": ["known-source"],
    }
    answer = "```" + fence + "\n" + json.dumps(payload) + "\n```"
    assert service.from_answer(context, answer, [{"source_id": "known-source"}]) is None
    assert store.get_settings() is None
    assert (
        store._write(lambda c: c.execute("SELECT COUNT(*) FROM settings_proposals").fetchone()[0])
        == 0
    )


@pytest.mark.parametrize("source_ids", [[], ["invented-source"]])
def test_empty_patch_still_requires_real_nonempty_evidence(proposal_case, source_ids):
    service, context, store = proposal_case
    payload = {"patch": {}, "reason": "默认设置符合目标", "source_ids": source_ids}
    answer = "```settings_proposal\n" + json.dumps(payload) + "\n```"
    with pytest.raises(AppError):
        service.from_answer(context, answer, [{"source_id": "known-source"}])
    assert store.get_settings() is None
    assert (
        store._write(lambda c: c.execute("SELECT COUNT(*) FROM settings_proposals").fetchone()[0])
        == 0
    )


@pytest.mark.parametrize("fence", ["settings_proposal", "json"])
@pytest.mark.parametrize(
    "patch",
    [
        {"output_dir": "D:/arbitrary"},
        {"command": "ffmpeg -i arbitrary"},
        {"quality_value": -2},
        {"quality_value": None},
        {"video_encoder": "libx264; arbitrary-command"},
        {"container": "exe"},
    ],
)
def test_both_fences_keep_parameter_whitelist_and_validation(proposal_case, fence, patch):
    service, context, store = proposal_case
    payload = {"patch": patch, "reason": "参数建议", "source_ids": ["known-source"]}
    answer = "```" + fence + "\n" + json.dumps(payload) + "\n```"
    with pytest.raises(AppError):
        service.from_answer(context, answer, [{"source_id": "known-source"}])
    assert store.get_settings() is None
    assert (
        store._write(lambda c: c.execute("SELECT COUNT(*) FROM settings_proposals").fetchone()[0])
        == 0
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"quality_value": 23},
        {"patch": {"quality_value": 23}},
        {"patch": {"quality_value": 23}, "reason": "缺少来源"},
        {"patch": {"quality_value": 23}, "reason": "空来源", "source_ids": []},
        {"patch": {"quality_value": 23}, "reason": "伪造来源", "source_ids": ["invented"]},
        {"patch": {"quality_value": 23}, "reason": "", "source_ids": ["known-source"]},
        {
            "patch": {"quality_value": 23},
            "reason": "包含额外动作",
            "source_ids": ["known-source"],
            "apply": True,
        },
        ["not a proposal"],
    ],
)
def test_json_fence_does_not_accept_arbitrary_json_or_unverified_sources(proposal_case, payload):
    service, context, store = proposal_case
    answer = "```json\n" + json.dumps(payload) + "\n```"
    with pytest.raises(AppError):
        service.from_answer(context, answer, [{"source_id": "known-source"}])
    assert store.get_settings() is None
    assert (
        store._write(lambda c: c.execute("SELECT COUNT(*) FROM settings_proposals").fetchone()[0])
        == 0
    )


@pytest.mark.parametrize("text", ['{"patch":{"quality_value":23}}', "```json5\n{}\n```"])
def test_unfenced_or_other_language_json_is_not_a_settings_proposal(proposal_case, text):
    service, context, _ = proposal_case
    assert service.from_answer(context, text, []) is None


def test_whitelist_sources_conflict_reject_and_idempotent_confirm(tmp_path):
    caps = inspect_toolchain(AppPaths.from_argument(tmp_path / "data"))
    with LocalStore(tmp_path / "state.sqlite3") as store:
        chats = ConversationStore(store)
        conversation = chats.create()
        base = ConversionSettings()
        context = chats.begin(conversation.conversation_id, "建议", base).context
        service = ProposalService(store, caps)
        sources = [{"source_id": "test-source", "title": "simulated unit evidence"}]

        def answer(patch):
            return (
                "```settings_proposal\n"
                + json.dumps({"patch": patch, "reason": "测试理由", "source_ids": ["test-source"]})
                + "\n```"
            )

        for patch in ({"output_dir": "D:/arbitrary"}, {"command": "ffmpeg"}, {"quality_value": -2}):
            with pytest.raises(AppError):
                service.from_answer(context, answer(patch), sources)
        proposal = service.from_answer(context, answer({"quality_value": 25}), sources)
        assert store.get_settings() is None
        with pytest.raises(AppError):
            service.apply(proposal.proposal_id, base.model_copy(update={"settings_version": 2}))
        changed, applied = service.apply(proposal.proposal_id, base)
        assert applied and changed.quality_value == 25 and changed.settings_version == 2
        assert base.quality_value == 23
        assert service.apply(proposal.proposal_id, changed) == (changed, False)
        rejected = service.from_answer(context, answer({"quality_value": 26}), sources)
        service.reject(rejected.proposal_id)
        with pytest.raises(AppError):
            service.apply(rejected.proposal_id, base)
