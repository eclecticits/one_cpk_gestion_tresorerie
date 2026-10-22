import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.admin import _normalize_user_phone


def test_numero_national_ou_international_stocke_normalise():
    assert _normalize_user_phone("0810 123 456") == "243810123456"
    assert _normalize_user_phone("+243 810-123-456") == "243810123456"


def test_champ_vide_retire_le_numero():
    assert _normalize_user_phone("") is None
    assert _normalize_user_phone("   ") is None
    assert _normalize_user_phone(None) is None


def test_numero_inexploitable_refuse():
    with pytest.raises(HTTPException) as exc:
        _normalize_user_phone("12")
    assert exc.value.status_code == 400


def test_le_sexe_est_exige_a_la_creation():
    from pydantic import ValidationError

    from app.schemas.admin import UserCreateRequest

    base = {"email": "a@b.cd", "nom": "MUKENDI", "prenom": "Jean"}
    assert UserCreateRequest(**base, sexe="F").sexe == "F"
    with pytest.raises(ValidationError):
        UserCreateRequest(**base)
    with pytest.raises(ValidationError):
        UserCreateRequest(**base, sexe="X")
