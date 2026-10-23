import asyncio
import json
import threading

import pytest
from PySide6.QtCore import Qt

from media_converter.agent.deepseek_adapter import ModelResponse
from media_converter.config import AppPaths, application_root
from media_converter.storage.local_store import LocalStore
from media_converter.ui.agent_controller import AgentController
from media_converter.ui.conversion_controller import ConversionController
from media_converter.ui.main_window import MainWindow
from media_converter.ui.runtime_bridge import RuntimeBridge
from media_converter.ui.theme import apply_theme

pytestmark = pytest.mark.gui


class SimulatedGUIProvider:
    def __init__(self):
        self.calls = 0
        self.gate = threading.Event()
        self.propose = False

    async def respond(self, items, tools, on_delta, **kwargs):
        self.calls += 1
        on_delta("模拟流式文字")
        while not self.gate.is_set():
            await asyncio.sleep(0.01)
        text = "模拟回答，未访问在线供应商。"
        if self.propose:
            snapshot = json.loads(items[1]["content"].split("：", 1)[1])
            source_id = snapshot["references"][0]["source_id"]
            text += (
                "\n```settings_proposal\n"
                + json.dumps(
                    {
                        "patch": {"quality_value": 25},
                        "reason": "模拟建议，验证确认流程",
                        "source_ids": [source_id],
                    }
                )
                + "\n```"
            )
        return ModelResponse(
            text,
            (
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                },
            ),
            (),
            {"input_tokens": 20, "output_tokens": 10},
            "simulated-gui",
        )


@pytest.fixture
def agent_window(qtbot, qapp, tmp_path):
    apply_theme(qapp)
    paths = AppPaths.from_argument(tmp_path / "data").ensure()
    store = LocalStore(paths.data_dir / "state.sqlite3")
    window = MainWindow(paths)
    bridge = RuntimeBridge(window)
    conversion = ConversionController(window, store, bridge)
    window.controller = conversion
    provider = SimulatedGUIProvider()
    agent = AgentController(window, store, bridge, conversion, adapter=provider)
    window.agent_controller = agent
    qtbot.addWidget(window)
    window.show()
    window.agent_dock.show()
    qtbot.waitUntil(lambda: conversion.ready and agent.current_id is not None, timeout=20000)
    try:
        yield window, conversion, agent, provider
    finally:
        provider.gate.set()
        window.close()
        bridge.close()
        store.close()


def test_floating_hiding_does_not_resubmit_or_cancel_and_history_is_shared(agent_window, qtbot):
    window, conversion, agent, provider = agent_window
    panel = agent.panel
    panel.input.setPlainText("测试侧栏")
    qtbot.mouseClick(panel.send_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: provider.calls == 1, timeout=15000)
    turn_id = agent.active_turns[agent.current_id]
    widget = window.agent_dock.widget()
    qtbot.mouseClick(window.float_button, Qt.MouseButton.LeftButton)
    assert window.agent_dock.isFloating()
    window.agent_dock.close()
    assert agent.service.chats.turn(turn_id).state == "RUNNING" and provider.calls == 1
    window.agent_dock.show()
    window._toggle_floating()
    assert window.agent_dock.widget() is widget and agent.panel is panel
    provider.gate.set()
    qtbot.waitUntil(lambda: agent.service.chats.turn(turn_id).state == "SUCCEEDED", timeout=10000)
    qtbot.waitUntil(lambda: "模拟回答" in panel.messages.toPlainText(), timeout=10000)
    assert provider.calls == 1 and conversion.jobs.processor.active_count == 0
    folder = application_root() / "artifacts/agent-acceptance"
    folder.mkdir(parents=True, exist_ok=True)
    assert window.grab().save(str(folder / "agent-completed.png"))


def test_explicit_stop_is_persisted_and_retry_creates_new_turn(agent_window, qtbot):
    window, _, agent, provider = agent_window
    agent.send("停止测试")
    qtbot.waitUntil(lambda: provider.calls == 1, timeout=15000)
    old = agent.active_turns[agent.current_id]
    qtbot.mouseClick(agent.panel.stop_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: agent.service.chats.turn(old).state == "CANCELLED", timeout=10000)
    provider.gate.set()
    qtbot.mouseClick(agent.panel.retry_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: provider.calls == 2, timeout=10000)
    qtbot.waitUntil(
        lambda: (
            len([m for m in agent.service.chats.messages(agent.current_id) if m.role == "user"])
            == 2
        )
    )
    ids = {m.turn_id for m in agent.service.chats.messages(agent.current_id) if m.role == "user"}
    assert len(ids) == 2 and old in ids
