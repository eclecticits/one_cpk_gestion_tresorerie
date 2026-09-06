from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_optional_email(value: str | None) -> str | None:
    """Tolère l'absence d'email (None / vide) mais valide le format si fourni.

    Évite d'enregistrer une adresse mal formée qui ferait échouer les reçus et
    relances par la suite.
    """
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    from email_validator import EmailNotValidError, validate_email

    try:
        return validate_email(cleaned, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise ValueError(f"Adresse email invalide : {exc}") from exc


def normalize_optional_sexe(value: str | None) -> str | None:
    """Ramène le sexe à 'M', 'F' ou rien.

    Le formulaire envoie déjà 'M' ou 'F', mais cette fonction est le seul point
    de passage pour les imports et les appels directs à l'API. On accepte donc
    aussi les formes longues et la minuscule, et on refuse le reste plutôt que
    de laisser filer une valeur que la contrainte de table rejettera de toute
    façon — l'erreur est alors lisible au lieu d'être une violation SQL.
    """
    if value is None:
        return None
    cleaned = value.strip().upper()
    if not cleaned:
        return None
    if cleaned in {"M", "MASCULIN", "H", "HOMME"}:
        return "M"
    if cleaned in {"F", "FEMININ", "FÉMININ", "FEMME"}:
        return "F"
    raise ValueError("Sexe invalide : attendu 'M' ou 'F'")


class ClientCreate(BaseModel):
    nom: str = Field(min_length=2, max_length=300)
    type_client: str | None = None
    email: str | None = Field(default=None, max_length=200)
    telephone: str | None = Field(default=None, max_length=50)
    sexe: str | None = Field(default=None, max_length=20)
    adresse: str | None = None
    notes: str | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        return _normalize_optional_email(v)

    @field_validator("sexe")
    @classmethod
    def _validate_sexe(cls, v: str | None) -> str | None:
        return normalize_optional_sexe(v)


class ClientUpdate(BaseModel):
    nom: str | None = Field(default=None, min_length=2, max_length=300)
    type_client: str | None = None
    email: str | None = Field(default=None, max_length=200)
    telephone: str | None = Field(default=None, max_length=50)
    sexe: str | None = Field(default=None, max_length=20)
    adresse: str | None = None
    notes: str | None = None
    active: bool | None = None

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        return _normalize_optional_email(v)

    @field_validator("sexe")
    @classmethod
    def _validate_sexe(cls, v: str | None) -> str | None:
        return normalize_optional_sexe(v)


class ClientOut(BaseModel):
    id: UUID
    nom: str
    type_client: str | None = None
    email: str | None = None
    telephone: str | None = None
    sexe: str | None = None
    adresse: str | None = None
    notes: str | None = None
    active: bool = True
    nb_encaissements: int | None = None
    dernier_encaissement: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
