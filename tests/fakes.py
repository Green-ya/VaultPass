"""Общие заглушки Vault-клиента для тестов.

Живут отдельно от конкретного тестового модуля, чтобы сценарии окна,
поиска и дерева могли переиспользовать одну и ту же модель Vault.
"""


class FakeClient:
    """Минимальная модель Vault KV v2 в памяти."""

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
    """``FakeClient`` с плоским каталогом на ``count`` секретов.

    Запоминает прочитанные пути, чтобы проверять ленивую загрузку.
    """

    def __init__(self, count):
        super().__init__()
        self.tree = {"": [f"secret-{i}" for i in range(count)]}
        self.reads = []

    def read_secret(self, path):
        self.reads.append(path)
        return super().read_secret(path)


class FakeKeyring:
    """Замена системного keyring: пароли лежат в памяти.

    ``working=False`` имитирует недоступный backend: запись падает, а
    чтение всегда возвращает ``None``.
    """

    def __init__(self, working=True):
        self.store = {}
        self.working = working

    def get_password(self, service, username):
        if not self.working:
            return None
        return self.store.get((service, username))

    def set_password(self, service, username, value):
        if not self.working:
            raise RuntimeError("keyring backend недоступен")
        self.store[(service, username)] = value
