import logging
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QPushButton,
    QTableWidgetItem,
)

import config_manager as config_module
from config_manager import ConfigManager
from ui.dialogs import ConfigDialog, DeleteSecretDialog, SecretDialog
from ui.main_window import MainWindow
from ui.search_dialog import SearchDialog
from vault_client import VaultClientError


class FakeClient:
    def __init__(self):
        self.tree = {
            "": ["folder/", "root-secret"],
            "folder/": ["nested"],
        }
        self.deleted = []
        self.created = []

    def list_secrets(self, path=""):
        return self.tree.get(path, [])

    def iter_all_secrets(self, root=""):
        root = (root or "").strip("/")
        stack = [f"{root}/" if root else ""]
        while stack:
            path = stack.pop()
            for item in self.list_secrets(path):
                full_path = f"{path}{item}"
                if item.endswith("/"):
                    stack.append(full_path)
                else:
                    yield full_path

    def read_secret(self, path):
        return {"password": f"value-of-{path}", "user": "alice"}

    def create_secret(self, path, data):
        self.created.append((path, data))
        parent = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
        name = path.rsplit("/", 1)[-1]
        if name not in self.tree.setdefault(parent, []):
            self.tree[parent].append(name)
        return True

    def delete_secret(self, path):
        self.deleted.append(path)
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        parent_path = f"{parent}/" if parent else ""
        name = path.rsplit("/", 1)[-1]
        if name in self.tree.get(parent_path, []):
            self.tree[parent_path].remove(name)
        return True


class CountingClient(FakeClient):
    def __init__(self, count):
        super().__init__()
        self.tree = {"": [f"secret-{i}" for i in range(count)]}
        self.reads = []

    def read_secret(self, path):
        self.reads.append(path)
        return super().read_secret(path)


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "keyring", None)
    monkeypatch.setattr(ConfigManager, "CONFIG_DIR", tmp_path / "vaultpass")
    monkeypatch.setattr(
        ConfigManager, "CONFIG_FILE", tmp_path / "vaultpass" / "config.enc"
    )
    monkeypatch.setattr(
        ConfigManager, "KEY_FILE", tmp_path / "vaultpass" / "key.bin"
    )
    monkeypatch.setattr(ConfigManager, "LEGACY_DIR", tmp_path / "legacy")

    main_window = MainWindow()
    yield main_window

    main_window._clipboard_timer.stop()
    main_window.close()
    main_window.deleteLater()
    QApplication.clipboard().clear()
    app.processEvents()


def test_window_starts_without_config(window):
    assert window.client is None
    assert window.content_stack.currentWidget() is window.empty_page
    assert not hasattr(window, "tab_widget")
    assert window.windowTitle().count("VaultPass") == 1
    assert window.status_label.text() == "Не подключено"


def test_refresh_populates_tree_and_directory(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    root = window.tree.topLevelItem(0)
    assert root.text(0) == "📁 /"
    assert root.childCount() == 2
    assert window.tree.currentItem() is root

    assert window.content_stack.currentWidget() is window.directory_page
    assert window.dir_path_label.text() == "📂 /"

    table = window.dir_table
    assert table.rowCount() == 2
    assert table.item(0, 1).text() == "📂 Папка"
    assert not table.item(0, 0).font().bold()

    # В маленьком каталоге значения подгружаются сразу (маскированно)
    value_item = table.item(1, 1)
    assert value_item.data(Qt.UserRole + 1) == "value-of-root-secret"
    assert value_item.text() == "•" * MainWindow.MASK_CHARS
    assert "…" not in value_item.text()
    assert table.item(1, 3).data(Qt.UserRole) is False


def test_selecting_secret_shows_secret_view(window):
    window.client = FakeClient()
    window.refresh(silent=True)
    window.open_secret("root-secret")

    assert window.content_stack.currentWidget() is window.secret_page
    assert window._secret_path == "root-secret"
    assert "root-secret" in window.secret_info_label.text()

    table = window.secret_table
    assert table.rowCount() == 2
    assert table.item(0, 0).text() == "password"
    assert table.item(0, 1).text() == "•" * MainWindow.MASK_CHARS
    assert table.item(0, 1).data(Qt.UserRole + 1) == "value-of-root-secret"
    assert table.item(0, 2).data(Qt.UserRole) is False


def test_directory_eye_toggles_only_its_row(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    table = window.dir_table
    row = 1
    assert "value-of-root-secret" not in table.item(row, 1).text()

    window._toggle_row_visibility(table, row, 3)
    assert table.item(row, 1).text() == "value-of-root-secret"
    assert table.item(row, 3).data(Qt.UserRole) is True
    # Соседняя строка-папка не изменилась
    assert table.item(0, 1).text() == "📂 Папка"

    window._toggle_row_visibility(table, row, 3)
    assert "value-of-root-secret" not in table.item(row, 1).text()
    assert table.item(row, 3).data(Qt.UserRole) is False


def test_secret_eye_toggles_only_its_row(window):
    window.client = FakeClient()
    window.refresh(silent=True)
    window.open_secret("root-secret")

    table = window.secret_table
    window._toggle_row_visibility(table, 0, 2)

    assert table.item(0, 1).text() == "value-of-root-secret"
    assert table.item(0, 2).data(Qt.UserRole) is True
    assert table.item(1, 1).text() != "alice"

    window._toggle_row_visibility(table, 0, 2)
    assert table.item(0, 2).data(Qt.UserRole) is False


def test_clipboard_countdown_and_cleanup(window):
    window.copy_to_clipboard("top-secret-value")

    assert "top-secret-value" not in window.clipboard_label.text()
    assert "top-secret-value" not in window.status_label.text()
    assert QApplication.clipboard().text() == "top-secret-value"
    assert "30 с" in window.clipboard_label.text()

    window._clipboard_deadline = time.monotonic() + 10
    window._update_clipboard_countdown()
    assert "10 с" in window.clipboard_label.text()

    window._clipboard_deadline = time.monotonic() - 1
    window._update_clipboard_countdown()

    assert QApplication.clipboard().text() == ""
    assert "очищен" in window.clipboard_label.text()
    assert not window._clipboard_timer.isActive()


def test_status_message_survives_clipboard_countdown(window):
    window.copy_to_clipboard("top-secret-value")
    window.status_label.setText("✅ Секрет создан")

    window._clipboard_deadline = time.monotonic() + 15
    window._update_clipboard_countdown()

    # Счётчик буфера не затирает уведомление в статусной строке
    assert window.status_label.text() == "✅ Секрет создан"
    assert "15 с" in window.clipboard_label.text()


def test_close_clears_clipboard_and_cache(window):
    window.copy_to_clipboard("top-secret-value")
    window._secret_cache["some/secret"] = (time.monotonic(), {"k": "v"})

    window.close()

    assert QApplication.clipboard().text() == ""
    assert window._secret_cache == {}
    assert not window._clipboard_timer.isActive()


def test_notify_levels_write_to_status_label(window):
    window.info("ℹ️ инфо")
    assert window.status_label.text() == "ℹ️ инфо"

    window.warn("⚠️ предупреждение")
    assert window.status_label.text() == "⚠️ предупреждение"

    window.error("❌ ошибка")
    assert window.status_label.text() == "❌ ошибка"
    # Ошибка не автоскрывается — держится до следующего сообщения
    assert not window._status_timer.isActive()


def test_info_autohides_via_timer(window):
    window.info("ℹ️ привет", timeout=1000)
    assert window._status_timer.isActive()

    window._status_timer.stop()
    window._reset_status()
    assert window.status_label.text() == "Готово"


def test_search_without_connection_warns_in_status(window):
    assert window.client is None

    window.show_search_dialog()

    assert "подключитесь" in window.status_label.text().lower()


def test_config_dialog_inline_validation(window):
    dialog = ConfigDialog(window)

    dialog.url_edit.setText("")
    dialog.token_edit.setText("")
    dialog.accept()
    assert "URL" in dialog.error_label.text()

    dialog.url_edit.setText("https://vault.local")
    dialog.token_edit.setText("")
    dialog.accept()
    assert "токен" in dialog.error_label.text().lower()

    dialog.close()


def test_secret_dialog_inline_validation(window):
    dialog = SecretDialog(window)

    dialog.path_edit.setText("")
    dialog.accept()
    assert "путь" in dialog.error_label.text().lower()

    dialog.path_edit.setText("team/db/prod")
    dialog.accept()  # строки пустые → нет данных
    assert "ключ" in dialog.error_label.text().lower()

    dialog.close()


def test_secret_dialog_generator_fills_row(window):
    dialog = SecretDialog(window)
    dialog.length_spin.setValue(32)
    dialog.generate_into_row(0)

    value = dialog.table.item(0, 1).text()
    assert len(value) == 32
    assert len(set(value)) > 1

    dialog.close()


def test_search_error_reported_in_dialog_status(window):
    class BoomClient(FakeClient):
        def iter_all_secrets(self, root=""):
            raise VaultClientError("сеть недоступна")

    dialog = SearchDialog(BoomClient(), window)
    dialog.query_edit.setText("x")
    dialog.run_search()

    assert "❌" in dialog.status_label.text()
    assert "сеть недоступна" in dialog.status_label.text()
    dialog.close()


def test_expanded_folders_survive_refresh(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    root = window.tree.topLevelItem(0)
    folder = root.child(0)
    folder.setExpanded(True)

    window.refresh(silent=True)

    root = window.tree.topLevelItem(0)
    folder = root.child(0)
    assert folder.isExpanded()
    assert folder.childCount() == 1


def test_search_dialog_matches_paths_and_values(window):
    dialog = SearchDialog(FakeClient(), window)

    dialog._match_path("folder/nested", "nested")
    assert dialog.results.rowCount() == 1
    assert dialog.results.item(0, 0).text() == "folder/nested"

    dialog._match_values("root-secret", "alice")
    assert dialog.results.rowCount() == 2
    value_item = dialog.results.item(1, 2)
    assert value_item.data(Qt.UserRole + 1) == "alice"
    assert value_item.text() == "•" * 12
    assert "…" not in value_item.text()

    dialog.close()


def test_search_dialog_full_scan(window):
    dialog = SearchDialog(FakeClient(), window)
    dialog.search_values_cb.setChecked(True)

    dialog.query_edit.setText("alice")
    dialog.run_search()

    # "alice" встречается в значении user у обоих секретов
    assert dialog.results.rowCount() == 2
    dialog.close()


def test_search_dialog_opens_secret_in_main_view(window):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)

    dialog = SearchDialog(client, window)
    dialog._match_path("folder/nested", "nested")
    dialog.results.setCurrentCell(0, 0)
    dialog.open_selected()

    assert window.content_stack.currentWidget() is window.secret_page
    assert window._secret_path == "folder/nested"
    dialog.close()


def test_single_delete_button_tracks_selection(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    assert len(window.findChildren(QPushButton, "deleteButton")) == 1
    assert not window.btn_delete.isEnabled()

    window.dir_table.setCurrentCell(0, 0)  # папка
    assert not window.btn_delete.isEnabled()
    assert "каталог" in window.delete_target_label.text().lower()

    window.dir_table.setCurrentCell(1, 0)  # секрет
    assert window.btn_delete.isEnabled()
    assert "root-secret" in window.delete_target_label.text()

    window.open_secret("root-secret")
    assert window.btn_delete.isEnabled()

    window.open_directory("")
    assert not window.btn_delete.isEnabled()


def test_delete_confirmation_requires_exact_secret_name(window):
    dialog = DeleteSecretDialog("folder/nested", window)

    assert not dialog.delete_btn.isEnabled()
    dialog.name_edit.setText("nested-wrong")
    assert not dialog.delete_btn.isEnabled()
    dialog.name_edit.setText("nested")
    assert dialog.delete_btn.isEnabled()

    dialog.close()


def test_delete_button_on_secret_view_deletes_secret(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    window.open_secret("root-secret")

    monkeypatch.setattr(
        window, "_confirm_secret_deletion", lambda path: True
    )
    window.delete_secret()

    # Удаляется путь секрета, а не имя ключа из таблицы
    assert client.deleted == ["root-secret"]
    assert window.content_stack.currentWidget() is window.directory_page
    assert window.tree.currentItem() is window.tree.topLevelItem(0)


def test_delete_from_directory_table_uses_selected_secret(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    window.dir_table.setCurrentCell(1, 0)

    monkeypatch.setattr(
        window, "_confirm_secret_deletion", lambda path: True
    )
    window.delete_secret()

    assert client.deleted == ["root-secret"]
    assert window.content_stack.currentWidget() is window.directory_page
    assert not window.btn_delete.isEnabled()


def test_cancelled_delete_keeps_secret(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    window.open_secret("root-secret")

    monkeypatch.setattr(
        window, "_confirm_secret_deletion", lambda path: False
    )
    window.delete_secret()

    assert client.deleted == []
    assert "отменено" in window.status_label.text().lower()


def test_large_directory_loads_values_lazily(window):
    client = CountingClient(MainWindow.PREVIEW_LIMIT + 10)
    window.client = client

    window.refresh(silent=True)

    # В большом каталоге значения не читаются заранее вообще
    assert len(client.reads) == 0

    table = window.dir_table
    last_row = table.rowCount() - 1
    table.setCurrentCell(last_row, 0)

    assert len(client.reads) == 1
    assert client.reads[-1] == f"secret-{last_row}"


def test_report_error_logs_details_and_shows_message(window, caplog):
    with caplog.at_level(logging.ERROR, logger="ui.main_window"):
        window._report_error(
            "Не удалось загрузить секрет: boom", RuntimeError("boom")
        )

    assert window.status_label.text().startswith("❌")
    assert "boom" in window.status_label.text()

    records = [r for r in caplog.records if r.name == "ui.main_window"]
    assert records
    assert records[-1].exc_info is not None


def test_load_directory_error_is_reported_and_logged(window, caplog):
    class BoomClient(FakeClient):
        def list_secrets(self, path=""):
            raise RuntimeError("сеть недоступна")

    window.client = BoomClient()

    with caplog.at_level(logging.ERROR, logger="ui.main_window"):
        window.load_directory("")

    assert window.status_label.text().startswith("❌")
    assert any("сеть недоступна" in r.getMessage() for r in caplog.records)


def test_show_secret_error_is_reported(window, caplog):
    class BoomClient(FakeClient):
        def read_secret(self, path):
            raise RuntimeError("секрет недоступен")

    window.client = BoomClient()

    with caplog.at_level(logging.ERROR, logger="ui.main_window"):
        window.show_secret("root-secret")

    assert window.status_label.text().startswith("❌")
    assert window.content_stack.currentWidget() is not window.secret_page


def test_disconnect_clears_client_tree_and_cache(window):
    window.client = FakeClient()
    window.refresh(silent=True)
    window.open_secret("root-secret")
    window._secret_cache["root-secret"] = (time.monotonic(), {"k": "v"})
    window.copy_to_clipboard("secret-value")

    window.disconnect_from_vault()

    assert window.client is None
    assert window._secret_cache == {}
    assert window.tree.topLevelItemCount() == 0
    assert window.content_stack.currentWidget() is window.empty_page
    assert window.status_label.text() == "Не подключено"
    assert window.delete_target_label.text() == "Секрет не выбран"
    assert QApplication.clipboard().text() == ""


def test_disconnect_without_connection_warns(window):
    assert window.client is None

    window.disconnect_from_vault()

    assert "нет активного подключения" in window.status_label.text().lower()


def test_purge_expired_cache_removes_old_entries(window):
    now = time.monotonic()
    window._secret_cache["fresh"] = (now, {"k": "v"})
    window._secret_cache["stale"] = (now - window.CACHE_TTL - 1, {"k": "v"})

    window._purge_expired_cache()

    assert "fresh" in window._secret_cache
    assert "stale" not in window._secret_cache


def test_connect_starts_and_disconnect_stops_cache_timer(window, monkeypatch):
    class StubClient:
        def __init__(self, *args, **kwargs):
            pass

        def list_secrets(self, path=""):
            return []

        def read_secret(self, path):
            return {}

    monkeypatch.setattr("ui.main_window.VaultClient", StubClient)

    window._connect_to_vault(
        "https://vault.local:8200", "token", "secret", save=False
    )

    assert window.client is not None
    assert window._cache_timer.isActive()
    assert "Подключено" in window.status_label.text()

    window.disconnect_from_vault()
    assert not window._cache_timer.isActive()


def test_secret_dialog_prefills_default_path(window):
    dialog = SecretDialog(window, default_path="team/db/")

    assert dialog.path_edit.text() == "team/db/"
    assert dialog.path_edit.isEnabled()
    dialog.close()


def test_secret_dialog_existing_path_locks_field(window):
    dialog = SecretDialog(
        window, existing_path="team/db/prod", existing_data={"k": "v"}
    )

    assert dialog.path_edit.text() == "team/db/prod"
    assert not dialog.path_edit.isEnabled()
    dialog.close()


def test_active_directory_from_selection(window):
    window._active_path = ""
    assert window._active_directory() == ""

    window._active_path = "folder/"
    assert window._active_directory() == "folder/"

    window._active_path = "folder/nested"
    assert window._active_directory() == "folder/"

    window._active_path = "root-secret"
    assert window._active_directory() == ""


def test_create_secret_uses_active_directory(window, monkeypatch):
    captured = {}

    class StubDialog:
        def __init__(self, parent=None, default_path="", **kwargs):
            captured["default_path"] = default_path

        def exec(self):
            return 0

    monkeypatch.setattr("ui.main_window.SecretDialog", StubDialog)

    window.client = FakeClient()
    window._active_path = "folder/"
    window.create_secret()

    assert captured["default_path"] == "folder/"


def test_tree_menu_for_directory_offers_new_secret(window):
    menu = window._build_tree_menu("folder/")
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]

    assert any("Новый секрет" in t for t in texts)
    assert not any("Переименовать" in t for t in texts)
    assert not any("Удалить" in t for t in texts)
    menu.deleteLater()


def test_tree_menu_for_secret_offers_rename_and_delete(window):
    menu = window._build_tree_menu("root-secret")
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]

    assert any("Переименовать" in t for t in texts)
    assert any("Удалить" in t for t in texts)
    assert not any("Новый секрет" in t for t in texts)
    menu.deleteLater()


def test_rename_secret_reads_writes_deletes(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    window.open_secret("root-secret")

    monkeypatch.setattr(
        "ui.main_window.QInputDialog.getText",
        staticmethod(lambda *args, **kwargs: ("renamed-secret", True)),
    )

    window.rename_secret("root-secret")

    assert client.created[-1][0] == "renamed-secret"
    assert client.deleted == ["root-secret"]
    assert window._secret_path == "renamed-secret"
    assert "Переименован" in window.status_label.text()


def test_rename_secret_cancelled_is_noop(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)

    monkeypatch.setattr(
        "ui.main_window.QInputDialog.getText",
        staticmethod(lambda *args, **kwargs: ("", False)),
    )

    window.rename_secret("root-secret")

    assert client.created == []
    assert client.deleted == []


def test_rename_secret_unchanged_path_is_noop(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)

    monkeypatch.setattr(
        "ui.main_window.QInputDialog.getText",
        staticmethod(lambda *args, **kwargs: ("root-secret", True)),
    )

    window.rename_secret("root-secret")

    assert client.created == []
    assert client.deleted == []


def test_ctrl_c_copies_real_value_from_secret_table(window):
    window.client = FakeClient()
    window.refresh(silent=True)
    window.open_secret("root-secret")

    window.secret_table.setCurrentCell(0, 1)
    QTest.keyClick(window.secret_table, Qt.Key_C, Qt.ControlModifier)

    assert QApplication.clipboard().text() == "value-of-root-secret"


def test_ctrl_c_copies_real_value_from_directory_table(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    window.dir_table.setCurrentCell(1, 0)
    QTest.keyClick(window.dir_table, Qt.Key_C, Qt.ControlModifier)

    assert QApplication.clipboard().text() == "value-of-root-secret"


def test_ctrl_c_on_folder_row_copies_nothing(window):
    window.client = FakeClient()
    window.refresh(silent=True)
    QApplication.clipboard().clear()

    window.dir_table.setCurrentCell(0, 0)
    QTest.keyClick(window.dir_table, Qt.Key_C, Qt.ControlModifier)

    assert QApplication.clipboard().text() == ""


def test_ctrl_c_on_lazy_directory_row_reads_value(window):
    client = CountingClient(MainWindow.PREVIEW_LIMIT + 5)
    window.client = client
    window.refresh(silent=True)
    QApplication.clipboard().clear()

    last_row = window.dir_table.rowCount() - 1
    window.dir_table.setCurrentCell(last_row, 0)
    QTest.keyClick(window.dir_table, Qt.Key_C, Qt.ControlModifier)

    assert QApplication.clipboard().text() == f"value-of-secret-{last_row}"


def test_ctrl_shift_enter_accepts_secret_dialog(window):
    dialog = SecretDialog(window, default_path="team/")
    dialog.table.setItem(0, 0, QTableWidgetItem("password"))
    dialog.table.setItem(0, 1, QTableWidgetItem("s3cret"))

    QTest.keyClick(
        dialog, Qt.Key_Return, Qt.ControlModifier | Qt.ShiftModifier
    )

    assert dialog.result() == QDialog.Accepted


def test_escape_rejects_secret_dialog(window):
    dialog = SecretDialog(window)

    QTest.keyClick(dialog, Qt.Key_Escape)

    assert dialog.result() == QDialog.Rejected


def test_secret_dialog_copy_uses_window_clipboard_policy(window):
    dialog = SecretDialog(window)
    dialog.table.setItem(0, 0, QTableWidgetItem("password"))
    dialog.table.setItem(0, 1, QTableWidgetItem("s3cret"))

    dialog._copy_row_value(0)

    assert QApplication.clipboard().text() == "s3cret"
    # Копирование из диалога взводит общую автоочистку буфера
    assert window._clipboard_timer.isActive()
    dialog.close()


# ----------------------------------------------------------------------
# Создание / редактирование секретов
# ----------------------------------------------------------------------
def _stub_secret_dialog(monkeypatch, path, data):
    class StubDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return 1

        def get_secret(self):
            return path, data

    monkeypatch.setattr("ui.main_window.SecretDialog", StubDialog)


def _answer_question(monkeypatch, module, yes):
    class FakeMessageBox:
        Yes = 1
        No = 0

        @staticmethod
        def question(*args, **kwargs):
            return 1 if yes else 0

    monkeypatch.setattr(f"{module}.QMessageBox", FakeMessageBox)


def test_create_secret_creates_new(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    _stub_secret_dialog(monkeypatch, "new-secret", {"k": "v"})
    monkeypatch.setattr(window, "_get_secret", lambda path, force=False: {})

    window.create_secret()

    assert client.created[-1] == ("new-secret", {"k": "v"})
    assert window._active_path == "new-secret"
    assert "Создан" in window.status_label.text()


def test_create_secret_without_connection_warns(window):
    window.create_secret()
    assert "подключитесь" in window.status_label.text().lower()


def test_create_secret_overwrite_confirmed(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    _stub_secret_dialog(monkeypatch, "root-secret", {"k": "v"})
    monkeypatch.setattr(
        window, "_get_secret", lambda path, force=False: {"old": "1"}
    )
    _answer_question(monkeypatch, "ui.main_window", yes=True)

    window.create_secret()

    assert client.created[-1] == ("root-secret", {"k": "v"})
    assert "Обновлён" in window.status_label.text()


def test_create_secret_overwrite_cancelled(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    _stub_secret_dialog(monkeypatch, "root-secret", {"k": "v"})
    monkeypatch.setattr(
        window, "_get_secret", lambda path, force=False: {"old": "1"}
    )
    _answer_question(monkeypatch, "ui.main_window", yes=False)

    window.create_secret()

    assert client.created == []
    assert "отменено" in window.status_label.text().lower()


def test_create_secret_client_error_reported(window, monkeypatch):
    class BoomClient(FakeClient):
        def create_secret(self, path, data):
            raise RuntimeError("запись запрещена")

    window.client = BoomClient()
    window.refresh(silent=True)
    _stub_secret_dialog(monkeypatch, "new-secret", {"k": "v"})
    monkeypatch.setattr(window, "_get_secret", lambda path, force=False: {})

    window.create_secret()

    assert window.status_label.text().startswith("❌")
    assert "запись запрещена" in window.status_label.text()


def test_edit_secret_updates_data(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    window.open_secret("root-secret")
    _stub_secret_dialog(monkeypatch, "root-secret", {"k": "new"})

    window.edit_secret("root-secret")

    assert client.created[-1] == ("root-secret", {"k": "new"})
    assert "обновлён" in window.status_label.text().lower()


def test_edit_secret_empty_data_warns(window, monkeypatch):
    client = FakeClient()
    window.client = client
    window.refresh(silent=True)
    _stub_secret_dialog(monkeypatch, "root-secret", {})

    window.edit_secret("root-secret")

    assert client.created == []
    assert "хотя бы одну пару" in window.status_label.text().lower()


def test_edit_secret_read_error_reported(window):
    class BoomClient(FakeClient):
        def read_secret(self, path):
            raise RuntimeError("нет доступа")

    window.client = BoomClient()
    window.edit_secret("root-secret")

    assert window.status_label.text().startswith("❌")


# ----------------------------------------------------------------------
# Дерево: ленивая загрузка и навигация
# ----------------------------------------------------------------------
def test_tree_lazy_loads_on_expand(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    root = window.tree.topLevelItem(0)
    folder = root.child(0)
    assert folder.childCount() == 0

    window.on_tree_expanded(folder)

    assert folder.childCount() == 1
    assert folder.child(0).data(0, Qt.UserRole) == "folder/nested"


def test_ensure_tree_item_returns_none_for_missing(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    assert window._ensure_tree_item("does/not/exist") is None


def test_navigate_to_missing_secret_uses_fallback(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    window._navigate_to("unknown/secret")

    assert window._active_path == "unknown/secret"
    assert window.content_stack.currentWidget() is window.secret_page


def test_populate_tree_error_is_reported(window, caplog):
    class BoomClient(FakeClient):
        def list_secrets(self, path=""):
            raise RuntimeError("boom-list")

    window.client = BoomClient()

    with caplog.at_level(logging.ERROR, logger="ui.main_window"):
        window.refresh()

    # Ошибка не должна затираться сообщением «Обновлено»
    assert window.status_label.text().startswith("❌")
    assert any("boom-list" in r.getMessage() for r in caplog.records)


# ----------------------------------------------------------------------
# Контекстные меню таблиц
# ----------------------------------------------------------------------
def test_directory_menu_filters_items_by_row_type(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    folder_menu = window._build_directory_menu(0, "folder/")
    folder_texts = [
        a.text() for a in folder_menu.actions() if not a.isSeparator()
    ]
    assert any("Открыть" in t for t in folder_texts)
    assert not any("Удалить" in t for t in folder_texts)
    folder_menu.deleteLater()

    secret_menu = window._build_directory_menu(1, "root-secret")
    secret_texts = [
        a.text() for a in secret_menu.actions() if not a.isSeparator()
    ]
    assert any("Скопировать значение" in t for t in secret_texts)
    assert any("Изменить" in t for t in secret_texts)
    assert any("Удалить" in t for t in secret_texts)
    secret_menu.deleteLater()


def test_secret_menu_has_copy_and_delete(window):
    window.client = FakeClient()
    window.refresh(silent=True)
    window.open_secret("root-secret")

    menu = window._build_secret_menu(0)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]

    assert any("Скопировать ключ" in t for t in texts)
    assert any("Удалить секрет" in t for t in texts)
    menu.deleteLater()


# ----------------------------------------------------------------------
# Двойной клик и кэш
# ----------------------------------------------------------------------
def test_double_click_on_directory_row_opens_secret(window):
    window.client = FakeClient()
    window.refresh(silent=True)

    window.on_table_double_click(window.dir_table.item(1, 0))

    assert window.content_stack.currentWidget() is window.secret_page
    assert window._secret_path == "root-secret"


def test_double_click_on_secret_row_copies_value(window):
    window.client = FakeClient()
    window.refresh(silent=True)
    window.open_secret("root-secret")
    QApplication.clipboard().clear()

    window.on_table_double_click(window.secret_table.item(0, 1))

    assert QApplication.clipboard().text() == "value-of-root-secret"


def test_invalidate_cache_recursively_removes_prefix(window):
    now = time.monotonic()
    window._secret_cache = {
        "team/db/prod": (now, {"k": "1"}),
        "team/db/stage": (now, {"k": "2"}),
        "team/api": (now, {"k": "3"}),
    }

    window._invalidate_cache("team/db")

    assert set(window._secret_cache) == {"team/api"}


def test_invalidate_cache_none_clears_all(window):
    window._secret_cache = {"a": (time.monotonic(), {})}
    window._invalidate_cache()
    assert window._secret_cache == {}


def test_copy_secret_data_joins_pairs(window):
    window.copy_secret_data({"user": "alice", "password": "s3cret"})

    text = QApplication.clipboard().text()
    assert "user: alice" in text
    assert "password: s3cret" in text


# ----------------------------------------------------------------------
# SecretDialog: удаление строки и get_secret
# ----------------------------------------------------------------------
def test_secret_dialog_remove_nonempty_row_confirms(window, monkeypatch):
    dialog = SecretDialog(window)
    dialog.table.setItem(0, 0, QTableWidgetItem("k"))
    dialog.table.setItem(0, 1, QTableWidgetItem("v"))

    _answer_question(monkeypatch, "ui.dialogs", yes=False)
    dialog._remove_row(0)
    assert dialog.table.rowCount() == 2

    _answer_question(monkeypatch, "ui.dialogs", yes=True)
    dialog._remove_row(0)
    assert dialog.table.rowCount() == 1
    dialog.close()


def test_secret_dialog_get_secret_normalizes(window):
    dialog = SecretDialog(window)
    dialog.path_edit.setText(" /team/db/prod/ ")
    dialog.table.setItem(0, 0, QTableWidgetItem(" user "))
    dialog.table.setItem(0, 1, QTableWidgetItem("alice"))
    dialog.table.setItem(1, 0, QTableWidgetItem(""))
    dialog.table.setItem(1, 1, QTableWidgetItem("skip"))

    path, data = dialog.get_secret()

    assert path == "team/db/prod"
    assert data == {"user": "alice"}
    dialog.close()


def test_config_dialog_empty_mount_defaults_to_secret(window):
    dialog = ConfigDialog(window)
    dialog.url_edit.setText("https://vault.local")
    dialog.token_edit.setText("token")
    dialog.mount_edit.setText("")

    _, _, mount = dialog.get_config()

    assert mount == "secret"
    dialog.close()
