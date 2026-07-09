import os
import json
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

class ConfigManager:
    CONFIG_DIR = Path.home() / ".config" / "vault-manager"
    CONFIG_FILE = CONFIG_DIR / "config.enc"
    KEY_FILE = CONFIG_DIR / "key.bin"
    
    def __init__(self):
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._ensure_key()
        self.fernet = Fernet(self._load_key())
    
    def _ensure_key(self):
        """Создаём ключ, если его нет"""
        if not self.KEY_FILE.exists():
            # Генерируем случайный ключ
            key = Fernet.generate_key()
            with open(self.KEY_FILE, "wb") as f:
                f.write(key)
            # Устанавливаем права только для чтения владельцем
            os.chmod(self.KEY_FILE, 0o600)
    
    def _load_key(self):
        with open(self.KEY_FILE, "rb") as f:
            return f.read()
    
    def save_config(self, url: str, token: str, mount_point: str = "secret"):
        """Сохраняем зашифрованный конфиг"""
        data = {
            "url": url,
            "token": token,
            "mount_point": mount_point
        }
        json_str = json.dumps(data)
        encrypted = self.fernet.encrypt(json_str.encode())
        
        with open(self.CONFIG_FILE, "wb") as f:
            f.write(encrypted)
        os.chmod(self.CONFIG_FILE, 0o600)
    
    def load_config(self):
        """Загружаем расшифрованный конфиг"""
        if not self.CONFIG_FILE.exists():
            return None
        
        with open(self.CONFIG_FILE, "rb") as f:
            encrypted = f.read()
        
        try:
            decrypted = self.fernet.decrypt(encrypted)
            return json.loads(decrypted.decode())
        except Exception:
            return None
    
    def clear_config(self):
        """Удаляем конфиг"""
        if self.CONFIG_FILE.exists():
            self.CONFIG_FILE.unlink()