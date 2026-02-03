import pytest

from app.api.v1.endpoints.experts import _normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("(+243)829000113", "+243829000113"),
        ("+243829000113", "+243829000113"),
        ("0829000113", "+243829000113"),
        ("829000113", "+243829000113"),
    ],
)
def test_phone_examples(raw, expected):
    assert _normalize_phone(raw) == expected
