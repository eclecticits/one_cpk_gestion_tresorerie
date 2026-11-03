"""La date future est refusée à la saisie, jamais à la lecture.

Une recette à identifier est datée à midi UTC du jour de valeur. Créée le matin,
elle est « dans le futur » jusqu'à midi : la relire ne doit pas échouer, sinon
toute la liste des encaissements tombe en erreur 500.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.payment import EncaissementCreate, EncaissementResponse


def _demain() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=3)


_CHAMPS = {
    "type_client": "autre",
    "libelle": "Recette à identifier",
    "montant": Decimal("10"),
    "montant_total": Decimal("10"),
}


def test_la_saisie_refuse_une_date_future():
    with pytest.raises(ValidationError, match="dans le futur"):
        EncaissementCreate(
            **_CHAMPS,
            date_encaissement=_demain(),
        )


def test_la_lecture_accepte_une_date_future_deja_enregistree():
    reponse = EncaissementResponse(
        id=uuid4(),
        **_CHAMPS,
        date_encaissement=_demain(),
        created_at=datetime.now(timezone.utc),
    )
    assert reponse.date_encaissement > datetime.now(timezone.utc)


def test_une_date_sans_fuseau_est_lue_en_utc():
    reponse = EncaissementResponse(
        id=uuid4(),
        **_CHAMPS,
        date_encaissement=datetime(2026, 1, 15, 8, 30),
        created_at=datetime.now(timezone.utc),
    )
    assert reponse.date_encaissement.tzinfo == timezone.utc
