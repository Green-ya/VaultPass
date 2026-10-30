import html
import logging
import math
import os
import time

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config_manager import ConfigManager
from logging_setup import set_debug
from resource_utils import get_resource_path
from ui.dialogs import ConfigDialog, DeleteSecretDialog, SecretDialog
from ui.search_dialog import SearchDialog
from vault_client import VaultClient

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    CACHE_TTL = 120  # секунд
    CLIPBOARD_CLEAR_SECONDS = 30
    PREVIEW_LIMIT = 30  # сколько значений подгружать сразу в списке каталога
    MASK_CHARS = 12  # фиксированное число символов в маскированном значении

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        self.client = None
        self.debug_mode = False

        self._active_path = ""
        self._directory_path = ""
        self._secret_path = None
        self._secret_data = {}
        self._secret_cache = {}

        self._clipboard_value = None
        self._clipboard_deadline = None

        self.setWindowTitle("VaultPass - Менеджер паролей")
        self.setGeometry(100, 100, 1100, 750)

        self._eye_icon_hidden = self._build_eye_icon(crossed=False)
        self._eye_icon_visible = self._build_eye_icon(crossed=True)

        self._clipboard_timer = QTimer(self)
        # 250 мс, чтобы подпись не «перескакивала» через секунду из-за
        # погрешности таймера Qt и всегда показывала актуальный остаток.
        self._clipboard_timer.setInterval(250)
        self._clipboard_timer.timeout.connect(self._update_clipboard_countdown)

        # Автоскрытие уведомлений в статусной строке.
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._reset_status)

        # Периодическая очистка кэша расшифрованных секретов: TTL ограничивает
        # чтение, но не время жизни записи в памяти.
        self._cache_timer = QTimer(self)
        self._cache_timer.setInterval(self.CACHE_TTL * 1000)
        self._cache_timer.timeout.connect(self._purge_expired_cache)

        self._create_menu()
        self._create_widgets()
        self._load_config()

    # ------------------------------------------------------------------
    # Жизненный цикл окна
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        """При закрытии окна очищаем буфер обмена и секреты из памяти."""
        self._clear_clipboard()
        self._clipboard_timer.stop()
        self._status_timer.stop()
        self._cache_timer.stop()
        self._secret_cache.clear()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Уведомления — единая точка вывода в статусную строку
    # ------------------------------------------------------------------
    def _notify(self, text, timeout=5000):
        self.status_label.setText(text)
        self._status_timer.stop()
        if timeout and timeout > 0:
            self._status_timer.start(timeout)

    def info(self, text, timeout=5000):
        """Информационное сообщение в статусной строке."""
        self._notify(text, timeout)

    def warn(self, text, timeout=8000):
        """Предупреждение в статусной строке."""
        self._notify(text, timeout)

    def error(self, text, timeout=0):
        """Ошибка в статусной строке; держится до следующего сообщения."""
        self._notify(text, timeout)

    def _reset_status(self):
        self.status_label.setText("Готово")

    # ------------------------------------------------------------------
    # Обработка ошибок: в лог — детали, пользователю — понятный текст
    # ------------------------------------------------------------------
    def _report_error(self, message, exc=None, level=logging.ERROR):
        """Логирует технические детали и показывает пользователю понятный текст.

        ``exc`` передаётся в лог как traceback; секреты сюда не попадают.
        """
        logger.log(level, "%s", message, exc_info=exc)
        self.error(f"❌ {message}")

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------
    def debug_log(self, *args):
        logger.debug(" ".join(str(a) for a in args))

    def toggle_debug_mode(self, checked):
        self.debug_mode = checked
        set_debug(checked)
        if checked:
            self.info("🐛 Режим отладки включён")
        else:
            self._reset_status()

    def _build_eye_icon(self, crossed: bool) -> QIcon:
        """Рисуем иконку глаза; перечёркнутый — значение открыто."""
        size = 20
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        pen = QPen(QColor("#444444"))
        pen.setWidthF(1.6)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        eye_path = QPainterPath()
        eye_path.moveTo(2, 10)
        eye_path.cubicTo(5, 5, 15, 5, 18, 10)
        eye_path.cubicTo(15, 15, 5, 15, 2, 10)
        painter.drawPath(eye_path)

        painter.setBrush(QColor("#444444"))
        painter.drawEllipse(QPointF(10, 10), 2.3, 2.3)

        if crossed:
            painter.setPen(QPen(QColor("#c62828"), 1.8))
            painter.drawLine(3, 3, 17, 17)

        painter.end()
        return QIcon(pixmap)

    # ------------------------------------------------------------------
    # Кэш секретов
    # ------------------------------------------------------------------
    def _get_secret(self, path, force=False):
        """Читает секрет через кэш с TTL."""
        now = time.monotonic()
        cached = self._secret_cache.get(path)
        if cached and not force and now - cached[0] < self.CACHE_TTL:
            return cached[1]

        data = self.client.read_secret(path)
        self._secret_cache[path] = (now, data)
        return data

    def _purge_expired_cache(self):
        """Выбрасывает из памяти расшифрованные секреты старше TTL."""
        now = time.monotonic()
        expired = [
            path
            for path, (stamp, _data) in self._secret_cache.items()
            if now - stamp >= self.CACHE_TTL
        ]
        for path in expired:
            self._secret_cache.pop(path, None)
        if expired:
            logger.debug("Очищено из кэша секретов: %d", len(expired))

    def _invalidate_cache(self, path=None):
        if path is None:
            self._secret_cache.clear()
            return

        self._secret_cache.pop(path, None)
        prefix = path.rstrip("/") + "/"
        for cached_path in [p for p in self._secret_cache if p.startswith(prefix)]:
            self._secret_cache.pop(cached_path, None)

    # ------------------------------------------------------------------
    # Меню
    # ------------------------------------------------------------------
    def _create_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Файл")
        connect_action = QAction("Подключиться к Vault…", self)
        connect_action.setShortcut(QKeySequence("Ctrl+Shift+O"))
        connect_action.triggered.connect(self.show_config_dialog)
        file_menu.addAction(connect_action)

        self.disconnect_action = QAction("Отключиться", self)
        self.disconnect_action.setShortcut(QKeySequence("Ctrl+Shift+D"))
        self.disconnect_action.triggered.connect(self.disconnect_from_vault)
        file_menu.addAction(self.disconnect_action)

        file_menu.addSeparator()
        exit_action = QAction("Выход", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = menubar.addMenu("Правка")
        self.search_action = QAction("Поиск по Vault…", self)
        self.search_action.setShortcut(QKeySequence("Ctrl+F"))
        self.search_action.triggered.connect(self.show_search_dialog)
        edit_menu.addAction(self.search_action)

        self.refresh_action = QAction("Обновить", self)
        self.refresh_action.setShortcut("F5")
        self.refresh_action.triggered.connect(self.refresh)
        edit_menu.addAction(self.refresh_action)

        view_menu = menubar.addMenu("Вид")
        debug_action = QAction("Режим отладки", self)
        debug_action.setCheckable(True)
        debug_action.setChecked(self.debug_mode)
        debug_action.triggered.connect(self.toggle_debug_mode)
        view_menu.addAction(debug_action)

    # ------------------------------------------------------------------
    # Виджеты
    # ------------------------------------------------------------------
    def _create_widgets(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Панель с кнопками ---
        top_panel = QWidget()
        top_panel.setFixedHeight(50)
        top_panel.setStyleSheet(
            """
            QWidget {
                background-color: #f0f0f0;
                border-bottom: 1px solid #ccc;
            }
            """
        )

        panel_layout = QHBoxLayout(top_panel)
        panel_layout.setContentsMargins(10, 5, 10, 5)

        logo_path = get_resource_path("resources/vaultpass_logo.png")
        if os.path.exists(logo_path):
            logo_label = QLabel()
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(
                pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            panel_layout.addWidget(logo_label)

        self.btn_connect = QPushButton("🔑 Подключиться")
        self.btn_connect.clicked.connect(self.show_config_dialog)
        panel_layout.addWidget(self.btn_connect)

        self.btn_refresh = QPushButton("🔄 Обновить")
        self.btn_refresh.clicked.connect(self.refresh)
        panel_layout.addWidget(self.btn_refresh)

        self.btn_new = QPushButton("➕ Новый секрет")
        self.btn_new.clicked.connect(self.create_secret)
        panel_layout.addWidget(self.btn_new)

        self.btn_search = QPushButton("🔍 Поиск")
        self.btn_search.clicked.connect(self.show_search_dialog)
        panel_layout.addWidget(self.btn_search)

        self.btn_disconnect = QPushButton("🔌 Отключиться")
        self.btn_disconnect.clicked.connect(self.disconnect_from_vault)
        panel_layout.addWidget(self.btn_disconnect)

        panel_layout.addStretch()

        # Отдельная метка для состояния буфера обмена: раньше счётчик
        # автоочистки каждые 250 мс перезаписывал status_label и затирал
        # любые уведомления. Теперь статус и буфер не мешают друг другу.
        self.clipboard_label = QLabel("")
        self.clipboard_label.setStyleSheet("color: #666;")
        panel_layout.addWidget(self.clipboard_label)

        self.status_label = QLabel("Не подключено")
        panel_layout.addWidget(self.status_label)

        layout.addWidget(top_panel)

        # --- Разделитель: дерево + правая панель ---
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        tree_label = QLabel("📂 Структура Vault")
        tree_label.setStyleSheet(
            """
            QLabel {
                padding: 8px;
                background: #f8f9fa;
                border-bottom: 1px solid #dee2e6;
                font-weight: bold;
            }
            """
        )
        left_layout.addWidget(tree_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.itemExpanded.connect(self.on_tree_expanded)
        self.tree.currentItemChanged.connect(self.on_tree_current_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(
            self._show_tree_context_menu
        )
        self.tree.setStyleSheet(
            """
            QTreeWidget::item { padding: 4px; }
            QTreeWidget::item:hover { background: #e8f0fe; }
            QTreeWidget::item:selected { background: #d2e3fc; }
            """
        )
        left_layout.addWidget(self.tree)

        splitter.addWidget(left_widget)

        self.content_stack = QStackedWidget()
        self.empty_page = self._create_empty_page()
        self.directory_page = self._create_directory_page()
        self.secret_page = self._create_secret_page()
        self.content_stack.addWidget(self.empty_page)
        self.content_stack.addWidget(self.directory_page)
        self.content_stack.addWidget(self.secret_page)
        self.content_stack.setCurrentWidget(self.empty_page)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        right_layout.addWidget(self.content_stack, 1)

        actions_bar = QWidget()
        actions_bar.setObjectName("actionsBar")
        actions_bar.setStyleSheet(
            "#actionsBar { background: #f8f9fa; "
            "border-top: 1px solid #dee2e6; }"
        )
        actions_layout = QHBoxLayout(actions_bar)
        actions_layout.setContentsMargins(10, 6, 10, 6)

        self.delete_target_label = QLabel("Секрет не выбран")
        self.delete_target_label.setStyleSheet("color: #666;")
        actions_layout.addWidget(self.delete_target_label, 1)

        self.btn_delete = QPushButton("🗑️ Удалить")
        self.btn_delete.setObjectName("deleteButton")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setToolTip("Выберите секрет для удаления")
        self.btn_delete.clicked.connect(self.delete_secret)
        actions_layout.addWidget(self.btn_delete)

        right_layout.addWidget(actions_bar)

        splitter.addWidget(right_panel)
        splitter.setSizes([300, 700])

    def _create_empty_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("Выберите каталог или секрет в дереве слева")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #777; font-size: 14px;")
        layout.addWidget(label)
        return page

    def _create_directory_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        self.dir_path_label = QLabel("📂 /")
        self.dir_path_label.setStyleSheet(
            "padding: 6px; background: #f8f9fa; border-radius: 4px;"
        )
        self.dir_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.dir_path_label)

        self.dir_table = QTableWidget()
        self.dir_table.setColumnCount(4)
        self.dir_table.setHorizontalHeaderLabels(["Имя", "Значение", "Тип", ""])
        self._configure_table(self.dir_table)
        self.dir_table.itemDoubleClicked.connect(self.on_table_double_click)
        self.dir_table.itemSelectionChanged.connect(
            lambda: self.on_table_selection_changed(self.dir_table)
        )
        self.dir_table.cellClicked.connect(
            lambda row, col: self._on_table_cell_clicked(
                self.dir_table, row, col, eye_column=3
            )
        )
        self.dir_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.dir_table.customContextMenuRequested.connect(
            self._show_directory_context_menu
        )

        header = self.dir_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        self.dir_table.setColumnWidth(3, 34)

        layout.addWidget(self.dir_table)
        return page

    def _create_secret_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        header_layout = QHBoxLayout()

        self.secret_info_label = QLabel("<b>Секрет:</b> ")
        self.secret_info_label.setStyleSheet(
            "padding: 6px; background: #f8f9fa; border-radius: 4px;"
        )
        self.secret_info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.secret_info_label.setWordWrap(True)
        header_layout.addWidget(self.secret_info_label, 1)

        copy_path_btn = QPushButton("📋 Путь")
        copy_path_btn.setToolTip("Скопировать путь секрета")
        copy_path_btn.clicked.connect(
            lambda: self.copy_to_clipboard(self._secret_path or "")
        )
        header_layout.addWidget(copy_path_btn)

        edit_btn = QPushButton("✏️ Изменить")
        edit_btn.clicked.connect(
            lambda: self.edit_secret(self._secret_path)
        )
        header_layout.addWidget(edit_btn)

        layout.addLayout(header_layout)

        self.secret_table = QTableWidget()
        self.secret_table.setColumnCount(3)
        self.secret_table.setHorizontalHeaderLabels(["Ключ", "Значение", ""])
        self._configure_table(self.secret_table)
        self.secret_table.itemDoubleClicked.connect(self.on_table_double_click)
        self.secret_table.cellClicked.connect(
            lambda row, col: self._on_table_cell_clicked(
                self.secret_table, row, col, eye_column=2
            )
        )
        self.secret_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.secret_table.customContextMenuRequested.connect(
            self._show_secret_context_menu
        )

        header = self.secret_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.secret_table.setColumnWidth(2, 34)

        layout.addWidget(self.secret_table)

        copy_btn = QPushButton("📋 Скопировать всё")
        copy_btn.clicked.connect(
            lambda: self.copy_secret_data(self._secret_data)
        )
        copy_btn.setStyleSheet(
            """
            QPushButton {
                padding: 8px;
                background: #0078d4;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background: #005a9e; }
            """
        )
        layout.addWidget(copy_btn)
        return page

    @staticmethod
    def _configure_table(table: QTableWidget):
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)

    # ------------------------------------------------------------------
    # Подключение
    # ------------------------------------------------------------------
    def _load_config(self):
        config = self.config_manager.load_config()
        if not config:
            return

        try:
            self._connect_to_vault(
                config["url"],
                config["token"],
                config.get("mount_point", "secret"),
                save=False,
            )
        except Exception as e:
            self._report_error(f"Ошибка: {e}", e)

    def _connect_to_vault(self, url, token, mount_point, save=True):
        client = VaultClient(url, token, mount_point)
        self.client = client
        self._invalidate_cache()
        self._active_path = ""
        self._cache_timer.start()
        logger.info("Подключение к Vault установлено: %s", url)

        if save:
            self.config_manager.save_config(url, token, mount_point)

        self.info(f"✅ Подключено к {url}")
        self.refresh(silent=True)

    def show_config_dialog(self):
        dialog = ConfigDialog(self)
        if not dialog.exec():
            return

        url, token, mount = dialog.get_config()
        try:
            self._connect_to_vault(url, token, mount)
        except Exception as e:
            self._report_error(str(e), e)

    def disconnect_from_vault(self):
        """Отключается от Vault и вычищает секреты из памяти."""
        if not self.client:
            self.warn("Нет активного подключения")
            return

        self._clear_clipboard()
        self._invalidate_cache()
        self.client = None
        self._cache_timer.stop()
        self._active_path = ""
        self._directory_path = ""
        self._secret_path = None
        self._secret_data = {}

        self.tree.clear()
        self.content_stack.setCurrentWidget(self.empty_page)
        self.delete_target_label.setText("Секрет не выбран")
        self._update_delete_action()

        logger.info("Отключение от Vault: клиент и кэш очищены")
        self._status_timer.stop()
        self.status_label.setText("Не подключено")
        self.clipboard_label.setText("")

    # ------------------------------------------------------------------
    # Дерево
    # ------------------------------------------------------------------
    def refresh(self, silent=False):
        """Перестраивает дерево и обновляет активную правую панель."""
        if not self.client:
            if not silent:
                self.warn("Сначала подключитесь к Vault")
            return

        active_path = self._active_path
        expanded_paths = self._expanded_tree_paths()

        self._invalidate_cache()
        self.tree.clear()

        root = QTreeWidgetItem(self.tree)
        root.setText(0, "📁 /")
        root.setData(0, Qt.UserRole, "")
        root.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
        self._populate_tree(root, "", show_errors=not silent)
        root.setExpanded(True)
        self._restore_expanded_paths(expanded_paths)

        item = self._ensure_tree_item(active_path) if active_path else root
        if item is None:
            item = root

        # После clear() текущего элемента нет, поэтому setCurrentItem()
        # вызовет currentItemChanged и правую панель обновит сигнал.
        if self.tree.currentItem() is item:
            self._show_tree_item(item)
        else:
            self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

        if not silent:
            self.info("🔄 Обновлено")

    def _expanded_tree_paths(self):
        paths = set()

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                path = child.data(0, Qt.UserRole)
                if child.isExpanded() and path:
                    paths.add(path)
                walk(child)

        root = self.tree.topLevelItem(0)
        if root:
            walk(root)
        return paths

    def _ensure_tree_item(self, path):
        """Находит элемент дерева по пути, при необходимости раскрывая папки."""
        root = self.tree.topLevelItem(0)
        if root is None:
            return None

        is_folder = path == "" or path.endswith("/")
        segments = [segment for segment in path.split("/") if segment]
        if not segments:
            return root

        current = root
        current_path = ""
        for index, segment in enumerate(segments):
            is_last = index == len(segments) - 1
            next_path = f"{current_path}{segment}"
            if not is_last or is_folder:
                next_path += "/"

            if current.childCount() == 0:
                self._populate_tree(current, current_path, show_errors=False)

            current = self._find_tree_child(current, next_path)
            if current is None:
                return None
            current_path = next_path

        return current

    @staticmethod
    def _find_tree_child(parent, path):
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, Qt.UserRole) == path:
                return child
        return None

    def _restore_expanded_paths(self, paths):
        for path in sorted(paths, key=lambda p: p.count("/")):
            item = self._ensure_tree_item(path)
            if item:
                item.setExpanded(True)

    def _populate_tree(self, parent_item, path, show_errors=True):
        try:
            items = self.client.list_secrets(path)
        except Exception as e:
            if show_errors:
                self._report_error(f"Не удалось загрузить {path or '/'}: {e}", e)
            return

        for item in items:
            child = QTreeWidgetItem(parent_item)

            if item.endswith("/"):
                child.setText(0, f"📁 {item[:-1]}")
                child.setData(0, Qt.UserRole, f"{path}{item}")
                child.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                child.setChildIndicatorPolicy(QTreeWidgetItem.ShowIndicator)
            else:
                child.setText(0, f"🔐 {item}")
                child.setData(0, Qt.UserRole, f"{path}{item}")
                child.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))

    def on_tree_expanded(self, item):
        """Лениво загружаем дочерние элементы при раскрытии папки."""
        if item.childCount() > 0:
            return

        path = item.data(0, Qt.UserRole)
        if path is None or not path.endswith("/"):
            return

        self._populate_tree(item, path)

    def on_tree_current_changed(self, current, _previous):
        if current is None:
            return
        self._show_tree_item(current)

    def _show_tree_item(self, item):
        path = item.data(0, Qt.UserRole)
        if path is None:
            return

        self._active_path = path
        if path == "" or path.endswith("/"):
            self.show_directory(path)
        else:
            self.show_secret(path)

    def _build_tree_menu(self, path):
        """Собирает контекстное меню узла дерева (П2)."""
        is_dir = path == "" or path.endswith("/")
        menu = QMenu(self)

        if is_dir:
            new_action = menu.addAction("➕ Новый секрет здесь")
            new_action.triggered.connect(
                lambda _checked=False: self._create_secret(path)
            )
            open_action = menu.addAction("📂 Открыть")
            open_action.triggered.connect(
                lambda _checked=False: self._navigate_to(path)
            )
        else:
            open_action = menu.addAction("📂 Открыть")
            open_action.triggered.connect(
                lambda _checked=False: self._navigate_to(path)
            )
            rename_action = menu.addAction("✏️ Переименовать…")
            rename_action.triggered.connect(
                lambda _checked=False: self.rename_secret(path)
            )
            delete_action = menu.addAction("🗑️ Удалить…")
            delete_action.triggered.connect(
                lambda _checked=False: self.delete_secret_path(path)
            )

        menu.addSeparator()
        refresh_action = menu.addAction("🔄 Обновить")
        refresh_action.triggered.connect(lambda _checked=False: self.refresh())

        return menu

    def _show_tree_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return

        path = item.data(0, Qt.UserRole)
        if path is None:
            return

        menu = self._build_tree_menu(path)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Навигация
    # ------------------------------------------------------------------
    def open_directory(self, path):
        self._navigate_to(path)

    def open_secret(self, path):
        self._navigate_to(path)

    def _navigate_to(self, path):
        item = self._ensure_tree_item(path)
        if item is None:
            self._active_path = path
            if path == "" or path.endswith("/"):
                self.show_directory(path)
            else:
                self.show_secret(path)
            return

        if self.tree.currentItem() is item:
            self._show_tree_item(item)
        else:
            self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)

    # ------------------------------------------------------------------
    # Правая панель
    # ------------------------------------------------------------------
    def show_directory(self, path):
        self._active_path = path
        self._directory_path = path
        self.dir_path_label.setText(f"📂 {path or '/'}")
        self.content_stack.setCurrentWidget(self.directory_page)
        self.load_directory(path)
        self._update_delete_action()

    def show_secret(self, path):
        try:
            data = self._get_secret(path)
        except Exception as e:
            self._report_error(f"Не удалось загрузить секрет: {e}", e)
            return

        self._active_path = path
        self._secret_path = path
        self._secret_data = data
        self.secret_info_label.setText(
            f"<b>Секрет:</b> {html.escape(path)}"
        )
        self._fill_secret_table(self.secret_table, data)
        self.content_stack.setCurrentWidget(self.secret_page)
        self._update_delete_action()

    def load_directory(self, path):
        if not self.client:
            return

        try:
            items = self.client.list_secrets(path)
        except Exception as e:
            self._report_error(f"Не удалось загрузить {path or '/'}: {e}", e)
            return

        prefix = (path or "").rstrip("/")
        prefix = f"{prefix}/" if prefix else ""

        table = self.dir_table
        table.setUpdatesEnabled(False)
        table.setRowCount(0)
        table.clearSelection()

        for item in items:
            row = table.rowCount()
            table.insertRow(row)

            is_folder = item.endswith("/")
            display_name = item[:-1] if is_folder else item
            full_path = f"{prefix}{item}"

            name_item = QTableWidgetItem(
                f"{'📁' if is_folder else '🔐'} {display_name}"
            )
            name_item.setData(Qt.UserRole, full_path)
            if is_folder:
                name_item.setForeground(QColor(Qt.blue))
                table.setItem(row, 0, name_item)
                table.setItem(row, 1, QTableWidgetItem("📂 Папка"))
                table.setItem(row, 2, QTableWidgetItem("📁"))
                table.setItem(row, 3, QTableWidgetItem(""))
            else:
                table.setItem(row, 0, name_item)
                table.setItem(row, 1, QTableWidgetItem("—"))
                table.setItem(row, 2, QTableWidgetItem("🔐"))
                table.setItem(row, 3, self._create_eye_item(visible=False))

        table.setUpdatesEnabled(True)

        # В небольших каталогах сразу показываем первые значения.
        # В больших — читаем только выбранную строку, чтобы не делать N+1.
        if len(items) <= self.PREVIEW_LIMIT:
            for row in range(table.rowCount()):
                self._load_row_value(table, row)

    def _fill_secret_table(self, table, data):
        table.setUpdatesEnabled(False)
        table.setRowCount(len(data))

        for row, (key, value) in enumerate(data.items()):
            key_item = QTableWidgetItem(str(key))
            key_item.setData(Qt.UserRole, str(key))
            table.setItem(row, 0, key_item)

            value_item = self.create_password_item(str(value), show=False)
            table.setItem(row, 1, value_item)
            table.setItem(row, 2, self._create_eye_item(visible=False))

        table.setUpdatesEnabled(True)

    def _create_eye_item(self, visible: bool) -> QTableWidgetItem:
        item = QTableWidgetItem()
        item.setData(Qt.UserRole, visible)
        item.setTextAlignment(Qt.AlignCenter)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self._update_eye_item(item, visible)
        return item

    def _update_eye_item(self, item: QTableWidgetItem, visible: bool):
        item.setIcon(self._eye_icon_visible if visible else self._eye_icon_hidden)
        item.setToolTip(
            "Скрыть значение" if visible else "Показать значение"
        )
        item.setData(Qt.UserRole, visible)

    def _on_table_cell_clicked(self, table, row, column, eye_column):
        if column != eye_column:
            return
        if table is self.dir_table and self._is_folder_row(table, row):
            return
        self._toggle_row_visibility(table, row, eye_column)

    def _toggle_row_visibility(self, table, row, eye_column):
        value_item = table.item(row, 1)
        if value_item is None:
            return

        real_value = value_item.data(Qt.UserRole + 1)
        if real_value is None:
            if table is self.dir_table:
                self._load_row_value(table, row)
                value_item = table.item(row, 1)
                if value_item is None:
                    return
                real_value = value_item.data(Qt.UserRole + 1)
            if real_value is None:
                return

        visible = value_item.data(Qt.UserRole) != "visible"
        new_item = self.create_password_item(real_value, show=visible)
        table.setItem(row, 1, new_item)

        eye_item = table.item(row, eye_column)
        if eye_item is None:
            eye_item = self._create_eye_item(visible)
            table.setItem(row, eye_column, eye_item)
        else:
            self._update_eye_item(eye_item, visible)

    @staticmethod
    def _is_folder_row(table, row) -> bool:
        type_item = table.item(row, 2)
        return bool(type_item and "📁" in type_item.text())

    def _load_row_value(self, table, row, force=False) -> bool:
        name_item = table.item(row, 0)
        if not name_item:
            return False
        path = name_item.data(Qt.UserRole)
        if not path or self._is_folder_row(table, row):
            return False

        try:
            data = self._get_secret(path, force=force)
        except Exception as e:
            self.debug_log(f"Не удалось прочитать {path}: {e}")
            table.setItem(row, 1, QTableWidgetItem("🔒 Ошибка"))
            return False

        first_value = next(iter(data.values()), "")
        table.setItem(row, 1, self.create_password_item(first_value, show=False))

        eye_item = table.item(row, 3)
        if eye_item:
            self._update_eye_item(eye_item, False)
        return True

    def on_table_selection_changed(self, table):
        if table is not self.dir_table:
            return

        self._update_delete_action()

        row = table.currentRow()
        if row < 0:
            return

        value_item = table.item(row, 1)
        if value_item and value_item.data(Qt.UserRole) in ("hidden", "visible"):
            return
        if value_item and value_item.text() in ("📂 Папка", "🔒 Ошибка"):
            return

        self._load_row_value(table, row)

    def create_password_item(self, value, show=False):
        item = QTableWidgetItem()
        str_value = str(value) if value is not None else ""
        item.setData(Qt.UserRole + 1, str_value)

        if show:
            item.setText(str_value if str_value else "(пусто)")
            item.setData(Qt.UserRole, "visible")
        else:
            # Фиксированное число точек: не показываем длину значения
            # и не добавляем «…» после упора в лимит.
            item.setText("•" * self.MASK_CHARS if str_value else "(пусто)")
            item.setData(Qt.UserRole, "hidden")

        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    # ------------------------------------------------------------------
    # Клики и контекстные меню
    # ------------------------------------------------------------------
    def on_table_double_click(self, item):
        if not item or item.row() < 0:
            return
        table = item.tableWidget()
        row = item.row()
        column = item.column()

        if table is self.secret_table:
            if column == 2:
                return
            if column == 0:
                key_item = table.item(row, 0)
                if key_item:
                    self.copy_to_clipboard(key_item.text())
                return
            self._copy_table_value(table, row)
            return

        name_item = table.item(row, 0)
        if not name_item:
            return
        path = name_item.data(Qt.UserRole)
        if not path:
            return

        is_folder = self._is_folder_row(table, row)

        if not is_folder and column == 1:
            self._copy_table_value(table, row)
            return

        if is_folder:
            self.open_directory(path)
        else:
            self.open_secret(path)

    def _copy_table_value(self, table, row):
        value_item = table.item(row, 1)
        if value_item is None:
            return
        real_value = value_item.data(Qt.UserRole + 1)
        if real_value:
            self.copy_to_clipboard(real_value)

    def _show_directory_context_menu(self, pos):
        table = self.dir_table
        item = table.itemAt(pos)
        if not item:
            return
        table.setCurrentCell(item.row(), 0)

        row = item.row()
        name_item = table.item(row, 0)
        if not name_item:
            return
        path = name_item.data(Qt.UserRole)
        if not path:
            return

        is_folder = self._is_folder_row(table, row)

        menu = QMenu(self)
        if is_folder:
            menu.addAction(
                "📂 Открыть", lambda: self.open_directory(path)
            )
        else:
            menu.addAction(
                "📄 Открыть", lambda: self.open_secret(path)
            )
            menu.addAction(
                "📋 Скопировать значение",
                lambda: self._copy_value_at_row(table, row),
            )
            menu.addAction(
                "🔗 Скопировать путь", lambda: self.copy_to_clipboard(path)
            )
            menu.addSeparator()
            menu.addAction("✏️ Изменить", lambda: self.edit_secret(path))
            menu.addAction("🗑️ Удалить", lambda: self.delete_secret_path(path))

        menu.addSeparator()
        menu.addAction(
            "🔄 Обновить",
            lambda: self.load_directory(self._directory_path),
        )
        menu.exec(table.viewport().mapToGlobal(pos))

    def _show_secret_context_menu(self, pos):
        table = self.secret_table
        item = table.itemAt(pos)
        if not item:
            return
        row = item.row()
        table.setCurrentCell(row, 0)

        key_item = table.item(row, 0)
        key = key_item.text() if key_item else ""
        path = self._secret_path or ""

        menu = QMenu(self)
        menu.addAction(
            "📋 Скопировать значение",
            lambda: self._copy_table_value(table, row),
        )
        menu.addAction("🔑 Скопировать ключ", lambda: self.copy_to_clipboard(key))
        menu.addAction("🔗 Скопировать путь", lambda: self.copy_to_clipboard(path))
        menu.addSeparator()
        menu.addAction("✏️ Изменить секрет", lambda: self.edit_secret(path))
        menu.addAction(
            "🗑️ Удалить секрет", lambda: self.delete_secret_path(path)
        )
        menu.addSeparator()
        menu.addAction("🔄 Обновить", self.refresh_active_view)
        menu.exec(table.viewport().mapToGlobal(pos))

    def _copy_value_at_row(self, table, row):
        name_item = table.item(row, 0)
        if not name_item:
            return
        path = name_item.data(Qt.UserRole)
        try:
            data = self._get_secret(path)
        except Exception as e:
            self._report_error(str(e), e)
            return
        value = next(iter(data.values()), "")
        if value:
            self.copy_to_clipboard(value)

    # ------------------------------------------------------------------
    # Буфер обмена
    # ------------------------------------------------------------------
    def copy_to_clipboard(self, text):
        text = str(text)
        QApplication.clipboard().setText(text)
        self._clipboard_value = text
        self._clipboard_deadline = (
            time.monotonic() + self.CLIPBOARD_CLEAR_SECONDS
        )
        self._clipboard_timer.start()
        self._update_clipboard_countdown()

    def _update_clipboard_countdown(self):
        if self._clipboard_value is None or self._clipboard_deadline is None:
            self._clipboard_timer.stop()
            self.clipboard_label.setText("")
            return

        remaining = math.ceil(self._clipboard_deadline - time.monotonic())
        if remaining <= 0:
            self._clear_clipboard()
            return

        self.clipboard_label.setText(
            f"📋 Буфер очистится через {remaining} с"
        )

    def _clear_clipboard(self):
        cleared = False
        if (
            self._clipboard_value is not None
            and QApplication.clipboard().text() == self._clipboard_value
        ):
            QApplication.clipboard().clear()
            cleared = True

        self._clipboard_value = None
        self._clipboard_deadline = None
        self._clipboard_timer.stop()
        self.clipboard_label.setText("🧹 Буфер обмена очищен" if cleared else "")

    def copy_secret_data(self, data):
        text = "\n".join(f"{k}: {v}" for k, v in data.items())
        self.copy_to_clipboard(text)

    # ------------------------------------------------------------------
    # Обновление активной панели
    # ------------------------------------------------------------------
    def refresh_active_view(self):
        if not self.client:
            return

        path = self._active_path
        if path == "" or path.endswith("/"):
            self.load_directory(path)
        else:
            self.show_secret(path)

    # ------------------------------------------------------------------
    # Создание / редактирование / удаление
    # ------------------------------------------------------------------
    def _active_directory(self):
        """Каталог, в контексте которого создаётся новый секрет (П1)."""
        path = self._active_path or ""
        if path and not path.endswith("/"):
            path = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
        return path

    def create_secret(self):
        self._create_secret(self._active_directory())

    def _create_secret(self, directory=""):
        if not self.client:
            self.warn("Сначала подключитесь")
            return

        dialog = SecretDialog(self, default_path=directory)
        if not dialog.exec():
            return

        path, data = dialog.get_secret()
        if not path or not data:
            self.warn("Путь и данные не могут быть пустыми")
            return

        try:
            existing = self._get_secret(path, force=True)
            if existing:
                reply = QMessageBox.question(
                    self,
                    "Секрет уже существует",
                    f"Секрет '{path}' уже существует.\n\n"
                    "Хотите перезаписать его?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                if reply == QMessageBox.No:
                    self.info("⏹️ Создание отменено")
                    return

            self.client.create_secret(path, data)
            self._invalidate_cache(path)
            self._active_path = path
            self.refresh(silent=True)
            self.info(
                f"✅ {'Обновлён' if existing else 'Создан'} секрет: {path}"
            )
        except Exception as e:
            self._report_error(str(e), e)

    def edit_secret(self, path):
        if not self.client or not path:
            return

        try:
            data = self._get_secret(path, force=True)
        except Exception as e:
            self._report_error(str(e), e)
            return

        dialog = SecretDialog(self, existing_path=path, existing_data=data)
        if not dialog.exec():
            return

        new_path, new_data = dialog.get_secret()
        if not new_data:
            self.warn("Добавьте хотя бы одну пару ключ-значение")
            return

        try:
            self.client.create_secret(new_path, new_data)
            self._invalidate_cache(path)
            self._active_path = new_path
            self.refresh(silent=True)
            self.info(f"✅ Секрет обновлён: {new_path}")
        except Exception as e:
            self._report_error(str(e), e)

    def rename_secret(self, path):
        """Переименовывает секрет: read → write → delete (папки не трогаем)."""
        if not self.client or not path:
            return

        new_path, ok = QInputDialog.getText(
            self,
            "Переименовать секрет",
            "Новый путь:",
            text=path,
        )
        if not ok:
            return

        new_path = (new_path or "").strip().strip("/")
        if not new_path or new_path == path:
            return

        try:
            data = self._get_secret(path, force=True)
            if not data:
                self.warn(f"Секрет не найден: {path}")
                return

            self.client.create_secret(new_path, data)
            self.client.delete_secret(path)
            self._invalidate_cache(path)
            self._invalidate_cache(new_path)
            if self._secret_path == path:
                self._secret_path = new_path
            if self._active_path == path:
                self._active_path = new_path
            self.refresh(silent=True)
            self.info(f"✏️ Переименован: {path} → {new_path}")
        except Exception as e:
            self._report_error(str(e), e)

    def _selected_secret_for_deletion(self):
        """Возвращает путь секрета, который сейчас выбран для удаления."""
        if (
            self.content_stack.currentWidget() is self.secret_page
            and self._secret_path
        ):
            return self._secret_path

        if self.content_stack.currentWidget() is self.directory_page:
            table = self.dir_table
            row = table.currentRow()
            if row < 0 or self._is_folder_row(table, row):
                return None
            name_item = table.item(row, 0)
            if name_item:
                return name_item.data(Qt.UserRole)

        return None

    def _update_delete_action(self):
        """Обновляет единственную кнопку удаления под текущий выбор."""
        path = self._selected_secret_for_deletion()
        if path:
            name = path.rstrip("/").rsplit("/", 1)[-1]
            self.btn_delete.setEnabled(True)
            self.btn_delete.setToolTip(f"Удалить секрет: {path}")
            self.delete_target_label.setText(f"Выбран секрет: {name}")
            self.delete_target_label.setToolTip(path)
            return

        self.btn_delete.setEnabled(False)
        self.btn_delete.setToolTip("Выберите секрет для удаления")
        self.delete_target_label.setToolTip("")

        if (
            self.content_stack.currentWidget() is self.directory_page
            and self.dir_table.currentRow() >= 0
        ):
            self.delete_target_label.setText(
                "Выбран каталог — удаление недоступно"
            )
        else:
            self.delete_target_label.setText("Секрет не выбран")

    def delete_secret(self):
        """Удаляет секрет, выбранный в правой панели."""
        path = self._selected_secret_for_deletion()
        if not path:
            self.warn("Выберите секрет для удаления")
            return
        self.delete_secret_path(path)

    def _confirm_secret_deletion(self, path):
        dialog = DeleteSecretDialog(path, self)
        return bool(dialog.exec())

    def delete_secret_path(self, path):
        if not self.client or not path:
            return

        if not self._confirm_secret_deletion(path):
            self.info("⏹️ Удаление отменено")
            return

        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        parent_path = f"{parent}/" if parent else ""

        try:
            self.client.delete_secret(path)
            self._invalidate_cache(path)
            if self._secret_path == path:
                self._secret_path = None
                self._secret_data = {}
            if self._active_path == path:
                self._active_path = parent_path
            self.refresh(silent=True)
            self.info(f"🗑️ Удалён: {path}")
        except Exception as e:
            self._report_error(str(e), e)

    # ------------------------------------------------------------------
    # Поиск
    # ------------------------------------------------------------------
    def show_search_dialog(self):
        if not self.client:
            self.warn("Сначала подключитесь к Vault")
            return

        dialog = SearchDialog(self.client, self)
        dialog.exec()
