import logging
import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

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
