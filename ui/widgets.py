"""Небольшие переиспользуемые виджеты."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTableWidget


class CopyableTable(QTableWidget):
    """``QTableWidget`` с сигналом ``copy_requested(row)`` по Ctrl+C.

    Логика копирования (реальное значение, политика автоочистки буфера)
    остаётся на стороне владельца таблицы.
    """

    copy_requested = Signal(int)

    def keyPressEvent(self, event):  # pylint: disable=invalid-name
        if event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
            row = self.currentRow()
            if row >= 0:
                self.copy_requested.emit(row)
                event.accept()
                return
        super().keyPressEvent(event)


class ConfirmOnCtrlShiftEnter:
    """Миксин для диалогов: Ctrl+Shift+Enter подтверждает ввод."""

    # Диалог-наследник предоставляет accept() и keyPressEvent().
    # pylint: disable=no-member
    def keyPressEvent(self, event):
        ctrl_shift = (
            event.modifiers() & Qt.ControlModifier
            and event.modifiers() & Qt.ShiftModifier
        )
        if ctrl_shift and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)
