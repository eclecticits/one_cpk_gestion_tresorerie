from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.ordres_decaissement import _normaliser_cle_fractionnement
from app.api.v1.endpoints.sorties_fonds import _nature_sortie_depuis_requisition
from app.schemas.requisition import RequisitionCreate


def test_nature_sortie_est_derivee_de_la_requisition():
    assert (
        _nature_sortie_depuis_requisition(
            SimpleNamespace(type_requisition="classique", nature_requisition="BUDGETAIRE")
        )
        == "BUDGETAIRE"
    )
    assert (
        _nature_sortie_depuis_requisition(
            SimpleNamespace(type_requisition="classique", nature_requisition="HORS_BUDGET")
        )
        == "HORS_BUDGET_A_REGULARISER"
    )
    assert (
        _nature_sortie_depuis_requisition(
            SimpleNamespace(type_requisition="classique", nature_requisition="FONDS_DE_TIERS")
        )
        == "FONDS_DE_TIERS"
    )
    assert (
        _nature_sortie_depuis_requisition(
            SimpleNamespace(type_requisition="remboursement_transport", nature_requisition="FONDS_DE_TIERS")
        )
        == "BUDGETAIRE"
    )


def test_requisition_fonds_tiers_exige_identite_tiers():
    with pytest.raises(ValidationError):
        RequisitionCreate(
            objet="Reversement fonds tiers",
            mode_paiement="cash",
            type_requisition="classique",
            nature_requisition="FONDS_DE_TIERS",
            montant_total=Decimal("75"),
            service_id=1,
        )


def test_fractionnement_direct_normalise_beneficiaire_de_maniere_deterministe():
    assert _normaliser_cle_fractionnement("  ACME   SARL  ") == "acme sarl"


def test_motif_snapshot_retient_le_premier_candidat_non_vide():
    from app.api.v1.endpoints.sorties_fonds import _motif_snapshot

    assert _motif_snapshot(None, "Objet réquisition", defaut="Repli") == "Objet réquisition"
    assert _motif_snapshot("Première tranche", "Objet", defaut="Repli") == "Première tranche"
    # `sorties_fonds.motif` est NOT NULL : un candidat vide ou blanc ne doit
    # jamais atteindre l'INSERT, sous peine de 500 au lieu d'un refus propre.
    assert _motif_snapshot(None, "   ", defaut="Repli") == "Repli"
    assert _motif_snapshot(defaut="Repli") == "Repli"


def test_requisition_hors_budget_accepte_une_nature_en_minuscules():
    # La normalisation doit agir AVANT la validation du Literal, sinon elle est
    # inopérante et « hors_budget » est rejeté à tort.
    req = RequisitionCreate(
        objet="Dépense urgente",
        mode_paiement="cash",
        type_requisition="classique",
        nature_requisition="hors_budget",
        montant_total=Decimal("120"),
        service_id=1,
    )
    assert req.nature_requisition == "HORS_BUDGET"
    # Une nature non budgétaire n'emporte aucune identité de tiers.
    assert req.tiers_organisation_id is None
    assert req.tiers_nom_libre is None


def test_requisition_fonds_tiers_refuse_les_deux_identites_a_la_fois():
    with pytest.raises(ValidationError):
        RequisitionCreate(
            objet="Reversement",
            mode_paiement="virement",
            type_requisition="classique",
            nature_requisition="FONDS_DE_TIERS",
            montant_total=Decimal("75"),
            service_id=1,
            tiers_organisation_id=2,
            tiers_nom_libre="Tiers hors référentiel",
        )
