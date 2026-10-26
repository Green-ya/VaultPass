import string

import pytest

from ui.dialogs import PASSWORD_SYMBOLS, generate_password


def test_default_password_length():
    assert len(generate_password()) == 24


@pytest.mark.parametrize("length", [8, 16, 64, 128])
def test_password_length(length):
    assert len(generate_password(length=length)) == length


def test_password_contains_selected_pools():
    password = generate_password(
        length=64,
        use_upper=True,
        use_lower=True,
        use_digits=True,
        use_symbols=True,
    )

    assert any(ch in string.ascii_uppercase for ch in password)
    assert any(ch in string.ascii_lowercase for ch in password)
    assert any(ch in string.digits for ch in password)
    assert any(ch in PASSWORD_SYMBOLS for ch in password)


def test_password_respects_disabled_pools():
    password = generate_password(
        length=64,
        use_upper=False,
        use_lower=True,
        use_digits=False,
        use_symbols=False,
    )

    assert all(ch in string.ascii_lowercase for ch in password)


def test_minimum_length_is_clamped_to_pool_count():
    password = generate_password(
        length=1,
        use_upper=True,
        use_lower=True,
        use_digits=True,
        use_symbols=True,
    )

    assert len(password) == 4


def test_no_pools_raises():
    with pytest.raises(ValueError):
        generate_password(
            use_upper=False,
            use_lower=False,
            use_digits=False,
            use_symbols=False,
        )


def test_passwords_are_not_identical():
    assert generate_password(length=32) != generate_password(length=32)
