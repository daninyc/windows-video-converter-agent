from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
)


class LossConfirmationDialog(QDialog):
    def __init__(self, plans, parent=None):
        super().__init__(parent)
        self.plans = tuple(plans)
        self.setWindowTitle("确认本次轨道丢失")
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("以下轨道不会出现在转换结果中，请逐项确认。"))
        self.details = QTextBrowser()
        self.details.setPlainText(
            "\n\n".join(
                f"{plan.source_path.name}\n"
                + "\n".join(
                    f"轨道 #{loss.stream_index} · {loss.kind}：{loss.reason}"
                    for loss in plan.loss_items
                )
                for plan in self.plans
                if plan.loss_items
            )
        )
        layout.addWidget(self.details)
        self.consent_checkbox = QCheckBox("我已了解以上轨道将不会保留")
        layout.addWidget(self.consent_checkbox)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.confirm_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.confirm_button.setText("确认本次丢失")
        self.confirm_button.setEnabled(False)
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        self.consent_checkbox.toggled.connect(self.confirm_button.setEnabled)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def confirmed_plans(self):
        if self.result() != QDialog.DialogCode.Accepted or not self.consent_checkbox.isChecked():
            return None
        return tuple(
            plan.confirm(plan.plan_hash) if plan.loss_items else plan for plan in self.plans
        )


def confirm_losses(plans, parent=None):
    if not any(plan.loss_items for plan in plans):
        return tuple(plans)
    dialog = LossConfirmationDialog(plans, parent)
    dialog.exec()
    return dialog.confirmed_plans()
