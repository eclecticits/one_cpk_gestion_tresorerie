import pytest

from app.core.security import validate_password_strength


@pytest.mark.parametrize(
    "password",
    [
        "Abcdefg1",
        "XyZ12345",
        "MotDePasse9",
    ],
)
def test_validate_password_strength_accepts_strong(password: str) -> None:
    validate_password_strength(password)


@pytest.mark.parametrize(
    "password, expected",
    [
        ("short1A", "8 caractères"),
        ("password1", "majuscule"),
        ("Password", "chiffre"),
    ],
)
def test_validate_password_strength_rejects_weak(password: str, expected: str) -> None:
    with pytest.raises(ValueError) as exc:
        validate_password_strength(password)
    assert expected in str(exc.value)
