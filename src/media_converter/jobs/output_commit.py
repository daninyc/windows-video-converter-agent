import os

from media_converter.common.errors import AppError, ErrorCode
from media_converter.media.models import FileFingerprint
from media_converter.media.output_paths import available_path, contained_path


class OutputLease:
    """A newly created attempt directory owns the temporary file, never the final result."""

    def __init__(self, plan):
        self.plan = plan
        self.directory_identity = None
        self.published_path = None

    def _validate(self):
        plan = self.plan
        if (
            plan.output_root is None
            or plan.output_root.resolve() != plan.output_root
            or plan.temporary_path.parent.name != f".media-converter-{plan.attempt_id}"
            or plan.temporary_path.parent.parent != plan.final_path.parent
            or plan.temporary_path.suffix != plan.final_path.suffix
        ):
            raise AppError(ErrorCode.ACCESS_DENIED)
        contained_path(plan.output_root, plan.final_path)
        contained_path(plan.output_root, plan.temporary_path)
        if plan.source_path.resolve() in (plan.final_path.resolve(), plan.temporary_path.resolve()):
            raise AppError(ErrorCode.ACCESS_DENIED)

    def acquire(self):
        self._validate()
        self.plan.final_path.parent.mkdir(parents=True, exist_ok=True)
        self._validate()
        try:
            self.plan.temporary_path.parent.mkdir(exist_ok=False)
        except FileExistsError as error:
            raise AppError(ErrorCode.ACCESS_DENIED) from error
        self.directory_identity = FileFingerprint.from_path(
            self.plan.temporary_path.parent
        ).file_identity

    def _owned(self):
        directory = self.plan.temporary_path.parent
        return (
            self.directory_identity is not None
            and directory.is_dir()
            and not directory.is_symlink()
            and not directory.is_junction()
            and FileFingerprint.from_path(directory).file_identity == self.directory_identity
        )

    def commit(self):
        self._validate()
        temporary = self.plan.temporary_path
        if not self._owned() or temporary.is_symlink() or not temporary.is_file():
            raise AppError(ErrorCode.ACCESS_DENIED)
        if (
            FileFingerprint.from_path(temporary).file_identity
            == self.plan.source_fingerprint.file_identity
        ):
            raise AppError(ErrorCode.ACCESS_DENIED)
        desired = self.plan.final_path
        for _ in range(1000):
            candidate = available_path(desired, self.plan.source_path)
            contained_path(self.plan.output_root, candidate)
            try:
                os.link(temporary, candidate)
            except FileExistsError:
                continue
            self.published_path = candidate
            temporary.unlink()
            return candidate
        raise AppError(ErrorCode.ACCESS_DENIED)

    def cleanup(self):
        if not self._owned():
            return
        self._validate()
        temporary = self.plan.temporary_path
        if temporary.is_file() or temporary.is_symlink():
            temporary.unlink()
        try:
            temporary.parent.rmdir()
        except OSError:
            # Other files are never removed, even inside a directory this attempt created.
            pass
