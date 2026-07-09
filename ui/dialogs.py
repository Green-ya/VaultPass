from PySide6.QtWidgets import *
from PySide6.QtCore import Qt
from config_manager import ConfigManager


class ConfigDialog(QDialog):
    """Диалог настроек подключения к Vault"""
    
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
        
        self.mount_edit = QLineEdit()
        self.mount_edit.setPlaceholderText("secret")
        self.mount_edit.setText("secret")
        form.addRow("Mount Point:", self.mount_edit)
        
        layout.addLayout(form)
        
        # Кнопки
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Загружаем сохранённые данные
        config = ConfigManager().load_config()
        if config:
            self.url_edit.setText(config.get("url", ""))
            self.token_edit.setText(config.get("token", ""))
            self.mount_edit.setText(config.get("mount_point", "secret"))
    
    def get_config(self):
        """Возвращает настройки из диалога"""
        return (
            self.url_edit.text().strip(),
            self.token_edit.text().strip(),
            self.mount_edit.text().strip()
        )


class SecretDialog(QDialog):
    """Диалог создания/редактирования секрета с несколькими парами ключ-значение"""
    
    def __init__(self, parent=None, existing_path="", existing_data=None):
        super().__init__(parent)
        self.setWindowTitle("Создать секрет" if not existing_path else "Редактировать секрет")
        self.setModal(True)
        self.resize(600, 400)
        
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
        label = QLabel("Пары ключ-значение:")
        layout.addWidget(label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Ключ", "Значение"])
        self.table.horizontalHeader().setStretchLastSection(True)
        
        # Заполняем данными если есть
        if existing_data:
            for key, value in existing_data.items():
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(key))
                self.table.setItem(row, 1, QTableWidgetItem(str(value)))
        else:
            # Добавляем две пустые строки для начала
            self.add_empty_row()
            self.add_empty_row()
        
        layout.addWidget(self.table)
        
        # Кнопки управления таблицей
        btn_layout = QHBoxLayout()
        
        add_row_btn = QPushButton("➕ Добавить строку")
        add_row_btn.clicked.connect(self.add_empty_row)
        btn_layout.addWidget(add_row_btn)
        
        remove_row_btn = QPushButton("➖ Удалить последнюю")
        remove_row_btn.clicked.connect(self.remove_last_row)
        btn_layout.addWidget(remove_row_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Кнопки OK/Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def add_empty_row(self):
        """Добавляет пустую строку в таблицу"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.table.setItem(row, 1, QTableWidgetItem(""))
        
        # Устанавливаем фокус на новую строку
        self.table.setCurrentCell(row, 0)
    
    def remove_last_row(self):
        """Удаляет последнюю строку, если она пустая и не единственная"""
        if self.table.rowCount() <= 1:
            QMessageBox.information(self, "Информация", "Должна быть хотя бы одна строка")
            return
        
        last_row = self.table.rowCount() - 1
        key_item = self.table.item(last_row, 0)
        value_item = self.table.item(last_row, 1)
        
        # Проверяем, пустая ли строка
        key_empty = not key_item or not key_item.text().strip()
        value_empty = not value_item or not value_item.text().strip()
        
        if not key_empty or not value_empty:
            reply = QMessageBox.question(
                self,
                "Удалить строку?",
                "Строка не пустая. Удалить её?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self.table.removeRow(last_row)
    
    def get_secret(self):
        """Возвращает путь и словарь с данными"""
        path = self.path_edit.text().strip()
        
        data = {}
        for row in range(self.table.rowCount()):
            key_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            
            if key_item and value_item:
                key = key_item.text().strip()
                value = value_item.text().strip()
                if key:  # Добавляем только если ключ не пустой
                    data[key] = value
        
        return path, data