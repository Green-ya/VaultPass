import hvac
from hvac.exceptions import InvalidPath, VaultError

class VaultClient:
    def __init__(self, url, token, mount_point="secret"):
        self.client = hvac.Client(url=url, token=token)
        self.mount_point = mount_point
        self._check_connection()
    
    def _check_connection(self):
        if not self.client.is_authenticated():
            raise ConnectionError("Не удалось авторизоваться в Vault")
    
    def list_secrets(self, path=""):
        """Получить список секретов и папок по пути"""
        try:
            # Для KV v2 путь всегда заканчивается на /metadata/
            metadata_path = f"{path.rstrip('/')}/" if path else ""
            result = self.client.secrets.kv.v2.list_secrets(
                path=metadata_path,
                mount_point=self.mount_point
            )
            return result.get("data", {}).get("keys", [])
        except InvalidPath:
            return []
        except VaultError as e:
            raise Exception(f"Ошибка Vault: {e}")
    
    def read_secret(self, path):
        """Прочитать секрет по пути"""
        try:
            result = self.client.secrets.kv.v2.read_secret(
                path=path,
                mount_point=self.mount_point
            )
            return result.get("data", {}).get("data", {})
        except InvalidPath:
            return {}
        except VaultError as e:
            raise Exception(f"Ошибка Vault: {e}")
    
    def create_secret(self, path, data):
        """Создать/обновить секрет"""
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point=self.mount_point
            )
            return True
        except VaultError as e:
            raise Exception(f"Ошибка создания секрета: {e}")
    
    def delete_secret(self, path):
        """Удалить секрет"""
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point=self.mount_point
            )
            return True
        except VaultError as e:
            raise Exception(f"Ошибка удаления: {e}")