# AGENTS.md

VaultPass — настольный GUI-менеджер паролей для HashiCorp Vault (KV v2).
Python 3.11–3.12 + PySide6 + hvac. Дистрибуция: AppImage (`build_appimage.sh`),
nix-пакет (`vaultpass.nix`, `flake.nix`). Никаких внешних сервисов — только Vault.

## Workflow

- Спринты строго по порядку; **стоп после каждого спринта**, отчёт, ждём
  подтверждения владельца. Никогда не начинать Sprint N+1 без запроса.
- Код пишет ИИ-ассистент; архитектура, приёмка и тестирование — владелец проекта.
- Каждый шаг = рабочий инкремент: `pytest -q` (Qt offscreen) зелёный + pylint
  без замечаний.
- Проверки перед сдачей: `pytest -q` и `pylint $(git ls-files '*.py')`.
- Нет `TODO: implement` в сдаваемом коде; незавершённое — в явный список задач.
- Один атомарный коммит на логическое изменение, осмысленное сообщение.
- Новая зависимость — только с обоснованием (почему не хватает текущего стека).
- Секреты и токен никогда не попадают в код, логи, статусную строку и тесты.

## Toolchain

- **Python 3.11–3.12**, PySide6, hvac (только Vault KV v2).
- Тесты: `pytest -q` в `QT_QPA_PLATFORM=offscreen` (см. `pytest.ini`); 114+
  тестов; фейки `FakeClient` / `CountingClient` / `FakeKeyring` — в `tests/fakes.py`.
- Линт: `pylint` с `.pylintrc`, целевая оценка 10.00/10.
- CI: GitHub Actions — pylint (`.github/workflows/pylint.yml`) + pytest
  (`.github/workflows/ci.yml`), Python 3.11/3.12.
- keyring в тестах — только через `FakeKeyring`; реальный системный бэкенд
  не поднимаем.

## Dependencies (justified)

- `PySide6` — GUI (Qt6).
- `hvac` — клиент HashiCorp Vault; используется только `client.secrets.kv.v2.*`.
- `cryptography` (Fernet) — шифрование токена на диске; ключ в системном
  keyring с файловым фолбэком `0600` (`config_manager.py`).
- `keyring` — системное хранилище ключей.
- dev: `pytest`, `pytest-qt`, `pylint` (`requirements-dev.txt`).

## Architecture

- `main.py` — точка входа; `run.sh` — запуск из исходников.
- `vault_client.py` — `VaultClient(url, token, mount_point, verify, timeout)`;
  типизированные ошибки `VaultClientError` / `VaultAuthError` /
  `VaultConnectionError`; нормализация путей `_normalize`; `list_secrets`,
  `iter_all_secrets`, `read_secret`, `create_secret`, `delete_secret`.
  Mount point задаётся при подключении; смена без переподключения — спринт 2.
- `config_manager.py` — конфиг, Fernet-шифрование токена, миграция из
  `~/.config/vault-manager`.
- `logging_setup.py` — лог в консоль + файл `~/.config/vaultpass/vaultpass.log`.
- `ui/main_window.py` — `MainWindow`: дерево с ленивой загрузкой, правая панель
  (`QStackedWidget`), кэш секретов (TTL 120 с, `_invalidate_cache`), слой
  уведомлений (`info`/`warn`/`error`, таймауты `INFO_TIMEOUT_MS`/`WARN_TIMEOUT_MS`),
  автоочистка буфера обмена 30 с (счётчик не затирает статус), `closeEvent`
  чистит буфер, `disconnect_from_vault` очищает клиент/дерево/кэш/буфер,
  горячие клавиши (`Ctrl+F`, `Ctrl+C`, `Ctrl+Shift+Enter`, `Ctrl+Shift+R`).
- `ui/dialogs.py` — `ConfigDialog`, `SecretDialog`, `DeleteSecretDialog`;
  диалоги не показывают ошибки сами — возвращают результат/исключение наверх.
- `ui/search_dialog.py` — глобальный поиск (пути, опционально ключи/значения).
- `ui/widgets.py` — переиспользуемые виджеты.
- `tests/` — pytest + pytest-qt, offscreen.
- Дистрибуция: `build_appimage.sh` (AppImage), `vaultpass.nix` / `flake.nix`
  (Nix), `vaultpass.spec` (PyInstaller).

## Repos / branching

- `origin` → `Green-ya/VaultPass` (публичный, default `master`).
- `private` → `Green-ya/VaultPass-dev` (разработка, default `develop`).
- Вся работа — в `develop`; в `master` не пушить без явной команды владельца.

## Roadmap (sprint gates)

1. **v0.2.0 — UX и стабилизация** — DONE (30.10.2026, тег `v0.2.0`, `master` @
   `c9fd222`): единый слой уведомлений вместо `QMessageBox`, обработка ошибок +
   логирование, управление сессией (отключение, очистка кэша/буфера,
   `closeEvent`), UX и горячие клавиши, 114 тестов, CI pylint+pytest,
   README/ROADMAP в синхроне.
2. **Переключатель Secrets engines** — DONE (24.11.2026, develop @ `8afbc07`,
   приёмка владельцем на тестовом стенде пройдена): `set_mount_point`,
   `list_kv_mounts`, кнопка «Engine», `MountDialog`, сброс кэша/дерева/буфера.
   Ручная приёмка: подключение к стенду, переключение, работа с секретами —
   без замечаний, кроме бага переноса строки (см. спринт 3).
   ТЗ (для истории): смена mount point KV v2 без отключения/подключения.
3. **Windows-порт + стабилизация UI** — DONE (24.11.2026, develop @
   `334ab5f`, ручная приёмка владельца: exe работает, функционал на месте):
   перенос длинных ошибок, APPDATA-пути, chmod POSIX-only, тесты переключателя
   engines (9 шт.), CI windows-latest, сборка vaultpass.exe (PyInstaller).
   Релиз v0.3.0.
   Windows-порт:
   - Пути конфигов: `%APPDATA%\VaultPass` вместо `~/.config/vaultpass`
     (`config_manager.py`, `logging_setup.py`); миграция со старого пути.
   - `os.chmod(0o600/0o700)` — условное выполнение (POSIX-only); chmod-тесты
     пометить `skipif(sys.platform == "win32")` (4 теста падают на Windows
     именно на этих assert).
   - Сборка PyInstaller под Windows (`vaultpass.spec`) → `vaultpass.exe`;
     keyring на Windows использует Credential Manager — проверить вживую.
   - CI: добавить `windows-latest` в матрицу pytest.
   - AppImage и nix — Linux-only, без изменений.
   Стабилизация UI:
   - **Баг (найден при приёмке спринта 2):** текст ошибки подключения
     выводится одной строкой без переноса и растягивает окно на всю ширину.
     Нужен перенос/обрезка (`wordWrap`, фиксированная ширина, tooltip с полным
     текстом) — размер окна не должен меняться.
   - Дописать тесты переключателя engines (наследие спринта 2: переключение,
     инвалидация кэша/дерева, ошибочные ветки, ручной ввод mount).
   - Приёмка: `pytest -q` зелёный на Windows, exe собирается и запускается,
     подключение к тестовому Vault (`http://192.168.100.40:8200`) работает,
     длинные ошибки не растягивают окно.

## Current state / smoke

- v0.2.0 выпущена (30.10.2026); 114 тестов зелёные (offscreen), pylint 10.00/10.
- Smoke: `pytest -q` + ручной чек-лист: подключение → навигация → копирование
  (реальное значение) → создание/правка/удаление → отключение → повторное
  подключение.
- Контроль: значения секретов не попадают в лог и статусную строку.
- Backlog v0.3+ (фоновые операции, тёмная тема, история версий KV v2,
  импорт/экспорт и пр.) — в `ROADMAP.md`.
