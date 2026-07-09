import sys
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QIcon, QAction, QFont

# Меняем импорты с src. на прямые
from vault_client import VaultClient
from config_manager import ConfigManager
from ui.dialogs import ConfigDialog, SecretDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.client = None
        self.current_path = ""
        
        self.setWindowTitle("VaultPass - Менеджер паролей")
        self.setGeometry(100, 100, 1100, 750)
        
        # Устанавливаем иконку приложения (если есть)
        # self.setWindowIcon(QIcon("resources/icon.png"))
        
        self._create_menu()
        self._create_widgets()
        self._load_config()
    
    def _create_menu(self):
        """Создаём меню"""
        menubar = self.menuBar()
        
        file_menu = menubar.addMenu("Файл")
        connect_action = QAction("Подключиться к Vault", self)
        connect_action.triggered.connect(self.show_config_dialog)
        file_menu.addAction(connect_action)
        
        file_menu.addSeparator()
        exit_action = QAction("Выход", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        tools_menu = menubar.addMenu("Инструменты")
        refresh_action = QAction("Обновить", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh)
        tools_menu.addAction(refresh_action)
    

    def refresh(self):
        """Обновляем дерево папок"""
        if not self.client:
            QMessageBox.warning(self, "Ошибка", "Сначала подключитесь к Vault")
            return
        
        # Очищаем дерево (если оно есть)
        if hasattr(self, 'tree') and self.tree:
            self.tree.clear()
            root = QTreeWidgetItem(self.tree)
            root.setText(0, "📁 /")
            root.setData(0, Qt.UserRole, "")
            self._populate_tree(root, "")
            root.setExpanded(True)
        else:
            # Если дерева нет, просто обновляем текущую вкладку
            current_tab = self.tab_widget.currentWidget()
            if current_tab:
                # Ищем таблицу во вкладке
                table = current_tab.findChild(QTableWidget)
                if table:
                    path = table.property("vault_path") or ""
                    self.load_tab_content(table, path)

    def _create_widgets(self):
        """Создаём виджеты"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # --- Панель с кнопками ---
        top_panel = QWidget()
        top_panel.setFixedHeight(50)
        top_panel.setStyleSheet("""
            QWidget {
                background-color: #f0f0f0;
                border-bottom: 1px solid #ccc;
            }
        """)
        
        panel_layout = QHBoxLayout(top_panel)
        panel_layout.setContentsMargins(10, 5, 10, 5)
        
        self.btn_connect = QPushButton("🔑 Подключиться")
        self.btn_connect.clicked.connect(self.show_config_dialog)
        panel_layout.addWidget(self.btn_connect)
        
        self.btn_refresh = QPushButton("🔄 Обновить")
        self.btn_refresh.clicked.connect(self.refresh)
        panel_layout.addWidget(self.btn_refresh)
        
        self.btn_new = QPushButton("➕ Новый секрет")
        self.btn_new.clicked.connect(self.create_secret)
        panel_layout.addWidget(self.btn_new)
        
        self.btn_delete = QPushButton("🗑️ Удалить")
        self.btn_delete.clicked.connect(self.delete_secret)
        panel_layout.addWidget(self.btn_delete)
        
        panel_layout.addStretch()
        
        self.status_label = QLabel("Не подключено")
        panel_layout.addWidget(self.status_label)
        
        layout.addWidget(top_panel)
        
        # --- Разделитель: дерево + вкладки ---
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        
        # Левая панель с деревом
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Заголовок дерева
        tree_label = QLabel("📂 Структура Vault")
        tree_label.setStyleSheet("""
            QLabel {
                padding: 8px;
                background: #f8f9fa;
                border-bottom: 1px solid #dee2e6;
                font-weight: bold;
            }
        """)
        left_layout.addWidget(tree_label)
        
        # Само дерево
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.itemDoubleClicked.connect(self.on_tree_click)
        self.tree.itemExpanded.connect(self.on_tree_expanded) 
        self.tree.itemSelectionChanged.connect(self.on_tree_selection_changed)
        left_layout.addWidget(self.tree)
        
        splitter.addWidget(left_widget)
        
        # Правая панель с вкладками
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #ccc;
                background: white;
            }
            QTabBar::tab {
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #e0e0e0;
                border-bottom: 2px solid #0078d4;
            }
        """)
        
        splitter.addWidget(self.tab_widget)
        splitter.setSizes([300, 700])
        
        # Создаём первую вкладку
        self.add_tab("", "/")

    def on_tree_selection_changed(self):
        """При выделении элемента в дереве - переключаемся на вкладку или открываем новую"""
        current_item = self.tree.currentItem()
        if not current_item:
            return
        
        path = current_item.data(0, Qt.UserRole)
        if not path:
            return
        
        # Сначала пытаемся переключиться на существующую вкладку
        if self.switch_to_tab(path):
            return  # Уже открыта - просто переключились
        
        # Если вкладки нет - создаём новую
        if path.endswith('/'):
            display_name = path.rstrip('/').split('/')[-1]
            if not display_name:
                display_name = "/"
            self.add_tab(path, display_name)
        else:
            display_name = path.split('/')[-1]
            self.add_secret_tab(path, display_name)

    def switch_to_tab(self, path):
        """Переключает на существующую вкладку с указанным путём.
        Возвращает True если вкладка найдена и переключена.
        """
        for i in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(i)
            if not widget:
                continue
            
            # Ищем таблицу во вкладке
            table = widget.findChild(QTableWidget)
            if table:
                tab_path = table.property("vault_path")
                if tab_path == path:
                    self.tab_widget.setCurrentIndex(i)
                    return True
            
            # Если это вкладка секрета, проверяем по тексту
            tab_text = self.tab_widget.tabText(i)
            if "📄" in tab_text and path.split('/')[-1] in tab_text:
                # Дополнительная проверка через содержимое
                label = widget.findChild(QLabel)
                if label and path in label.text():
                    self.tab_widget.setCurrentIndex(i)
                    return True
        
        return False

    def on_tree_expanded(self, item):
        """Загружаем дочерние элементы при раскрытии папки"""
        # Проверяем, есть ли уже дочерние элементы
        if item.childCount() > 0:
            # Если есть - значит уже загружены
            return
        
        path = item.data(0, Qt.UserRole)
        if not path or not path.endswith('/'):
            return
        
        # Загружаем содержимое папки
        self._populate_tree(item, path)

    def add_tab(self, path, display_name):
        """Создаёт новую вкладку для каталога"""
        tab_widget = QWidget()
        tab_layout = QVBoxLayout(tab_widget)
        tab_layout.setContentsMargins(5, 5, 5, 5)
        
        # Создаём таблицу для этой вкладки
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Ключ/Путь", "Значение", "Тип"])
        table.horizontalHeader().setStretchLastSection(True)
        table.itemDoubleClicked.connect(self.on_table_double_click)
        
        # Сохраняем путь в таблицу
        table.setProperty("vault_path", path)
        
        tab_layout.addWidget(table)
        
        # Добавляем вкладку
        index = self.tab_widget.addTab(tab_widget, display_name)
        self.tab_widget.setCurrentIndex(index)
        
        # Загружаем содержимое
        self.load_tab_content(table, path)

    def close_tab(self, index):
        """Закрывает вкладку"""
        if self.tab_widget.count() > 1:
            self.tab_widget.removeTab(index)
        else:
            # Не даём закрыть последнюю вкладку
            QMessageBox.information(self, "Информация", "Нельзя закрыть последнюю вкладку")

    def load_tab_content(self, table, path):
        """Загружает содержимое каталога в таблицу"""
        if not self.client:
            return
        
        try:
            items = self.client.list_secrets(path)
            table.setRowCount(0)
            
            for item in items:
                row = table.rowCount()
                table.insertRow(row)
                
                # Определяем тип: папка или секрет
                is_folder = item.endswith('/')
                display_name = item[:-1] if is_folder else item
                
                # Сохраняем полный путь
                full_path = f"{path}{item}"
                
                # Колонка 0: Имя
                name_item = QTableWidgetItem(display_name)
                name_item.setData(Qt.UserRole, full_path)
                
                if is_folder:
                    font = name_item.font()
                    font.setBold(True)
                    name_item.setFont(font)
                    name_item.setForeground(Qt.blue)
                    table.setItem(row, 0, name_item)
                    table.setItem(row, 1, QTableWidgetItem("📂 Папка"))
                    table.setItem(row, 2, QTableWidgetItem("📁"))
                else:
                    table.setItem(row, 0, name_item)
                    table.setItem(row, 1, QTableWidgetItem("🔒 Нажмите для загрузки"))
                    table.setItem(row, 2, QTableWidgetItem("🔐"))
        
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить {path}: {e}")

    def on_table_double_click(self, item):
        """Обработка двойного клика по таблице во вкладке"""
        table = item.tableWidget()
        
        if not item or item.row() < 0:
            return
        
        name_item = table.item(item.row(), 0)
        if not name_item:
            return
        
        path = name_item.data(Qt.UserRole)
        if not path:
            return
        
        # Проверяем тип элемента (колонка 1)
        type_item = table.item(item.row(), 1)
        is_folder = type_item and ("Папка" in type_item.text() or "📂" in type_item.text())
        
        if is_folder:
            # Это папка
            folder_name = path.rstrip('/').split('/')[-1]
            if not folder_name:
                folder_name = "/"
            
            # Проверяем, не открыта ли уже эта вкладка
            if not self.switch_to_tab(path):
                self.add_tab(path, folder_name)
        else:
            # Это секрет
            secret_name = path.split('/')[-1]
            if not self.switch_to_tab(path):
                self.add_secret_tab(path, secret_name)

    def load_secret_value(self, table, path, row):
        """Загружает значение секрета в таблицу"""
        if not self.client:
            return
        
        try:
            data = self.client.read_secret(path)
            
            if not data:
                table.setItem(row, 1, QTableWidgetItem("(пусто)"))
                return
            
            # Показываем первый ключ-значение в текущей строке
            keys = list(data.keys())
            if keys:
                first_key = keys[0]
                first_value = str(data[first_key])
                
                # Обновляем текущую строку
                table.setItem(row, 0, QTableWidgetItem(first_key))
                table.setItem(row, 1, QTableWidgetItem(first_value))
                table.setItem(row, 2, QTableWidgetItem("🔑"))
                
                # Добавляем остальные ключи как новые строки
                for extra_key in keys[1:]:
                    new_row = table.rowCount()
                    table.insertRow(new_row)
                    table.setItem(new_row, 0, QTableWidgetItem(extra_key))
                    table.setItem(new_row, 1, QTableWidgetItem(str(data[extra_key])))
                    table.setItem(new_row, 2, QTableWidgetItem("🔑"))
        
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить секрет: {e}")

    def _load_config(self):
        """Загружаем сохранённый конфиг и подключаемся"""
        config = self.config_manager.load_config()
        if config:
            try:
                self.client = VaultClient(
                    url=config["url"],
                    token=config["token"],
                    mount_point=config.get("mount_point", "secret")
                )
                self.status_label.setText(f"✅ Подключено к {config['url']}")
                self.refresh()
            except Exception as e:
                self.status_label.setText(f"❌ Ошибка: {e}")
    
    def show_config_dialog(self):
        """Показываем диалог настройки"""
        dialog = ConfigDialog(self)
        if dialog.exec():
            url, token, mount = dialog.get_config()
            try:
                self.client = VaultClient(url, token, mount)
                self.config_manager.save_config(url, token, mount)
                self.status_label.setText(f"✅ Подключено к {url}")
                self.refresh()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def refresh(self):
        """Обновляем дерево папок"""
        if not self.client:
            QMessageBox.warning(self, "Ошибка", "Сначала подключитесь к Vault")
            return
        
        self.tree.clear()
        root = QTreeWidgetItem(self.tree)
        root.setText(0, "/")
        self._populate_tree(root, "")
        root.setExpanded(True)
    
    def _populate_tree(self, parent_item, path):
        """Рекурсивно заполняем дерево"""
        try:
            items = self.client.list_secrets(path)
            for item in items:
                child = QTreeWidgetItem(parent_item)
                
                # Если это папка (заканчивается на /)
                if item.endswith('/'):
                    display_name = item[:-1]  # Убираем слеш
                    child.setText(0, f"📁 {display_name}")
                    child.setData(0, Qt.UserRole, f"{path}{item}")
                    child.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    # Раскрываем папки с иконкой (но не загружаем содержимое сразу)
                    child.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
                else:
                    # Это секрет
                    child.setText(0, f"🔐 {item}")
                    child.setData(0, Qt.UserRole, f"{path}{item}")
                    child.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                    
                    # Попробуем прочитать секрет для предпросмотра
                    try:
                        data = self.client.read_secret(f"{path}{item}")
                        if data:
                            preview = list(data.values())[0] if data else ""
                            if len(str(preview)) > 30:
                                preview = str(preview)[:30] + "..."
                            child.setText(1, preview)
                    except:
                        pass  # Молча пропускаем ошибки при предпросмотре
        
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить {path}: {e}")
    
    def on_tree_click(self, item, _column=None):
        """При клике на элемент дерева"""
        path = item.data(0, Qt.UserRole)
        if not path:
            return
        
        if path.endswith('/'):  # Это папка
            # Открываем в новой вкладке
            display_name = item.text(0).replace("📁 ", "")
            if not display_name:
                display_name = "/"
            self.add_tab(path, display_name)
        else:  # Это секрет
            # Открываем в новой вкладке с содержимым секрета
            display_name = item.text(0).replace("🔐 ", "")
            self.add_secret_tab(path, display_name)
    
    def add_secret_tab(self, path, display_name):
        """Создаёт вкладку с содержимым секрета"""
        if not self.client:
            return
        
        try:
            data = self.client.read_secret(path)
            
            tab_widget = QWidget()
            tab_layout = QVBoxLayout(tab_widget)
            tab_layout.setContentsMargins(10, 10, 10, 10)
            
            # Информация о секрете
            info_label = QLabel(f"<b>Секрет:</b> {path}")
            info_label.setStyleSheet("padding: 5px; background: #f8f9fa; border-radius: 4px;")
            info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            info_label.setWordWrap(True)
            tab_layout.addWidget(info_label)
            
            # Кнопка копирования пути
            copy_path_btn = QPushButton("📋 Скопировать путь")
            copy_path_btn.clicked.connect(lambda: self.copy_to_clipboard(path))
            copy_path_btn.setStyleSheet("""
                QPushButton {
                    padding: 5px 15px;
                    background: #f0f0f0;
                    border: 1px solid #ccc;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #e0e0e0;
                }
            """)
            tab_layout.addWidget(copy_path_btn)
            
            # Таблица с ключами-значениями
            table = QTableWidget()
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Ключ", "Значение"])
            table.horizontalHeader().setStretchLastSection(True)
            table.setProperty("vault_path", path)  # <-- ДОБАВЛЯЕМ для поиска
            
            table.setRowCount(len(data))
            for i, (key, value) in enumerate(data.items()):
                table.setItem(i, 0, QTableWidgetItem(key))
                table.setItem(i, 1, QTableWidgetItem(str(value)))
            
            # Кнопка копирования всего секрета
            copy_btn = QPushButton("📋 Скопировать всё")
            copy_btn.clicked.connect(lambda: self.copy_secret_data(data))
            copy_btn.setStyleSheet("""
                QPushButton {
                    padding: 8px;
                    background: #0078d4;
                    color: white;
                    border: none;
                    border-radius: 4px;
                }
                QPushButton:hover {
                    background: #005a9e;
                }
            """)
            
            tab_layout.addWidget(copy_btn)
            tab_layout.addWidget(table)
            
            index = self.tab_widget.addTab(tab_widget, f"📄 {display_name}")
            self.tab_widget.setCurrentIndex(index)
            
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить секрет: {e}")

    def copy_to_clipboard(self, text):
        """Копирует текст в буфер обмена"""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.status_label.setText(f"📋 Скопировано: {text[:50]}...")

    def copy_secret_data(self, data):
        """Копирует все данные секрета в буфер обмена"""
        clipboard = QApplication.clipboard()
        text = "\n".join([f"{k}: {v}" for k, v in data.items()])
        clipboard.setText(text)
        self.status_label.setText("📋 Все данные скопированы")

    def _show_folder(self, path):
        """Показываем содержимое папки"""
        if not self.client:
            return
        
        try:
            items = self.client.list_secrets(path)
            self.table.setRowCount(0)
            for item in items:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(item))
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))
    
    def _show_secret(self, path):
        """Показываем содержимое секрета"""
        if not self.client:
            return
        
        try:
            data = self.client.read_secret(path)
            self.table.setRowCount(0)
            for key, value in data.items():
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(key))
                self.table.setItem(row, 1, QTableWidgetItem(str(value)))
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", str(e))
    
    def create_secret(self):
        """Создать новый секрет"""
        if not self.client:
            QMessageBox.warning(self, "Ошибка", "Сначала подключитесь")
            return
        
        dialog = SecretDialog(self)  # Теперь работает
        if dialog.exec():
            path, data = dialog.get_secret()
            if not path or not data:
                QMessageBox.warning(self, "Ошибка", "Путь и данные не могут быть пустыми")
                return
            
            try:
                # Проверяем, существует ли секрет
                existing = self.client.read_secret(path)
                if existing:
                    # Секрет существует - спрашиваем
                    reply = QMessageBox.question(
                        self, 
                        "Секрет уже существует",
                        f"Секрет '{path}' уже существует.\n\n"
                        "Хотите перезаписать его?",
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    if reply == QMessageBox.No:
                        self.status_label.setText("⏹️ Создание отменено")
                        return
                
                # Создаём или обновляем секрет
                self.client.create_secret(path, data)
                self.refresh()
                self.status_label.setText(f"✅ {'Обновлён' if existing else 'Создан'} секрет: {path}")
                
                # Открываем созданный секрет во вкладке
                secret_name = path.split('/')[-1]
                self.add_secret_tab(path, secret_name)
                
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
    
    def delete_secret(self):
        """Удалить выбранный секрет"""
        # Получаем текущую вкладку
        current_tab = self.tab_widget.currentWidget()
        if not current_tab:
            return
        
        # Ищем таблицу в текущей вкладке
        table = current_tab.findChild(QTableWidget)
        if not table:
            QMessageBox.warning(self, "Ошибка", "Нет активной таблицы")
            return
        
        # Получаем выбранную строку
        current_row = table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите секрет для удаления")
            return
        
        # Получаем путь из первой колонки
        path_item = table.item(current_row, 0)
        if not path_item:
            return
        
        # Проверяем, что это секрет (не папка)
        type_item = table.item(current_row, 2)
        if type_item and "Папка" in type_item.text():
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить папку через эту кнопку")
            return
        
        # Получаем полный путь
        full_path = path_item.data(Qt.UserRole)
        if not full_path:
            # Если путь не сохранён, пытаемся собрать из контекста
            tab_path = table.property("vault_path") or ""
            secret_name = path_item.text()
            full_path = f"{tab_path}{secret_name}"
        
        # Подтверждение удаления
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить секрет '{full_path}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                self.client.delete_secret(full_path)
                # Обновляем текущую вкладку
                self.load_tab_content(table, table.property("vault_path") or "")
                self.status_label.setText(f"🗑️ Удалён: {full_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def _create_tree_widget(self):
        """Создаёт виджет дерева (для левой панели)"""
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Каталоги")
        self.tree.setIconSize(QSize(20, 20))
        self.tree.itemDoubleClicked.connect(self.on_tree_click)
        
        # Иконки для дерева
        self.tree.setStyleSheet("""
            QTreeWidget::item {
                padding: 4px;
            }
            QTreeWidget::item:hover {
                background: #e8f0fe;
            }
            QTreeWidget::item:selected {
                background: #d2e3fc;
            }
        """)
        
        return self.tree