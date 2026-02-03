import pytest

from app.api.v1.endpoints.experts import _normalize_phone, _normalize_email, _is_valid_email


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(+243)829000113", "+243829000113"),
        ("+243829000113", "+243829000113"),
        ("0829000113", "+243829000113"),
        ("829000113", "+243829000113"),
        ("243829000113", "+243829000113"),
        ("", None),
        (None, None),
        ("abcd", None),
    ],
)
def test_normalize_phone(raw, expected):
    assert _normalize_phone(raw if raw is not None else "") == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (" Test@Email.COM ", "test@email.com"),
        ("", None),
        ("   ", None),
    ],
)
def test_normalize_email(raw, expected):
    assert _normalize_email(raw) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("user@example.com", True),
        ("bad-email", False),
        ("user@", False),
        ("@example.com", False),
    ],
)
def test_is_valid_email(value, expected):
    assert _is_valid_email(value) is expected
