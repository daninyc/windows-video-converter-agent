import json
import re
from typing import Literal

from pydantic import Field, ValidationError

from media_converter.agent.models import SettingsProposal
from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import ConversionSettings, FrameRate, FrozenModel, Resolution
from media_converter.media.settings import SettingsService


class SettingsPatch(FrozenModel):
    container: Literal["mp4", "mkv", "webm"] | None = None
    video_encoder: str | None = Field(default=None, max_length=80)
    quality_mode: Literal["crf", "bitrate"] | None = None
    quality_value: int | None = None
    video_bitrate_bps: int | None = None
    resolution: Resolution | None = None
    frame_rate: FrameRate | None = None
    audio_encoder: str | None = Field(default=None, max_length=80)
    audio_bitrate_bps: int | None = None


class ProposalContent(FrozenModel):
    patch: SettingsPatch
    reason: str = Field(min_length=1, max_length=2000)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=20)


class ProposalService:
    def __init__(self, store, capabilities):
        self.store, self.settings = store, SettingsService(capabilities)

    def from_answer(self, context, text, sources):
        match = re.search(r"```(?:settings_proposal|json)\s*\n(.*?)```", text, re.S)
        if match is None:
            return None
        try:
            value = ProposalContent.model_validate_json(match[1])
            patch = value.patch.model_dump(exclude_unset=True)
            allowed = {source["source_id"] for source in sources}
            if not set(value.source_ids) <= allowed:
                raise AppError(ErrorCode.INVALID_ARGUMENT)
            if not patch:
                return None
            base = ConversionSettings.model_validate_json(context.settings_json)
            checked = self.settings.update(base, patch)
            if not checked.valid:
                raise AppError(ErrorCode.INVALID_ARGUMENT)
            proposal = SettingsProposal(
                conversation_id=context.conversation_id,
                turn_id=context.turn_id,
                base_settings_version=context.settings_version,
                patch_json=json.dumps(patch),
                reason=value.reason,
                sources_json=json.dumps(
                    [s for s in sources if s["source_id"] in value.source_ids], ensure_ascii=False
                ),
            )
            self.store._write(
                lambda c: c.execute(
                    "INSERT INTO settings_proposals VALUES(?,?,?,?)",
                    (
                        proposal.proposal_id,
                        proposal.conversation_id,
                        proposal.status,
                        proposal.model_dump_json(),
                    ),
                )
            )
            return proposal
        except ValidationError as error:
            raise AppError(ErrorCode.INVALID_ARGUMENT) from error

    def get(self, proposal_id):
        with __import__("contextlib").closing(__import__("sqlite3").connect(self.store.path)) as c:
            row = c.execute(
                "SELECT payload FROM settings_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if not row:
            raise AppError(ErrorCode.INVALID_ARGUMENT)
        return SettingsProposal.model_validate_json(row[0])

    def apply(self, proposal_id, current):
        def operation(c):
            row = c.execute(
                "SELECT payload FROM settings_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if not row:
                raise AppError(ErrorCode.INVALID_ARGUMENT)
            proposal = SettingsProposal.model_validate_json(row[0])
            if proposal.status == "APPLIED":
                return current, False
            if (
                proposal.status != "PENDING"
                or proposal.base_settings_version != current.settings_version
            ):
                raise AppError(ErrorCode.INVALID_STATE)
            result = self.settings.update(current, json.loads(proposal.patch_json))
            if not result.valid:
                raise AppError(ErrorCode.INVALID_ARGUMENT)
            self.store._save(c, "settings", "current", result.settings.model_dump(mode="json"))
            applied = proposal.model_copy(update={"status": "APPLIED"})
            c.execute(
                "UPDATE settings_proposals SET status=?,payload=? WHERE proposal_id=?",
                ("APPLIED", applied.model_dump_json(), proposal_id),
            )
            return result.settings, True

        return self.store._write(operation)

    def reject(self, proposal_id):
        def operation(c):
            row = c.execute(
                "SELECT payload FROM settings_proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if row:
                value = SettingsProposal.model_validate_json(row[0])
                if value.status == "PENDING":
                    value = value.model_copy(update={"status": "REJECTED"})
                    c.execute(
                        "UPDATE settings_proposals SET status=?,payload=? WHERE proposal_id=?",
                        (value.status, value.model_dump_json(), proposal_id),
                    )

        self.store._write(operation)
