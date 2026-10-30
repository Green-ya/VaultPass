import json
import stat

import pytest
from cryptography.fernet import Fernet
from fakes import FakeKeyring

import config_manager as config_module
from config_manager import ConfigManager


def _patch_config_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(ConfigManager, "CONFIG_DIR", tmp_path / "vaultpass")
    monkeypatch.setattr(
        ConfigManager, "CONFIG_FILE", tmp_path / "vaultpass" / "config.enc"
    )
    monkeypatch.setattr(
        ConfigManager, "KEY_FILE", tmp_path / "vaultpass" / "key.bin"
    )
    monkeypatch.setattr(ConfigManager, "LEGACY_DIR", tmp_path / "legacy")


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "keyring", None)
    _patch_config_paths(tmp_path, monkeypatch)
    return ConfigManager()


def test_save_and_load_roundtrip(manager):
    manager.save_config("https://vault.example.com:8200", "hvs.token", "secret")

    loaded = manager.load_config()
    assert loaded == {
        "url": "https://vault.example.com:8200",
        "token": "hvs.token",
        "mount_point": "secret",
    }


def test_config_and_key_permissions(manager):
    manager.save_config("https://vault.local", "token")

    config_mode = stat.S_IMODE(manager.CONFIG_FILE.stat().st_mode)
    dir_mode = stat.S_IMODE(manager.CONFIG_DIR.stat().st_mode)

    assert config_mode == 0o600
    assert manager.KEY_FILE.exists()
    assert stat.S_IMODE(manager.KEY_FILE.stat().st_mode) == 0o600
    assert dir_mode == 0o700


def test_config_is_encrypted_on_disk(manager):
    manager.save_config("https://vault.local", "super-secret-token")

    raw = manager.CONFIG_FILE.read_bytes()
    assert b"super-secret-token" not in raw


def test_wrong_key_returns_none(manager):
    manager.save_config("https://vault.local", "token")

    # Подменяем ключ: расшифровать старый конфиг новым ключом нельзя
    manager.KEY_FILE.write_bytes(Fernet.generate_key())
    other = ConfigManager()

    assert other.load_config() is None


def test_clear_config(manager):
    manager.save_config("https://vault.local", "token")
    assert manager.has_config()

    manager.clear_config()

    assert not manager.has_config()
    assert manager.load_config() is None


def test_legacy_config_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "keyring", None)

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    key = Fernet.generate_key()
    (legacy_dir / "key.bin").write_bytes(key)
    payload = {
        "url": "https://old-vault.local",
        "token": "old-token",
        "mount_point": "kv",
    }
    (legacy_dir / "config.enc").write_bytes(
        Fernet(key).encrypt(json.dumps(payload).encode())
    )

    monkeypatch.setattr(ConfigManager, "CONFIG_DIR", tmp_path / "vaultpass")
    monkeypatch.setattr(
        ConfigManager, "CONFIG_FILE", tmp_path / "vaultpass" / "config.enc"
    )
    monkeypatch.setattr(
        ConfigManager, "KEY_FILE", tmp_path / "vaultpass" / "key.bin"
    )
    monkeypatch.setattr(ConfigManager, "LEGACY_DIR", legacy_dir)

    manager = ConfigManager()

    assert manager.load_config() == payload
    assert manager.CONFIG_FILE.exists()


def test_key_is_stored_in_keyring_when_available(tmp_path, monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(config_module, "keyring", fake)
    _patch_config_paths(tmp_path, monkeypatch)

    manager = ConfigManager()
    manager.save_config("https://vault.local", "token")

    # Ключ ушёл в keyring, файловый дублёр не создаётся
    assert not manager.KEY_FILE.exists()
    assert fake.store[(ConfigManager.KEYRING_SERVICE, ConfigManager.KEYRING_USERNAME)]
    assert manager.load_config()["token"] == "token"


def test_key_from_keyring_survives_restart(tmp_path, monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(config_module, "keyring", fake)
    _patch_config_paths(tmp_path, monkeypatch)

    ConfigManager().save_config("https://vault.local", "token")

    # Новый экземпляр читает ключ только из keyring и расшифровывает конфиг
    restarted = ConfigManager()
    assert restarted.load_config() == {
        "url": "https://vault.local",
        "token": "token",
        "mount_point": "secret",
    }


def test_key_falls_back_to_file_when_keyring_broken(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "keyring", FakeKeyring(working=False))
    _patch_config_paths(tmp_path, monkeypatch)

    manager = ConfigManager()
    manager.save_config("https://vault.local", "token")

    # backend сломан — ключ сохранён в файл с правами 0600
    assert manager.KEY_FILE.exists()
    assert stat.S_IMODE(manager.KEY_FILE.stat().st_mode) == 0o600
    assert manager.load_config()["token"] == "token"


def test_legacy_key_migrates_into_keyring(tmp_path, monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(config_module, "keyring", fake)

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    key = Fernet.generate_key()
    (legacy_dir / "key.bin").write_bytes(key)
    payload = {
        "url": "https://old-vault.local",
        "token": "old-token",
        "mount_point": "kv",
    }
    (legacy_dir / "config.enc").write_bytes(
        Fernet(key).encrypt(json.dumps(payload).encode())
    )

    _patch_config_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(ConfigManager, "LEGACY_DIR", legacy_dir)

    manager = ConfigManager()

    # При миграции ключ уехал в keyring, а не в файл
    stored = fake.store[(ConfigManager.KEYRING_SERVICE, ConfigManager.KEYRING_USERNAME)]
    assert stored.encode() == key
    assert not manager.KEY_FILE.exists()
    assert manager.load_config() == payload
