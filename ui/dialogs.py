import secrets
import string

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from config_manager import ConfigManager

PASSWORD_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/"


def generate_password(
    length: int = 24,
    use_upper: bool = True,
    use_lower: bool = True,
    use_digits: bool = True,
    use_symbols: bool = True,
) -> str:
    """Генерирует криптостойкий пароль из выбранных наборов символов."""
    pools = []
    if use_upper:
        pools.append(string.ascii_uppercase)
    if use_lower:
        pools.append(string.ascii_lowercase)
    if use_digits:
        pools.append(string.digits)
    if use_symbols:
        pools.append(PASSWORD_SYMBOLS)

    if not pools:
        raise ValueError("Выберите хотя бы один набор символов")

    length = max(int(length), len(pools))
    alphabet = "".join(pools)

    # Гарантируем хотя бы один символ из каждого выбранного набора
    password = [secrets.choice(pool) for pool in pools]
    password.extend(secrets.choice(alphabet) for _ in range(length - len(password)))
    secrets.SystemRandom().shuffle(password)
    return "".join(password)


class ConfigDialog(QDialog):
    """Диалог настроек подключения к Vault."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки Vault")
        self.setModal(True)
        self.resize(500, 200)

        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://vault.example.com:8200")
        form.addRow("URL Vault:", self.url_edit)

        self.token_edit = QLineEdit()
        self.token_edit.setPlaceholderText("hvs.xxxxxxxxxxxx")
        self.token_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Токен:", self.token_edit)

        self.show_token_cb = QCheckBox("Показать токен")
        self.show_token_cb.toggled.connect(self._toggle_token_visibility)
        form.addRow("", self.show_token_cb)

        self.mount_edit = QLineEdit()
        self.mount_edit.setPlaceholderText("secret")
        self.mount_edit.setText("secret")
        form.addRow("Mount Point:", self.mount_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Загружаем сохранённые данные
        config = ConfigManager().load_config()
        if config:
            self.url_edit.setText(config.get("url", ""))
            self.token_edit.setText(config.get("token", ""))
            self.mount_edit.setText(config.get("mount_point", "secret"))

    def _toggle_token_visibility(self, visible: bool):
        self.token_edit.setEchoMode(
            QLineEdit.Normal if visible else QLineEdit.Password
        )

    def accept(self):
        url, token, mount = self.get_config()
        if not url:
            QMessageBox.warning(self, "Ошибка", "Укажите URL Vault")
            return
        if not token:
            QMessageBox.warning(self, "Ошибка", "Укажите токен доступа")
            return
        if not mount:
            self.mount_edit.setText("secret")
        super().accept()

    def get_config(self):
        """Возвращает настройки из диалога."""
        return (
            self.url_edit.text().strip().rstrip("/"),
            self.token_edit.text().strip(),
            self.mount_edit.text().strip().strip("/") or "secret",
        )


class SecretDialog(QDialog):
    """Диалог создания/редактирования секрета с несколькими парами ключ-значение."""

    def __init__(self, parent=None, existing_path="", existing_data=None):
        super().__init__(parent)
        self.setWindowTitle(
            "Создать секрет" if not existing_path else "Редактировать секрет"
        )
        self.setModal(True)
        self.resize(650, 480)

        layout = QVBoxLayout(self)

        # Путь к секрету
        form = QFormLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("myapp/production")
        if existing_path:
            self.path_edit.setText(existing_path)
            self.path_edit.setEnabled(False)  # Не даём менять путь при редактировании
        form.addRow("Путь:", self.path_edit)
        layout.addLayout(form)

        # Таблица для ключей-значений
        layout.addWidget(QLabel("Пары ключ-значение:"))
        self.table = self._create_table()
        layout.addWidget(self.table)

        # Кнопки управления таблицей
        btn_layout = QHBoxLayout()

        add_row_btn = QPushButton("➕ Добавить строку")
        add_row_btn.clicked.connect(self.add_empty_row)
        btn_layout.addWidget(add_row_btn)

        remove_row_btn = QPushButton("➖ Удалить строку")
        remove_row_btn.clicked.connect(self.remove_current_row)
        btn_layout.addWidget(remove_row_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Генератор паролей
        generator_box = QGroupBox("Генератор паролей")
        generator_layout = QVBoxLayout(generator_box)

        options_layout = QHBoxLayout()
        options_layout.addWidget(QLabel("Длина:"))
        self.length_spin = QSpinBox()
        self.length_spin.setRange(8, 128)
        self.length_spin.setValue(24)
        options_layout.addWidget(self.length_spin)

        self.upper_cb = QCheckBox("A-Z")
        self.upper_cb.setChecked(True)
        options_layout.addWidget(self.upper_cb)

        self.lower_cb = QCheckBox("a-z")
        self.lower_cb.setChecked(True)
        options_layout.addWidget(self.lower_cb)

        self.digits_cb = QCheckBox("0-9")
        self.digits_cb.setChecked(True)
        options_layout.addWidget(self.digits_cb)

        self.symbols_cb = QCheckBox("Символы")
        self.symbols_cb.setChecked(True)
        options_layout.addWidget(self.symbols_cb)

        options_layout.addStretch()

        generate_btn = QPushButton("🎲 Сгенерировать")
        generate_btn.clicked.connect(self.generate_into_current_row)
        options_layout.addWidget(generate_btn)

        generator_layout.addLayout(options_layout)
        layout.addWidget(generator_box)

        # Заполняем данными если есть
        if existing_data:
            for key, value in existing_data.items():
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(str(key)))
                self.table.setItem(row, 1, QTableWidgetItem(str(value)))
        else:
            # Добавляем две пустые строки для начала
            self.add_empty_row()
            self.add_empty_row()

        # Кнопки OK/Cancel
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create_table(self) -> QTableWidget:
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Ключ", "Значение"])
        table.horizontalHeader().setStretchLastSection(True)
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_context_menu)
        return table

    def _show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        row = item.row() if item else self.table.currentRow()
        menu = QMenu(self)

        copy_action = menu.addAction("📋 Скопировать значение")
        copy_action.triggered.connect(lambda: self._copy_row_value(row))
        menu.addSeparator()
        generate_action = menu.addAction("🎲 Сгенерировать пароль")
        generate_action.triggered.connect(lambda: self.generate_into_row(row))
        menu.addSeparator()
        remove_action = menu.addAction("➖ Удалить строку")
        remove_action.triggered.connect(lambda: self._remove_row(row))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_row_value(self, row):
        item = self.table.item(row, 1)
        if item and item.text():
            QApplication.clipboard().setText(item.text())

    def add_empty_row(self):
        """Добавляет пустую строку в таблицу."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.setCurrentCell(row, 0)

    def remove_current_row(self):
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        self._remove_row(row)

    def _remove_row(self, row):
        if row < 0:
            return
        if self.table.rowCount() <= 1:
            QMessageBox.information(
                self, "Информация", "Должна быть хотя бы одна строка"
            )
            return

        key_item = self.table.item(row, 0)
        value_item = self.table.item(row, 1)
        key_empty = not key_item or not key_item.text().strip()
        value_empty = not value_item or not value_item.text().strip()

        if not key_empty or not value_empty:
            reply = QMessageBox.question(
                self,
                "Удалить строку?",
                "Строка не пустая. Удалить её?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        self.table.removeRow(row)

    def generate_into_current_row(self):
        row = self.table.currentRow()
        if row < 0:
            row = self.table.rowCount() - 1
        self.generate_into_row(row)

    def generate_into_row(self, row):
        if row < 0:
            self.add_empty_row()
            row = self.table.rowCount() - 1

        try:
            password = generate_password(
                length=self.length_spin.value(),
                use_upper=self.upper_cb.isChecked(),
                use_lower=self.lower_cb.isChecked(),
                use_digits=self.digits_cb.isChecked(),
                use_symbols=self.symbols_cb.isChecked(),
            )
        except ValueError as e:
            QMessageBox.warning(self, "Ошибка", str(e))
            return

        item = self.table.item(row, 1)
        if item is None:
            item = QTableWidgetItem()
            self.table.setItem(row, 1, item)
        item.setText(password)
        self.table.setCurrentCell(row, 1)

    def accept(self):
        path, data = self.get_secret()
        if not path:
            QMessageBox.warning(self, "Ошибка", "Укажите путь к секрету")
            return
        if not data:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Добавьте хотя бы одну пару ключ-значение",
            )
            return
        super().accept()

    def get_secret(self):
        """Возвращает нормализованный путь и словарь с данными."""
        path = self.path_edit.text().strip().strip("/")

        data = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)

            if key_item and value_item:
                key = key_item.text().strip()
                value = value_item.text()
                if key:  # Добавляем только если ключ не пустой
                    data[key] = value

        return path, data


class DeleteSecretDialog(QDialog):
    """Подтверждение удаления секрета вводом его имени."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.secret_name = path.rstrip("/").rsplit("/", 1)[-1] or path

        self.setWindowTitle("Удаление секрета")
        self.setModal(True)
        self.resize(520, 250)

        layout = QVBoxLayout(self)

        warning = QLabel(
            "Удалить секрет?\n\n"
            f"{path}\n\n"
            "Будут удалены все версии секрета. Это действие необратимо.\n\n"
            f"Для подтверждения введите имя секрета: {self.secret_name}"
        )
        warning.setTextFormat(Qt.PlainText)
        warning.setWordWrap(True)
        layout.addWidget(warning)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(self.secret_name)
        self.name_edit.setClearButtonEnabled(True)
        form.addRow("Имя секрета:", self.name_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.delete_btn = buttons.button(QDialogButtonBox.Ok)
        self.delete_btn.setText("Удалить")
        self.delete_btn.setEnabled(False)
        self.delete_btn.setStyleSheet(
            """
            QPushButton {
                background: #c62828;
                color: white;
                padding: 6px 14px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:disabled { background: #e0a0a0; }
            QPushButton:hover:enabled { background: #9f1f1f; }
            """
        )

        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.name_edit.textChanged.connect(self._update_delete_button)
        self.name_edit.returnPressed.connect(self.accept)
        layout.addWidget(buttons)

    def _update_delete_button(self, text):
        self.delete_btn.setEnabled(text.strip() == self.secret_name)

    def accept(self):
        if self.name_edit.text().strip() != self.secret_name:
            return
        super().accept()
