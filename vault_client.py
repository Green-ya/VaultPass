import hvac
from hvac.exceptions import InvalidPath, VaultError


class VaultClientError(Exception):
    """Ошибка при работе с Vault."""


class VaultAuthError(VaultClientError):
    """Не удалось авторизоваться в Vault."""


class VaultClient:
    def __init__(self, url, token, mount_point="secret", verify=True, timeout=15):
        self.url = url
        self.token = token
        self.mount_point = mount_point
        self.client = hvac.Client(
            url=url,
            token=token,
            verify=verify,
            timeout=timeout,
        )
        self._check_connection()

    def _check_connection(self):
        try:
            authenticated = self.client.is_authenticated()
        except VaultError as e:
            raise VaultAuthError(f"Не удалось подключиться к Vault: {e}") from e
        except Exception as e:
            raise VaultAuthError(f"Не удалось подключиться к Vault: {e}") from e

        if not authenticated:
            raise VaultAuthError("Не удалось авторизоваться в Vault: проверьте токен")

    @staticmethod
    def _normalize(path: str) -> str:
        return (path or "").strip("/")

    def list_secrets(self, path=""):
        """Получить список секретов и папок по пути."""
        path = self._normalize(path)
        try:
            # Для KV v2 путь всегда заканчивается на /metadata/
            metadata_path = f"{path}/" if path else ""
            result = self.client.secrets.kv.v2.list_secrets(
                path=metadata_path,
                mount_point=self.mount_point,
            )
            return result.get("data", {}).get("keys", [])
        except InvalidPath:
            return []
        except VaultError as e:
            raise VaultClientError(f"Ошибка Vault: {e}") from e

    def iter_all_secrets(self, root=""):
        """Рекурсивно обходит все секреты, отдавая их полные пути."""
        root = self._normalize(root)
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
        """Прочитать секрет по пути."""
        path = self._normalize(path)
        try:
            result = self.client.secrets.kv.v2.read_secret(
                path=path,
                mount_point=self.mount_point,
            )
            return result.get("data", {}).get("data", {})
        except InvalidPath:
            return {}
        except VaultError as e:
            raise VaultClientError(f"Ошибка Vault: {e}") from e

    def create_secret(self, path, data):
        """Создать/обновить секрет."""
        path = self._normalize(path)
        if not path:
            raise VaultClientError("Путь к секрету не может быть пустым")
        try:
            self.client.secrets.kv.v2.create_or_update_secret(
                path=path,
                secret=data,
                mount_point=self.mount_point,
            )
            return True
        except VaultError as e:
            raise VaultClientError(f"Ошибка создания секрета: {e}") from e

    def delete_secret(self, path):
        """Удалить секрет и все его версии."""
        path = self._normalize(path)
        try:
            self.client.secrets.kv.v2.delete_metadata_and_all_versions(
                path=path,
                mount_point=self.mount_point,
            )
            return True
        except VaultError as e:
            raise VaultClientError(f"Ошибка удаления: {e}") from e
