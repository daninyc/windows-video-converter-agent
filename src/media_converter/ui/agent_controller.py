import asyncio
import json
import re
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFileDialog, QListWidgetItem, QScrollArea

from media_converter.agent.service import AgentService
from media_converter.agent.settings_proposals import ProposalService
from media_converter.common.context import CallContext
from media_converter.common.errors import AppError
from media_converter.config import application_root
from media_converter.services.config import ConfigService
from media_converter.ui.agent_panel import AgentPanel
from media_converter.ui.api_settings import APISettingsDialog
from media_converter.ui.settings_diff import SettingsDiffDialog


class AgentController(QObject):
    _incoming = Signal(object)

    def __init__(self, window, store, bridge, conversion, *, adapter=None):
        super().__init__(window)
        self.window, self.store, self.bridge, self.conversion = window, store, bridge, conversion
        self.panel = AgentPanel(window)
        layout = window.agent_dock.widget().layout()
        while layout.count() > 1:
            item = layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setWidget(self.panel)
        scroll.setMinimumWidth(320)
        layout.addWidget(scroll)
        self.service = None
        self.closed = False
        self.current_id = None
        self.pending = {}
        self.active_turns = {}
        self.turn_states = {}
        self.proposals = {}
        self.tool_summaries = {}
        self._incoming.connect(self._agent_event, Qt.ConnectionType.QueuedConnection)
        bridge.event_received.connect(self.runtime_event)
        self.panel.send_requested.connect(self.send)
        self.panel.new_requested.connect(self.new_conversation)
        self.panel.conversation_selected.connect(self.select)
        self.panel.stop_requested.connect(self.stop)
        self.panel.retry_requested.connect(self.retry)
        self.panel.api_requested.connect(self.api_settings)
        self.panel.reference_video.connect(lambda: self.reference_selected("video"))
        self.panel.reference_task.connect(lambda: self.reference_selected("task"))
        self.panel.reference_file.connect(self.reference_file)
        self.panel.revoke_requested.connect(self.revoke)
        self.panel.proposal_requested.connect(self.proposal_preview)
        self.panel.sources.itemDoubleClicked.connect(self.open_source)
        self.panel.send_button.setEnabled(False)
        self.panel.stop_button.setEnabled(False)

        async def initialize():
            self.service = AgentService(
                store, window.paths.data_dir, self._incoming.emit, adapter=adapter
            )
            self.service.start_sync()
            values = await asyncio.to_thread(self.service.chats.list_conversations)
            if not values:
                values = [await asyncio.to_thread(self.service.chats.create)]
            return values

        self.submit(initialize, self.initialized)

    def submit(self, factory, callback=None):
        if self.closed:
            return
        identity = self.bridge.submit(factory)
        self.pending[identity] = callback

    def runtime_event(self, event):
        if event.task_id not in self.pending:
            return
        callback = self.pending.pop(event.task_id)
        if self.closed:
            return
        if event.state == "succeeded":
            if callback:
                callback(event.data)
        else:
            self.panel.status.setText(event.error.message if event.error else "操作已取消")

    def initialized(self, values):
        self.current_id = values[0].conversation_id
        self.panel.set_conversations(values, self.current_id)
        self.panel.send_button.setEnabled(True)
        self.refresh()

    def refresh(self):
        if not self.service or not self.current_id:
            return
        identity = self.current_id

        def load():
            chats = self.service.chats
            messages = chats.messages(identity)
            rendered = []
            sources = {}
            for message in messages:
                prefix = "你" if message.role == "user" else "助手"
                fixed = ""
                if message.role == "user" and message.turn_id:
                    turn = chats.turn(message.turn_id)
                    fixed = "\n本轮引用：" + "、".join(r.label for r in turn.context.references)
                    if turn.state == "INTERRUPTED":
                        fixed += "\n上次回答已中断，可显式重试。"
                if message.text:
                    visible = re.sub(
                        r"```settings_proposal\s*\n.*?```",
                        "（参数建议可通过按钮预览）",
                        message.text,
                        flags=re.S,
                    )
                    rendered.append(prefix + fixed + "\n" + visible)
                for source in json.loads(message.sources_json):
                    sources[source["source_id"]] = source
            pending = chats._rows(
                "SELECT proposal_id FROM settings_proposals WHERE conversation_id=? "
                "AND status='PENDING' ORDER BY rowid DESC LIMIT 1",
                (identity,),
            )
            return (
                chats.references(identity),
                "\n\n".join(rendered),
                list(sources.values()),
                pending,
            )

        def loaded(data):
            if self.current_id != identity:
                return
            refs, text, sources, pending = data
            if pending:
                self.proposals[identity] = pending[0][0]
            self.panel.proposal_button.setEnabled(bool(pending))
            self.panel.references.clear()
            self.panel.reference_toggle.setText(f"引用素材（{len(refs)}） · 展开管理")
            for ref in refs:
                kind_label = {"file": "文档", "video": "视频", "task": "任务"}[ref.kind]
                item = QListWidgetItem(f"{kind_label} · {ref.label}")
                item.setData(Qt.ItemDataRole.UserRole, ref.reference_id)
                self.panel.references.addItem(item)
            self.panel.messages.setPlainText(text)
            self.panel.sources.clear()
            self.panel.sources.setVisible(bool(sources))
            for source in sources:
                title = (
                    source.get("title")
                    or source.get("section")
                    or source.get("source_path")
                    or source.get("source_id")
                )
                item = QListWidgetItem(str(title))
                item.setData(Qt.ItemDataRole.UserRole, source)
                self.panel.sources.addItem(item)

        self.submit(lambda: asyncio.to_thread(load), loaded)

    def select(self, identity):
        if identity:
            self.current_id = identity
            self.panel.tool_details.setPlainText(
                "\n".join(self.tool_summaries.get(identity, [])[-30:])
            )
            self.panel.trace.setText("诊断标识：本会话发送问题后显示")
            self.panel.proposal_button.setEnabled(identity in self.proposals)
            self.refresh()

    def new_conversation(self):
        if not self.service:
            return

        async def create():
            value = await asyncio.to_thread(self.service.chats.create)
            values = await asyncio.to_thread(self.service.chats.list_conversations)
            return value, values

        def created(data):
            value, values = data
            self.current_id = value.conversation_id
            self.panel.set_conversations(values, self.current_id)
            self.refresh()

        self.submit(create, created)

    def send(self, text):
        if not self.service or not self.current_id or not self.conversion.ready:
            return
        identity = self.current_id
        settings = self.window.settings_panel._current
        refs = tuple(
            self.panel.references.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.panel.references.count())
        )

        async def send():
            if self.service.proposals is None:
                self.service.proposals = ProposalService(self.store, self.conversion.capabilities)
            return await self.service.submit(identity, text, settings, refs)

        def sent(turn):
            self.panel.input.clear()
            self.refresh()

        self.submit(send, sent)

    def _agent_event(self, event):
        if self.closed:
            return
        context = event["context"]
        identity = context.conversation_id
        kind = event["kind"]
        if identity == self.current_id:
            self.panel.trace.setText("诊断标识：" + context.trace_id)
        if kind == "state":
            self.turn_states[context.turn_id] = (identity, event["state"])
            active = [
                (turn_id, state)
                for turn_id, (chat, state) in self.turn_states.items()
                if chat == identity and state in {"QUEUED", "RUNNING"}
            ]
            running = next((turn_id for turn_id, state in active if state == "RUNNING"), None)
            if active:
                self.active_turns[identity] = running or active[0][0]
            else:
                self.active_turns.pop(identity, None)
            if identity == self.current_id:
                self.panel.stop_button.setEnabled(bool(active))
                state_label = {
                    "QUEUED": "等待回答",
                    "RUNNING": "正在回答",
                    "SUCCEEDED": "回答完成",
                    "FAILED": "回答未完成",
                    "CANCELLED": "已停止",
                    "INTERRUPTED": "上次回答已中断",
                }[event["state"]]
                if running:
                    state_label = f"正在回答 · 另有 {sum(s == 'QUEUED' for _, s in active)} 条排队"
                self.panel.status.setText(
                    state_label
                    + (
                        " · " + self.error_message(event["error_code"])
                        if event.get("error_code")
                        else ""
                    )
                )
                self.refresh()
        elif kind == "delta":
            if identity == self.current_id:
                cursor = self.panel.messages.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                cursor.insertText(event["text"])
                self.panel.messages.setTextCursor(cursor)
        elif kind == "tool" and identity == self.current_id:
            self.bridge.logger.event(
                "tool.finished",
                CallContext(
                    instance_id=context.instance_id,
                    conversation_id=context.conversation_id,
                    turn_id=context.turn_id,
                    trace_id=context.trace_id,
                ),
                tool_name=event["tool_name"],
                state=event["state"],
                cache_state=event.get("cache_state"),
            )
            tool_label = {
                "rag_search": "检索内置资料",
                "lookup_technical_rules": "查询参数规则",
                "list_conversion_presets": "查询预设",
                "query_conversion_history": "查询转换记录",
                "read_local_file": "读取引用文档",
                "search_web": "搜索网页",
            }.get(event["tool_name"], "查询工具")
            self.panel.status.setText(
                tool_label
                + " · "
                + (
                    "执行中"
                    if event["state"] == "RUNNING"
                    else "完成"
                    if event["state"] == "SUCCEEDED"
                    else "未完成"
                )
            )
            summaries = self.tool_summaries.setdefault(identity, [])
            summaries.append(
                tool_label
                + " · "
                + event["state"]
                + " · "
                + event.get("cache_state", "")
                + " · trace="
                + context.trace_id
            )
            self.panel.tool_details.setPlainText("\n".join(summaries[-30:]))
        elif kind == "proposal":
            self.proposals[identity] = event["proposal"].proposal_id
            if identity == self.current_id:
                self.panel.proposal_button.setEnabled(True)
        elif kind == "proposal_invalid" and identity == self.current_id:
            self.panel.status.setText("参数建议未通过校验，设置未变更。")

    def stop(self):
        turn_id = self.active_turns.get(self.current_id)
        if turn_id:
            self.submit(lambda: self.service.cancel(turn_id))

    @staticmethod
    def error_message(code):
        from media_converter.common.errors import ErrorCode

        try:
            info = AppError(ErrorCode(code)).info
            return info.message + "；" + info.suggested_action
        except ValueError:
            return "本轮未完成，请查看诊断标识并重试"

    def retry(self):
        if not self.service:
            return
        messages = self.service.chats.messages(self.current_id)
        latest = next((m for m in reversed(messages) if m.role == "user"), None)
        if latest:
            self.send(latest.text)

    def reference_selected(self, kind):
        row = self.conversion.selected_row()
        if row:
            entity = (
                row.asset.asset_id
                if kind == "video"
                else row.attempt.attempt_id
                if row.attempt
                else None
            )
            if entity:
                self.add_reference(kind, entity)

    def reference_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window, "引用文档", "", "文档 (*.txt *.md *.log *.pdf *.docx)"
        )
        if path:
            self.add_reference("file", path)

    def add_reference(self, kind, entity):
        if self.service and self.current_id:
            identity = self.current_id
            self.submit(
                lambda: asyncio.to_thread(self.service.chats.add_reference, identity, kind, entity),
                lambda value: self.refresh(),
            )

    def revoke(self):
        item = self.panel.references.currentItem()
        if item:
            identity = self.current_id
            reference_id = item.data(Qt.ItemDataRole.UserRole)
            self.submit(
                lambda: asyncio.to_thread(self.service.chats.revoke, identity, reference_id),
                lambda value: self.refresh(),
            )

    def api_settings(self):
        from media_converter.agent.deepseek_adapter import DeepSeekAdapter

        config = ConfigService(self.window.paths.data_dir)

        def test(label):
            self.submit(
                lambda: DeepSeekAdapter(config).connection_test(),
                lambda result: label.setText(
                    "连接成功"
                    if result["configured_model_available"]
                    else "连接成功，未发现所配置模型"
                ),
            )

        APISettingsDialog(config, self.window, on_test=test).exec()

    def proposal_preview(self):
        proposal_id = self.proposals.get(self.current_id)
        if not proposal_id or not self.service.proposals:
            return
        service = self.service.proposals
        proposal = service.get(proposal_id)
        current = self.window.settings_panel._current
        dialog = SettingsDiffDialog(proposal, current, self.window)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                settings, applied = service.apply(proposal_id, self.window.settings_panel._current)
                if applied:
                    self.window.settings_panel.set_settings(settings)
                self.panel.status.setText("建议已应用到下一批；请核对后手动开始转换。")
            except AppError:
                self.panel.status.setText("建议已失效或设置版本冲突，请重新生成。")
        else:
            service.reject(proposal_id)

    def open_source(self, item):
        source = item.data(Qt.ItemDataRole.UserRole)
        url = source.get("url") or source.get("source_url")
        if url and urlsplit(url).scheme in {"https", "http"}:
            QDesktopServices.openUrl(QUrl(url))
        elif source.get("source_path"):
            root = (application_root() / "knowledge").resolve()
            target = (root / source["source_path"]).resolve()
            if target.is_relative_to(root) and target.is_file():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        elif source.get("reference_id") or source.get("file_ref_id"):
            ref_id = source.get("reference_id") or source["file_ref_id"]
            ref = next(
                (
                    r
                    for r in self.service.chats.references(self.current_id)
                    if r.reference_id == ref_id
                ),
                None,
            )
            if ref and ref.kind == "video":
                index = next(
                    (
                        i
                        for i, row in enumerate(self.conversion.model.rows)
                        if row.asset.asset_id == ref.entity_id
                    ),
                    None,
                )
                if index is not None:
                    self.window.task_table.selectRow(index)
            self.panel.status.setText(
                (ref.label if ref else "引用已撤销")
                + " · "
                + json.dumps(source.get("locations", []), ensure_ascii=False)
            )
        else:
            self.panel.status.setText(json.dumps(source, ensure_ascii=False))

    async def shutdown(self):
        self.closed = True
        if self.service:
            await self.service.close()
