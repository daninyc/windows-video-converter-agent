import asyncio

from PySide6.QtCore import QObject, Qt, Signal, Slot

from media_converter.common.context import new_id
from media_converter.common.errors import AppError, ErrorCode
from media_converter.jobs.job_service import JobService
from media_converter.jobs.models import JobState
from media_converter.media.importer import ImportService
from media_converter.media.models import ConversionSettings, FileFingerprint, MediaAsset
from media_converter.media.output_paths import path_key
from media_converter.media.planner import ConversionPlanner
from media_converter.media.presets import PresetService, open_output_location
from media_converter.media.probe import ProbeService
from media_converter.media.thumbnail import ThumbnailService
from media_converter.media.toolchain import inspect_toolchain_async
from media_converter.ui.import_actions import ImportActions
from media_converter.ui.loss_confirmation import confirm_losses
from media_converter.ui.preset_actions import PresetActions
from media_converter.ui.task_model import STATE_LABELS, format_duration


def error_text(code):
    try:
        info = AppError(ErrorCode(code)).info
        return f"{info.message}（{info.code}）。{info.suggested_action}"
    except ValueError:
        return "任务在上次运行中中断，可重试。"


class ConversionController(QObject):
    _job_signal = Signal(object)
    _media_signal = Signal(object)
    _thumbnail_signal = Signal(object, object)

    def __init__(self, window, store, bridge):
        super().__init__(window)
        self.window, self.store, self.bridge = window, store, bridge
        self.model = window.task_model
        self.ready = False
        self.closed = False
        self.importing = False
        self.planning = False
        self.active_batch = None
        self.finished_batches = {}
        self._pending = {}
        self._remember_lock = asyncio.Lock()
        self.import_actions = ImportActions(window, window.recursive_checkbox)
        self.presets_actions = PresetActions(window.settings_panel)
        self.import_actions.paths_requested.connect(self.import_paths)
        self.presets_actions.save_requested.connect(self.save_preset)
        self.presets_actions.load_requested.connect(self.load_preset)
        self._job_signal.connect(self._job_event, Qt.ConnectionType.QueuedConnection)
        self._media_signal.connect(self._media_ready, Qt.ConnectionType.QueuedConnection)
        self._thumbnail_signal.connect(self._thumbnail_ready, Qt.ConnectionType.QueuedConnection)
        bridge.event_received.connect(self._runtime_event)
        window.start_button.clicked.connect(self.start)
        window.cancel_button.clicked.connect(lambda: self.cancel(False))
        window.cancel_batch_button.clicked.connect(lambda: self.cancel(True))
        window.retry_button.clicked.connect(self.retry_selected)
        window.open_button.clicked.connect(self.open_selected)
        window.remove_button.clicked.connect(self.remove_selected)
        window.refresh_button.clicked.connect(self.refresh_selected)
        window.settings_panel.settings_changed.connect(self._settings_changed)
        window.settings_panel.validation_changed.connect(self._update_actions)
        window.task_table.selectionModel().selectionChanged.connect(self._selection_changed)
        window.closing.connect(self.close)
        self._submit(self._initialise, self._initialised)

    def _submit(self, factory, success=None, failure=None):
        if self.closed:
            return None
        identity = self.bridge.submit(factory)
        self._pending[identity] = (success, failure)
        return identity

    @Slot(object)
    def _runtime_event(self, event):
        handlers = self._pending.pop(event.task_id, None)
        if handlers is None or self.closed:
            return
        success, failure = handlers
        if event.state == "succeeded":
            if success:
                success(event.data)
        elif event.state == "failed":
            self.window.notice_label.setText(error_text(event.error.code))
            if failure:
                failure()
        self._update_actions()

    async def _initialise(self):
        self.capabilities = await inspect_toolchain_async(self.window.paths)
        self.capabilities.require_ready()
        self.importer = ImportService(self.store, [self.window.paths.data_dir])
        self.probe = ProbeService(self.capabilities.ffprobe.path, self.store)
        self.thumbnails = ThumbnailService(
            self.capabilities.ffmpeg.path, self.window.paths.data_dir / "thumbnails"
        )
        self.planner = ConversionPlanner(self.capabilities)
        self.presets = PresetService(self.store, self.capabilities)
        self.jobs = JobService(
            self.store, self.capabilities, self._job_signal.emit, logger=self.bridge.logger
        )
        assets = await asyncio.to_thread(self.store.list_assets)
        attempts = await asyncio.to_thread(self.store.list_attempts)
        restored = await asyncio.to_thread(self.presets.restore)
        presets = await asyncio.to_thread(self.presets.list)
        return assets, attempts, restored, presets

    def _initialised(self, data):
        assets, attempts, restored, presets = data
        self.ready = True
        panel = self.window.settings_panel
        panel.setEnabled(True)
        panel.set_capabilities(self.capabilities)
        panel.set_settings(restored.settings or ConversionSettings())
        self.presets_actions.set_presets(presets)
        for asset in assets:
            self.model.add(asset)
        for attempt in attempts:
            self.model.set_attempt(attempt)
        self.window.notice_label.setText(
            "；".join(issue.message for issue in restored.issues)
            or "视频组件就绪。添加视频后可设置并开始转换。"
        )
        for asset in assets:
            self._queue_media(asset)
        self.window.empty_label.setVisible(not self.model.rows)
        self._update_actions()

    def import_paths(self, paths, recursive=False):
        if not self.ready or self.importing or self.closed:
            return
        self.importing = True
        validation = self.window.settings_panel.validation()
        settings = validation.settings if validation and validation.valid else None
        self.window.notice_label.setText("正在扫描所选文件和目录…")

        async def importing():
            if settings and settings.output_dir:
                self.importer.excluded_directories.add(settings.output_dir.resolve())
            return await asyncio.to_thread(self.importer.import_paths, paths, recursive)

        self._submit(importing, self._imported, self._import_failed)
        self._update_actions()

    def _import_failed(self):
        self.importing = False

    def _imported(self, result):
        self.importing = False
        for asset in result.assets:
            self.model.add(asset)
            self._queue_media(asset)
        self.window.empty_label.setVisible(not self.model.rows)
        self.window.notice_label.setText(
            f"已导入 {len(result.assets)} 个视频；跳过 {len(result.rejected)} 项。"
        )
        self.window.import_report.setVisible(bool(result.rejected))
        self.window.import_report.setPlainText(
            "\n".join(f"{item.path}：{item.reason}" for item in result.rejected)
        )
        if result.assets:
            index = self.model.find(result.assets[0].asset_id)
            self.window.task_table.selectRow(index)

    def _queue_media(self, asset, force=False):
        probing = MediaAsset.model_validate({**asset.model_dump(), "probe_status": "probing"})
        self.model.update_asset(probing)

        async def load():
            checked = await self.probe.probe(asset, force=force)
            self._media_signal.emit(checked)
            result = await self.thumbnails.get(checked)
            self._thumbnail_signal.emit(checked, result)

        self._submit(load)

    @Slot(object)
    def _media_ready(self, asset):
        if not self.closed:
            self.model.update_asset(asset)
            self._selection_changed()
            self._update_actions()

    @Slot(object, object)
    def _thumbnail_ready(self, asset, result):
        if not self.closed:
            self.model.set_thumbnail(asset, result)

    def selected_row(self):
        index = self.window.task_table.currentIndex()
        return (
            self.model.rows[index.row()]
            if index.isValid() and index.row() < len(self.model.rows)
            else None
        )

    def _selection_changed(self, *args):
        row = self.selected_row()
        if row is None:
            self.window.details_panel.setPlainText("选择视频后查看详细信息。")
            self._update_actions()
            return
        asset = row.asset
        raw_size = f"{asset.width} × {asset.height}" if asset.width and asset.height else "未知"
        visible_size = (
            f"{asset.height} × {asset.width}" if asset.rotation_deg in (90, 270) else raw_size
        )
        rate = asset.average_frame_rate or asset.frame_rate
        fps = f"{rate.numerator}/{rate.denominator}" if rate else "未知"
        rotation = asset.rotation_deg if asset.rotation_deg is not None else "未知"
        bitrate = asset.bitrate_bps or "未知"
        text = [
            str(asset.resolved_path),
            f"容器：{asset.container or '未知'}    时长：{format_duration(asset.duration_us)}",
            f"像素：{raw_size}    可视方向：{visible_size}    旋转：{rotation}°",
            f"帧率：{fps}    大小：{asset.fingerprint.size_bytes} 字节\n码率：{bitrate} bit/s",
        ]
        for stream in asset.streams:
            text.append(
                f"轨道 #{stream.stream_index} · {stream.kind} · {stream.codec or '未知'} · "
                f"{stream.language or '语言未知'} · "
                f"{'默认' if 'default' in stream.disposition else '非默认'}"
                + (
                    f" · {stream.channels or '未知'} 声道 / {stream.sample_rate_hz or '未知'} Hz"
                    if stream.kind == "audio"
                    else ""
                )
            )
        if asset.probe_error_code:
            text.append(error_text(asset.probe_error_code))
        if row.attempt:
            text.append("转换：" + STATE_LABELS[row.attempt.state])
            if row.attempt.error_code:
                text.append(error_text(row.attempt.error_code))
            if row.attempt.output_path:
                text.append("实际输出：" + row.attempt.output_path)
        self.window.details_panel.setPlainText("\n".join(text))
        self._update_actions()

    def _update_actions(self):
        if self.closed:
            return
        busy = self.planning or self.active_batch is not None
        self.window.add_files_button.setEnabled(self.ready and not self.importing)
        self.window.add_folder_button.setEnabled(self.ready and not self.importing)
        self.window.empty_label.setVisible(not self.model.rows)
        validation = (
            self.window.settings_panel.validation(require_output=True) if self.ready else None
        )
        readable = any(row.asset.probe_status == "succeeded" for row in self.model.rows)
        probing = any(row.asset.probe_status in ("pending", "probing") for row in self.model.rows)
        enabled = bool(
            self.ready and readable and not probing and not busy and validation and validation.valid
        )
        self.window.start_button.setEnabled(enabled)
        if not busy and not self.finished_batches:
            count = len(self.model.rows)
            next_step = (
                "正在读取信息"
                if probing
                else "可开始转换"
                if enabled
                else "选择输出目录并检查参数"
                if readable
                else "等待导入"
            )
            self.window.progress_label.setText(f"{count} 个视频 · {next_step}")
        self.window.start_button.setToolTip(
            "开始转换列表中的可用视频"
            if enabled
            else "请等待信息读取完成，确认参数有效并选择输出位置；坏文件不会阻止其他已读取的视频"
        )
        self.window.cancel_button.setEnabled(self.active_batch is not None)
        self.window.cancel_batch_button.setEnabled(self.active_batch is not None)
        row = self.selected_row()
        self.window.remove_button.setEnabled(row is not None and not busy)
        self.window.refresh_button.setEnabled(row is not None and not busy and self.ready)
        retryable = (
            row is not None
            and row.attempt
            and row.attempt.state in {JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}
        )
        self.window.retry_button.setEnabled(bool(retryable and not busy))
        self.window.open_button.setEnabled(bool(row and row.attempt and row.attempt.output_path))

    def _settings_changed(self, settings):
        self._update_actions()
        if self.ready and self.window.settings_panel.validation(require_output=True).valid:

            async def remember():
                async with self._remember_lock:
                    await asyncio.to_thread(self.presets.remember, settings)

            self._submit(remember)

    async def _prepare(self, settings, assets):
        plans, refreshed, errors, reserved = [], [], [], set()
        for asset in assets:
            try:
                if FileFingerprint.from_path(asset.resolved_path) != asset.fingerprint:
                    asset = await self.probe.probe(asset, force=True)
                refreshed.append(asset)
                root = await asyncio.to_thread(self.store.get_import_root, asset.root_id)
                if root is None:
                    raise AppError(ErrorCode.INVALID_ARGUMENT)
                plan = await asyncio.to_thread(
                    self.planner.plan_one, settings, asset, root, reserved=reserved
                )
                reserved.add(path_key(plan.final_path))
                plans.append(plan)
            except (AppError, OSError) as error:
                errors.append(
                    f"{asset.resolved_path.name}："
                    + error_text(
                        error.info.code if isinstance(error, AppError) else ErrorCode.PROCESS_FAILED
                    )
                )
        return tuple(plans), refreshed, errors

    def start(self):
        if not self.ready or self.planning or self.active_batch:
            return
        validation = self.window.settings_panel.validation(require_output=True)
        if not validation.valid:
            self.window.notice_label.setText(
                "；".join(issue.message for issue in validation.issues)
            )
            return
        assets = tuple(
            row.asset for row in self.model.rows if row.asset.probe_status == "succeeded"
        )
        if not assets:
            return
        settings = validation.settings
        self.planning = True
        self.window.notice_label.setText("正在检查来源、输出路径与轨道兼容性…")
        self._submit(
            lambda: self._prepare(settings, assets),
            lambda result: self._prepared(result, settings.settings_version),
            self._planning_failed,
        )
        self._update_actions()

    def _planning_failed(self):
        self.planning = False

    def _prepared(self, result, settings_version=None, retry_id=None):
        plans, refreshed, errors = result
        for asset in refreshed:
            self.model.update_asset(asset)
        if errors:
            self.window.import_report.setPlainText("\n".join(errors))
            self.window.import_report.show()
        current = self.window.settings_panel.validation()
        if not plans or (
            retry_id is None
            and (not current.valid or current.settings.settings_version != settings_version)
        ):
            self.planning = False
            self.window.notice_label.setText("没有可执行计划，或参数已经变化。请检查后重新开始。")
            self._update_actions()
            return
        confirmed = confirm_losses(plans, self.window)
        current = self.window.settings_panel.validation()
        if confirmed is None or (
            retry_id is None
            and (not current.valid or current.settings.settings_version != settings_version)
        ):
            self.planning = False
            self.window.notice_label.setText("本次转换未开始：未确认轨道丢失或参数已变化。")
            self._update_actions()
            return
        command_id = new_id()

        async def factory():
            if retry_id:
                return await self.jobs.retry(retry_id, confirmed[0])
            return await self.jobs.start_batch(confirmed, command_id)

        self._submit(factory, self._started, self._planning_failed)

    def _started(self, batch_id):
        self.planning = False
        if batch_id not in self.finished_batches:
            self.active_batch = batch_id
        self._update_actions()

    @Slot(object)
    def _job_event(self, event):
        if self.closed:
            return
        if event.kind == "batch_started":
            self.active_batch = event.batch_id
            self.planning = False
            self.window.notice_label.setText("本批参数已固定；设置更改用于下一批。")
        if event.attempt:
            self.model.set_attempt(event.attempt)
        counts = event.counts
        self.window.progress_label.setText(
            f"成功 {counts['succeeded']} · 失败 {counts['failed']} · "
            f"取消 {counts['cancelled']} / 共 {counts['total']}"
            + (" · " + STATE_LABELS[event.attempt.state] if event.attempt else "")
        )
        if event.kind == "progress":
            index = self.model.find(event.attempt.asset_id)
            duration = self.model.rows[index].asset.duration_us if index is not None else None
            percent = event.progress.percentage(duration)
            self.window.progress_bar.setRange(0, 0 if percent is None else 100)
            if percent is not None:
                self.window.progress_bar.setValue(
                    round((counts["completed"] * 100 + percent) / max(1, counts["total"]))
                )
        if event.kind == "batch_finished":
            self.active_batch = None
            self.planning = False
            self.finished_batches[event.batch_id] = counts
            self.window.progress_bar.setRange(0, 100)
            self.window.progress_bar.setValue(100)
            self.window.notice_label.setText(
                f"本批处理结束：成功 {counts['succeeded']}、失败 {counts['failed']}、"
                f"取消 {counts['cancelled']}。"
            )
        self._selection_changed()

    def cancel(self, whole_batch):
        if self.active_batch:
            batch_id = self.active_batch
            self._submit(
                lambda: (
                    self.jobs.cancel_batch(batch_id)
                    if whole_batch
                    else self.jobs.cancel_current(batch_id)
                ),
                lambda accepted: self.window.notice_label.setText(
                    "已请求取消，正在等待所属进程停止。"
                    if accepted
                    else "当前结果已完成发布，无法再取消；整批请求仍会阻止后项启动。"
                ),
            )

    def retry_selected(self):
        row = self.selected_row()
        if row is None or row.attempt is None or self.active_batch or self.planning:
            return
        attempt_id = row.attempt.attempt_id
        self.planning = True
        self._submit(
            lambda: self.jobs.prepare_retry(attempt_id),
            lambda plan: self._prepared(((plan,), (plan.source_asset,), []), retry_id=attempt_id),
            self._planning_failed,
        )
        self._update_actions()

    def refresh_selected(self):
        row = self.selected_row()
        if row and not self.active_batch and not self.planning:
            self._queue_media(row.asset, force=True)
            self._update_actions()

    def remove_selected(self):
        if self.active_batch or self.planning:
            return
        identities = [
            self.model.rows[index.row()].asset.asset_id
            for index in self.window.task_table.selectionModel().selectedRows()
        ]
        for identity in identities:
            self.model.remove(identity)
            self._submit(
                lambda identity=identity: asyncio.to_thread(self.store.archive_asset, identity)
            )
        self._selection_changed()

    def open_selected(self):
        row = self.selected_row()
        if row and row.attempt and row.attempt.output_path:
            try:
                open_output_location(row.attempt.output_path)
            except AppError as error:
                self.window.notice_label.setText(error_text(error.info.code))

    def save_preset(self, name):
        validation = self.window.settings_panel.validation()
        if validation and validation.valid:

            async def save():
                identity = await asyncio.to_thread(self.presets.save, name, validation.settings)
                return await asyncio.to_thread(self.presets.list), identity

            self._submit(save, lambda data: self.presets_actions.set_presets(*data))

    def load_preset(self, identity):
        def loaded(restored):
            if restored.issues:
                self.window.notice_label.setText(
                    "预设未应用：" + "；".join(item.message for item in restored.issues)
                )
            else:
                version = self.window.settings_panel._current.settings_version + 1
                settings = ConversionSettings.model_validate(
                    {**restored.settings.model_dump(), "settings_version": version}
                )
                self.window.settings_panel.set_settings(settings)
                self.window.notice_label.setText("预设已应用到下一批参数。")

        self._submit(lambda: asyncio.to_thread(self.presets.load, identity), loaded)

    def close(self):
        if not self.closed:
            self.closed = True

            async def shutdown():
                operations = []
                if self.ready:
                    operations.append(self.jobs.shutdown())
                agent = getattr(self.window, "agent_controller", None)
                if agent:
                    operations.append(agent.shutdown())
                if operations:
                    await asyncio.gather(*operations)
                setup = getattr(self.window, "setup_controller", None)
                if setup:
                    await setup.shutdown()

            self.bridge.close(shutdown)
