import json
import os
import shutil
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

try:  # Системное хранилище секретов (GNOME Keyring, KWallet, macOS Keychain...)
    import keyring
except Exception:  # pragma: no cover - keyring необязателен
    keyring = None


class ConfigManager:
    """Хранение настроек подключения к Vault.

    Токен шифруется Fernet-ключом. Ключ по возможности хранится в системном
    keyring, а если он недоступен — в отдельном файле с правами 0600.
    Старый каталог ``~/.config/vault-manager`` автоматически мигрирует.
    """

    CONFIG_DIR = Path.home() / ".config" / "vaultpass"
    CONFIG_FILE = CONFIG_DIR / "config.enc"
    KEY_FILE = CONFIG_DIR / "key.bin"

    LEGACY_DIR = Path.home() / ".config" / "vault-manager"

    KEYRING_SERVICE = "vaultpass"
    KEYRING_USERNAME = "config-key"

    def __init__(self):
        self._ensure_config_dir()
        self._migrate_legacy()
        self.fernet = Fernet(self._load_or_create_key())

    # ------------------------------------------------------------------
    # Каталог и права доступа
    # ------------------------------------------------------------------
    def _ensure_config_dir(self):
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        # Каталог доступен только владельцу
        os.chmod(self.CONFIG_DIR, 0o700)

    def _migrate_legacy(self):
        """Переносим конфиг из старого каталога, если он ещё используется."""
        if not self.LEGACY_DIR.exists() or self.CONFIG_FILE.exists():
            return

        legacy_config = self.LEGACY_DIR / "config.enc"
        legacy_key = self.LEGACY_DIR / "key.bin"
        if not legacy_config.exists():
            return

        try:
            if legacy_key.exists():
                key = legacy_key.read_bytes().strip()
                if not self._keyring_set(key):
                    self._write_key_file(key)

            shutil.copy2(legacy_config, self.CONFIG_FILE)
            os.chmod(self.CONFIG_FILE, 0o600)
        except OSError:
            # Миграция не критична: при ошибке просто останемся без конфига.
            return

    # ------------------------------------------------------------------
    # Ключ шифрования
    # ------------------------------------------------------------------
    def _keyring_get(self):
        if keyring is None:
            return None
        try:
            value = keyring.get_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME)
        except Exception:
            return None
        if not value:
            return None
        return value.encode() if isinstance(value, str) else value

    def _keyring_set(self, key: bytes) -> bool:
        """Сохраняем ключ в keyring. Возвращает False, если backend недоступен."""
        if keyring is None:
            return False
        try:
            value = key.decode() if isinstance(key, bytes) else key
            keyring.set_password(self.KEYRING_SERVICE, self.KEYRING_USERNAME, value)
            # Проверяем, что backend действительно сохранил значение
            stored = keyring.get_password(
                self.KEYRING_SERVICE, self.KEYRING_USERNAME
            )
            return stored == value
        except Exception:
            return False

    def _write_key_file(self, key: bytes):
        tmp_path = self.KEY_FILE.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(key)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.KEY_FILE)

    def _load_or_create_key(self) -> bytes:
        keyring_key = self._keyring_get()
        file_key = None
        if self.KEY_FILE.exists():
            try:
                file_key = self.KEY_FILE.read_bytes().strip()
            except OSError:
                file_key = None

        # Если конфиг уже есть, выбираем тот ключ, которым он реально
        # расшифровывается (например, после появления keyring).
        if self.CONFIG_FILE.exists():
            for candidate in (file_key, keyring_key):
                if candidate and self._can_decrypt(candidate):
                    if not self._keyring_set(candidate):
                        self._write_key_file(candidate)
                    return candidate

        key = keyring_key or file_key
        if key is None:
            key = Fernet.generate_key()

        if not self._keyring_set(key):
            self._write_key_file(key)

        return key

    def _can_decrypt(self, key: bytes) -> bool:
        try:
            Fernet(key).decrypt(self.CONFIG_FILE.read_bytes())
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------
    def save_config(self, url: str, token: str, mount_point: str = "secret"):
        """Сохраняем зашифрованный конфиг."""
        data = {
            "url": url,
            "token": token,
            "mount_point": mount_point,
        }
        encrypted = self.fernet.encrypt(json.dumps(data).encode())

        tmp_path = self.CONFIG_FILE.with_suffix(".tmp")
        with open(tmp_path, "wb") as f:
            f.write(encrypted)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.CONFIG_FILE)

    def load_config(self):
        """Загружаем расшифрованный конфиг или None."""
        if not self.CONFIG_FILE.exists():
            return None

        try:
            encrypted = self.CONFIG_FILE.read_bytes()
            decrypted = self.fernet.decrypt(encrypted)
            config = json.loads(decrypted.decode())
        except (OSError, InvalidToken, ValueError, json.JSONDecodeError):
            return None

        if not isinstance(config, dict):
            return None
        return config

    def has_config(self) -> bool:
        return self.CONFIG_FILE.exists()

    def clear_config(self):
        """Удаляем конфиг (ключ оставляем, чтобы не ломать будущие записи)."""
        if self.CONFIG_FILE.exists():
            self.CONFIG_FILE.unlink()
