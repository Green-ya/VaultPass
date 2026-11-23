from types import SimpleNamespace

import pytest
from hvac.exceptions import VaultError

from vault_client import (
    VaultAuthError,
    VaultClient,
    VaultClientError,
    VaultConnectionError,
)


def make_client_with_tree(tree):
    client = VaultClient.__new__(VaultClient)
    client.mount_point = "secret"
    client.list_secrets = lambda path="": tree.get(path, [])
    return client


class _FakeHvacClient:
    """Заглушка hvac.Client для проверки классификации ошибок."""

    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    def is_authenticated(self):
        if self._exc is not None:
            raise self._exc
        return self._result


def _client_with(check):
    client = VaultClient.__new__(VaultClient)
    client.url = "https://vault.local:8200"
    client.client = check
    return client


def test_normalize_path():
    assert VaultClient._normalize("/a/b/") == "a/b"
    assert VaultClient._normalize("a/b") == "a/b"
    assert VaultClient._normalize("") == ""
    assert VaultClient._normalize(None) == ""


def test_iter_all_secrets_recurses():
    client = make_client_with_tree(
        {
            "": ["app/", "root-secret"],
            "app/": ["db/", "api-key"],
            "app/db/": ["prod", "stage"],
        }
    )

    assert set(client.iter_all_secrets()) == {
        "root-secret",
        "app/api-key",
        "app/db/prod",
        "app/db/stage",
    }


def test_iter_all_secrets_from_subtree():
    client = make_client_with_tree(
        {
            "app/": ["db/", "api-key"],
            "app/db/": ["prod"],
        }
    )

    assert set(client.iter_all_secrets("app")) == {"app/api-key", "app/db/prod"}


def test_create_secret_rejects_empty_path():
    client = VaultClient.__new__(VaultClient)

    with pytest.raises(VaultClientError):
        client.create_secret("/", {"key": "value"})


def test_vault_error_classified_as_auth_error():
    client = _client_with(_FakeHvacClient(exc=VaultError("permission denied")))

    with pytest.raises(VaultAuthError):
        client._check_connection()


def test_network_error_classified_as_connection_error():
    client = _client_with(_FakeHvacClient(exc=OSError("connection refused")))

    with pytest.raises(VaultConnectionError):
        client._check_connection()


def test_unauthenticated_token_raises_auth_error():
    client = _client_with(_FakeHvacClient(result=False))

    with pytest.raises(VaultAuthError):
        client._check_connection()


def test_successful_check_does_not_raise():
    client = _client_with(_FakeHvacClient(result=True))

    client._check_connection()  # не должно бросить исключение


def test_connection_error_is_subclass_of_client_error():
    assert issubclass(VaultConnectionError, VaultClientError)
    assert issubclass(VaultAuthError, VaultClientError)


class _FakeSys:
    """Заглушка hvac.sys для list_mounted_secrets_engines."""

    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc

    def list_mounted_secrets_engines(self):
        if self._exc is not None:
            raise self._exc
        return self._result


def test_set_mount_point_switches_without_reconnect():
    client = VaultClient.__new__(VaultClient)
    client.mount_point = "secret"

    client.set_mount_point("kv2/")

    assert client.mount_point == "kv2"


def test_set_mount_point_rejects_empty():
    client = VaultClient.__new__(VaultClient)
    client.mount_point = "secret"

    with pytest.raises(VaultClientError, match="пустым"):
        client.set_mount_point("  /  ")


def test_list_kv_mounts_keeps_only_kv_v2_sorted():
    client = VaultClient.__new__(VaultClient)
    client.client = SimpleNamespace(
        sys=_FakeSys(
            result={
                "data": {
                    "secret/": {"type": "kv", "options": {"version": "2"}},
                    "old/": {"type": "kv", "options": {"version": "1"}},
                    "pki/": {"type": "pki"},
                    "kv2/": {"type": "kv", "options": {"version": 2}},
                }
            }
        )
    )

    assert client.list_kv_mounts() == ["kv2", "secret"]


def test_list_kv_mounts_raises_client_error_on_vault_failure():
    client = VaultClient.__new__(VaultClient)
    client.client = SimpleNamespace(sys=_FakeSys(exc=VaultError("permission denied")))

    with pytest.raises(VaultClientError, match="Vault"):
        client.list_kv_mounts()
