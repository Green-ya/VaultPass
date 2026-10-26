import pytest

from vault_client import VaultClient, VaultClientError


def make_client_with_tree(tree):
    client = VaultClient.__new__(VaultClient)
    client.mount_point = "secret"
    client.list_secrets = lambda path="": tree.get(path, [])
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
