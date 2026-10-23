import pytest
from PySide6.QtCore import QPoint, Qt

from media_converter.ui.loss_confirmation import LossConfirmationDialog
from tests.unit.test_conversion_planner import make_plan

pytestmark = pytest.mark.gui


def test_explicit_consent_and_cancel_do_not_approve(qtbot, fixture_root, tmp_path):
    plan = make_plan(fixture_root, tmp_path, "mp4")
    dialog = LossConfirmationDialog([plan])
    qtbot.addWidget(dialog)
    assert not dialog.confirm_button.isEnabled() and dialog.confirmed_plans() is None
    assert "#3" in dialog.details.toPlainText() and "#4" in dialog.details.toPlainText()
    dialog.reject()
    assert dialog.confirmed_plans() is None
    dialog.show()
    qtbot.mouseClick(
        dialog.consent_checkbox,
        Qt.MouseButton.LeftButton,
        pos=QPoint(10, dialog.consent_checkbox.height() // 2),
    )
    qtbot.mouseClick(dialog.confirm_button, Qt.MouseButton.LeftButton)
    assert dialog.confirmed_plans()[0].consent_satisfied
