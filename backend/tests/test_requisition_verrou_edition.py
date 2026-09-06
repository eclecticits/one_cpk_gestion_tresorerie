"""Ce qui fige une réquisition, et ce qui la laisse amendable.

Deux verrous, et ils ne disent pas la même chose :

- le **visa d'examen**, quand l'examen fait partie du circuit figé sur la
  pièce : à partir de là, seul l'examinateur qui a visé peut encore reprendre
  le texte — c'est son visa qui en répond ;
- la **première validation** : dès qu'elle est passée, la pièce est
  `AUTORISEE` (visa attendu) ou `APPROUVEE` (circuit fini), et plus rien ne se
  modifie.

Restent amendables : un examen rejeté, un examen hors circuit, et une pièce
rejetée après validation — c'est précisément à ces moments-là qu'on corrige.
"""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.historical_snapshots import (
    ensure_requisition_editable,
    is_requisition_locked_for_edit,
    requisition_lock_reason,
)


EXAMINATEUR = uuid.uuid4()
AUTRE_UTILISATEUR = uuid.uuid4()


def _user(user_id):
    return SimpleNamespace(id=user_id)


def _req(**kwargs):
    base = {
        "status": "EN_ATTENTE",
        "examen_status": "NON_EXAMINE",
        "examen_par": EXAMINATEUR,
        "montant_total": 1000,
        "workflow_snapshot": {
            "preset": "complet",
            "steps": {
                "signature_service": {"enabled": True},
                "examen": {"enabled": True},
                "validation_1": {"enabled": True},
                "validation_2": {"enabled": True},
            },
        },
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _sans_examen(**kwargs):
    return _req(
        workflow_snapshot={
            "preset": "express",
            "steps": {
                "signature_service": {"enabled": False},
                "examen": {"enabled": False},
                "validation_1": {"enabled": True},
                "validation_2": {"enabled": False},
            },
        },
        **kwargs,
    )


def test_piece_en_attente_non_examinee_reste_amendable():
    assert requisition_lock_reason(_req()) is None
    assert is_requisition_locked_for_edit(_req()) is False


def test_visa_examen_fige_la_piece():
    reason = requisition_lock_reason(_req(examen_status="EXAMINE"))
    assert reason is not None
    assert "examen" in reason


def test_examen_rejete_laisse_corriger():
    assert requisition_lock_reason(_req(examen_status="REJETE")) is None


def test_examen_hors_circuit_ne_fige_rien():
    # Le statut d'examen peut traîner d'un ancien circuit : ce qui compte est
    # le circuit figé sur la pièce, pas la valeur résiduelle de la colonne.
    assert requisition_lock_reason(_sans_examen(examen_status="EXAMINE")) is None


@pytest.mark.parametrize("statut", ["AUTORISEE", "APPROUVEE", "PAYEE", "SIGNEE", "EN_DECAISSEMENT"])
def test_premiere_validation_fige_la_piece(statut):
    # AUTORISEE est l'état d'une pièce validée une fois et en attente du visa :
    # elle est déjà hors de portée du rédacteur.
    reason = requisition_lock_reason(_req(status=statut, examen_status="EXAMINE"))
    assert reason is not None
    assert statut in reason


def test_piece_rejetee_apres_validation_redevient_amendable():
    # Le rejet renvoie la pièce au rédacteur ; la figer ici l'enfermerait dans
    # un texte qu'on vient justement de lui demander de reprendre.
    assert requisition_lock_reason(_sans_examen(status="REJETEE")) is None


def test_le_refus_nomme_le_motif_et_les_champs():
    with pytest.raises(HTTPException) as exc:
        ensure_requisition_editable(
            _req(status="AUTORISEE"),
            attempted_fields={"montant_total", "objet"},
        )

    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert "AUTORISEE" in detail
    assert "montant_total, objet" in detail


def test_apres_examen_seul_l_examinateur_modifie():
    vise = _req(examen_status="EXAMINE")

    assert requisition_lock_reason(vise, user=_user(EXAMINATEUR)) is None
    assert requisition_lock_reason(vise, user=_user(AUTRE_UTILISATEUR)) is not None
    # Sans utilisateur (appel interne), on reste du côté sûr : c'est fermé.
    assert requisition_lock_reason(vise) is not None


def test_examinateur_inconnu_ne_rouvre_rien():
    # Donnée ancienne : visée, mais sans trace de qui a visé. Personne ne passe.
    vise = _req(examen_status="EXAMINE", examen_par=None)
    assert requisition_lock_reason(vise, user=_user(EXAMINATEUR)) is not None


def test_la_validation_ferme_aussi_a_l_examinateur():
    # Passée en validation, la pièce est sortie du circuit d'examen : le visa
    # ne donne plus aucun droit dessus.
    validee = _req(status="AUTORISEE", examen_status="EXAMINE")
    assert requisition_lock_reason(validee, user=_user(EXAMINATEUR)) is not None
