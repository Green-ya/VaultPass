import logging
from logging.handlers import RotatingFileHandler

import pytest

import logging_setup


@pytest.fixture
def restored_root():
    """Сохраняет и восстанавливает обработчики корневого логгера.

    ``setup_logging`` снимает все обработчики, включая перехватчик pytest,
    поэтому после теста возвращаем исходное состояние.
    """
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield root

    for handler in list(root.handlers):
        if handler not in original_handlers:
            root.removeHandler(handler)
            handler.close()
    for handler in original_handlers:
        if handler not in root.handlers:
            root.addHandler(handler)
    root.setLevel(original_level)


@pytest.fixture
def log_paths(tmp_path, monkeypatch):
    log_dir = tmp_path / "vaultpass"
    log_file = log_dir / "vaultpass.log"
    monkeypatch.setattr(logging_setup, "LOG_DIR", log_dir)
    monkeypatch.setattr(logging_setup, "LOG_FILE", log_file)
    return log_dir, log_file


def _file_handlers(root):
    return [h for h in root.handlers if isinstance(h, RotatingFileHandler)]


def test_setup_logging_writes_to_file(restored_root, log_paths):
    log_dir, log_file = log_paths
    logging_setup.setup_logging(debug=False)

    logging.getLogger("vaultpass.test").info("проверочное сообщение")
    for handler in restored_root.handlers:
        handler.flush()

    assert log_file.exists()
    assert "проверочное сообщение" in log_file.read_text(encoding="utf-8")
    # Каталог с логами доступен только владельцу
    assert log_dir.stat().st_mode & 0o777 == 0o700


def test_setup_logging_debug_raises_console_level(restored_root, log_paths):
    root = logging_setup.setup_logging(debug=False)
    console = [h for h in root.handlers if not isinstance(h, RotatingFileHandler)]
    assert console
    assert console[0].level == logging.WARNING

    logging_setup.set_debug(True)
    assert console[0].level == logging.DEBUG
    assert _file_handlers(root)[0].level == logging.DEBUG

    logging_setup.set_debug(False)
    assert console[0].level == logging.WARNING
    assert _file_handlers(root)[0].level == logging.INFO


def test_setup_logging_is_idempotent(restored_root, log_paths):
    root = logging_setup.setup_logging(debug=False)
    count = len(root.handlers)
    logging_setup.setup_logging(debug=False)
    assert len(root.handlers) == count
