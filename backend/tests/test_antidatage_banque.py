"""Le caissier antidate un encaissement sur banque, jusqu'à un mois en arrière.

La caisse reste au jour ; le super administrateur garde son antidatage libre ;
les autres profils restent à l'horloge du serveur.
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.horodatage import resoudre_date_operation, un_mois_avant


def _user(role: str) -> SimpleNamespace:
    return SimpleNamespace(role=role)


def _il_y_a(jours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=jours)


def test_le_caissier_antidate_un_encaissement_banque():
    valeur = _il_y_a(10)
    resultat = resoudre_date_operation(
        valeur, user=_user("caissier"), champ="date_encaissement", canal="BANQUE"
    )
    assert resultat == valeur


def test_le_caissier_peut_remonter_d_un_mois_jour_pour_jour():
    aujourd_hui = datetime.now(timezone.utc).date()
    limite = un_mois_avant(aujourd_hui)
    valeur = datetime(limite.year, limite.month, limite.day, 10, 0, tzinfo=timezone.utc)
    resultat = resoudre_date_operation(
        valeur, user=_user("caissier"), champ="date_encaissement", canal="banque"
    )
    assert resultat == valeur


def test_au_dela_d_un_mois_la_date_est_refusee():
    with pytest.raises(HTTPException) as erreur:
        resoudre_date_operation(
            _il_y_a(40), user=_user("caissier"), champ="date_encaissement", canal="BANQUE"
        )
    assert erreur.value.status_code == 403
    assert "au plus tôt" in erreur.value.detail


def test_une_date_future_reste_refusee_sur_banque():
    with pytest.raises(HTTPException):
        resoudre_date_operation(
            datetime.now(timezone.utc) + timedelta(days=2),
            user=_user("caissier"),
            champ="date_encaissement",
            canal="BANQUE",
        )


def test_la_caisse_reste_au_jour_pour_le_caissier():
    with pytest.raises(HTTPException):
        resoudre_date_operation(
            _il_y_a(3), user=_user("caissier"), champ="date_encaissement", canal="CAISSE"
        )


@pytest.mark.parametrize("role", ["admin", "comptable", "tresorier", "rapporteur"])
def test_les_autres_profils_ne_peuvent_pas_antidater_la_banque(role):
    with pytest.raises(HTTPException):
        resoudre_date_operation(
            _il_y_a(3), user=_user(role), champ="date_encaissement", canal="BANQUE"
        )


def test_le_jour_meme_l_heure_du_serveur_s_impose():
    resultat = resoudre_date_operation(
        datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        user=_user("caissier"),
        champ="date_encaissement",
        canal="BANQUE",
    )
    assert datetime.now(timezone.utc) - resultat < timedelta(seconds=5)


def test_le_super_administrateur_garde_l_antidatage_libre():
    valeur = _il_y_a(120)
    resultat = resoudre_date_operation(
        valeur, user=_user("super_admin"), champ="date_encaissement", canal="CAISSE"
    )
    assert resultat == valeur


@pytest.mark.parametrize(
    ("jour", "attendu"),
    [
        (date(2026, 11, 3), date(2026, 10, 3)),
        (date(2026, 3, 31), date(2026, 2, 28)),
        (date(2028, 3, 31), date(2028, 2, 29)),
        (date(2026, 1, 15), date(2025, 12, 15)),
        (date(2026, 12, 31), date(2026, 11, 30)),
    ],
)
def test_un_mois_avant(jour, attendu):
    assert un_mois_avant(jour) == attendu
