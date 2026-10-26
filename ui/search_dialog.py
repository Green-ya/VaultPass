from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from vault_client import VaultClientError


class SearchDialog(QDialog):
    """Глобальный поиск по путям, ключам и значениям секретов Vault."""

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.setWindowTitle("Поиск по Vault")
        self.setModal(True)
        self.resize(800, 500)

        layout = QVBoxLayout(self)

        top_layout = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Что искать? Например, production/db")
        self.query_edit.returnPressed.connect(self.run_search)
        top_layout.addWidget(self.query_edit, 1)

        self.search_btn = QPushButton("🔍 Найти")
        self.search_btn.clicked.connect(self.run_search)
        top_layout.addWidget(self.search_btn)
        layout.addLayout(top_layout)

        options_layout = QHBoxLayout()
        self.search_values_cb = QCheckBox("Искать в ключах и значениях (медленнее)")
        options_layout.addWidget(self.search_values_cb)

        self.case_sensitive_cb = QCheckBox("Учитывать регистр")
        options_layout.addWidget(self.case_sensitive_cb)
        options_layout.addStretch()

        self.status_label = QLabel("Введите запрос и нажмите «Найти»")
        options_layout.addWidget(self.status_label)
        layout.addLayout(options_layout)

        self.results = QTableWidget()
        self.results.setColumnCount(3)
        self.results.setHorizontalHeaderLabels(["Путь", "Ключ", "Значение"])
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results.itemDoubleClicked.connect(lambda _item: self.open_selected())
        self.results.setContextMenuPolicy(Qt.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.results)

        buttons = QDialogButtonBox()
        self.open_btn = buttons.addButton("Открыть секрет", QDialogButtonBox.ActionRole)
        self.open_btn.clicked.connect(self.open_selected)
        self.copy_btn = buttons.addButton(
            "Копировать значение", QDialogButtonBox.ActionRole
        )
        self.copy_btn.clicked.connect(self.copy_selected_value)
        buttons.addButton(QDialogButtonBox.Close).clicked.connect(self.reject)
        layout.addWidget(buttons)

        self._seen = set()
        self._found = 0

    # ------------------------------------------------------------------
    # Поиск
    # ------------------------------------------------------------------
    def run_search(self):
        query = self.query_edit.text().strip()
        if not query:
            return
        if not self.case_sensitive_cb.isChecked():
            query = query.lower()

        self.results.setRowCount(0)
        self._seen.clear()
        self._found = 0

        progress = QProgressDialog(
            "Сканируем Vault…", "Отмена", 0, 0, self
        )
        progress.setWindowTitle("Поиск")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QApplication.setOverrideCursor(Qt.WaitCursor)

        scanned = 0
        cancelled = False
        try:
            for path in self.client.iter_all_secrets():
                if progress.wasCanceled():
                    cancelled = True
                    break

                scanned += 1
                if scanned % 10 == 0:
                    progress.setLabelText(
                        f"Проверено секретов: {scanned}\n{path}"
                    )
                    QApplication.processEvents()
                    if progress.wasCanceled():
                        cancelled = True
                        break

                self._match_path(path, query)
                if self.search_values_cb.isChecked():
                    self._match_values(path, query)
        except VaultClientError as e:
            QMessageBox.warning(self, "Ошибка поиска", str(e))
        except Exception as e:  # сетевые ошибки и неожиданные ответы Vault
            QMessageBox.warning(self, "Ошибка поиска", f"Поиск прерван: {e}")
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()

        if cancelled:
            self.status_label.setText(
                f"Поиск отменён. Проверено: {scanned}, найдено: {self._found}"
            )
        else:
            self.status_label.setText(
                f"Проверено секретов: {scanned}, найдено: {self._found}"
            )
        self.results.resizeColumnsToContents()
        self.results.horizontalHeader().setStretchLastSection(True)

    def _match_path(self, path: str, query: str):
        haystack = path if self.case_sensitive_cb.isChecked() else path.lower()
        if query in haystack:
            self._add_result(path, "", "")

    def _match_values(self, path: str, query: str):
        try:
            data = self.client.read_secret(path)
        except VaultClientError:
            return

        case_sensitive = self.case_sensitive_cb.isChecked()
        for key, value in data.items():
            value_str = str(value)
            key_cmp = key if case_sensitive else key.lower()
            value_cmp = value_str if case_sensitive else value_str.lower()
            if query in key_cmp or query in value_cmp:
                self._add_result(path, key, value_str)

    def _add_result(self, path: str, key: str, value: str):
        dedup_key = (path, key)
        if dedup_key in self._seen:
            return
        self._seen.add(dedup_key)
        self._found += 1

        row = self.results.rowCount()
        self.results.insertRow(row)

        path_item = QTableWidgetItem(path)
        path_item.setData(Qt.UserRole, path)
        self.results.setItem(row, 0, path_item)

        self.results.setItem(row, 1, QTableWidgetItem(key))

        # Фиксированная маска: не раскрываем длину значения.
        masked = "•" * 12 if value else ""
        value_item = QTableWidgetItem(masked)
        value_item.setData(Qt.UserRole + 1, value)
        self.results.setItem(row, 2, value_item)

    # ------------------------------------------------------------------
    # Действия с результатами
    # ------------------------------------------------------------------
    def _current_path(self):
        row = self.results.currentRow()
        if row < 0:
            return None
        item = self.results.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def open_selected(self):
        path = self._current_path()
        if not path:
            return
        parent = self.parent()
        if parent and hasattr(parent, "open_secret"):
            parent.open_secret(path)
            self.accept()

    def copy_selected_value(self):
        row = self.results.currentRow()
        if row < 0:
            return
        item = self.results.item(row, 2)
        value = item.data(Qt.UserRole + 1) if item else None
        if value:
            parent = self.parent()
            if parent and hasattr(parent, "copy_to_clipboard"):
                parent.copy_to_clipboard(str(value))
            else:
                QApplication.clipboard().setText(str(value))
            self.status_label.setText("📋 Значение скопировано в буфер обмена")

    def _show_context_menu(self, pos):
        item = self.results.itemAt(pos)
        if not item:
            return
        self.results.setCurrentCell(item.row(), item.column())
        menu = QMenu(self)
        open_action = menu.addAction("Открыть секрет")
        open_action.triggered.connect(self.open_selected)
        copy_action = menu.addAction("Копировать значение")
        copy_action.triggered.connect(self.copy_selected_value)
        menu.exec(self.results.viewport().mapToGlobal(pos))
