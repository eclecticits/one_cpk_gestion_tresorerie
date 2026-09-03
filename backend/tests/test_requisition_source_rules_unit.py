from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.ordre_decaissement import normaliser_cle_beneficiaire
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
    assert normaliser_cle_beneficiaire("  ACME   SARL  ") == "acme sarl"
    # Tabulation et saut de ligne comptent comme des blancs à réduire.
    assert normaliser_cle_beneficiaire("\tACME\nSARL ") == "acme sarl"
    # Espace INSÉCABLE (U+00A0) : c'est le cas qui séparait les deux
    # normalisations quand l'une était écrite en SQL — Postgres ne la voit pas
    # comme un blanc sous glibc. Une seule clé, calculée ici et stockée, la
    # ramène au même nom que « ACME SARL » et referme le contournement.
    assert normaliser_cle_beneficiaire("ACME\u00a0SARL") == "acme sarl"
    assert normaliser_cle_beneficiaire("\u00a0ACME\u00a0\u00a0SARL\u00a0") == "acme sarl"
    assert normaliser_cle_beneficiaire(None) == ""


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
        # Exigé pour cette nature (cf. test dédié) : sans lui la construction
        # échouerait, et ce test cesserait de porter sur la casse de la nature.
        beneficiaire="ACME SARL",
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


def test_requisition_hors_budget_exige_un_beneficiaire():
    # Hors budget : ni ligne ni poste. Le bénéficiaire est la seule pièce qui
    # dise à qui l'argent va, et la sortie de fonds en dérive le sien — sans
    # lui, le décaissement s'enregistrait sous un libellé de remplissage.
    with pytest.raises(ValidationError):
        RequisitionCreate(
            objet="Dépense urgente hors budget",
            mode_paiement="cash",
            type_requisition="classique",
            nature_requisition="HORS_BUDGET",
            montant_total=Decimal("80"),
            service_id=1,
        )
    # Un bénéficiaire fait de blancs ne compte pas : le validateur le rogne
    # d'abord, donc il ne désigne personne.
    with pytest.raises(ValidationError):
        RequisitionCreate(
            objet="Dépense urgente hors budget",
            mode_paiement="cash",
            type_requisition="classique",
            nature_requisition="HORS_BUDGET",
            montant_total=Decimal("80"),
            service_id=1,
            beneficiaire="   ",
        )
    req = RequisitionCreate(
        objet="Dépense urgente hors budget",
        mode_paiement="cash",
        type_requisition="classique",
        nature_requisition="HORS_BUDGET",
        montant_total=Decimal("80"),
        service_id=1,
        beneficiaire="  ACME SARL  ",
    )
    assert req.beneficiaire == "ACME SARL"


def test_requisition_budgetaire_et_fonds_tiers_nexigent_pas_de_beneficiaire():
    # Budgétaire : les lignes portent la dépense, le bénéficiaire reste
    # facultatif comme avant.
    assert RequisitionCreate(
        objet="Achat de fournitures",
        mode_paiement="cash",
        type_requisition="classique",
        nature_requisition="BUDGETAIRE",
        montant_total=Decimal("80"),
        service_id=1,
    ).beneficiaire is None
    # Fonds de tiers : le bénéficiaire EST le tiers créancier, déjà identifié
    # et imposé au paiement — l'exiger en plus n'ajouterait rien.
    assert RequisitionCreate(
        objet="Reversement au tiers",
        mode_paiement="cash",
        type_requisition="classique",
        nature_requisition="FONDS_DE_TIERS",
        montant_total=Decimal("80"),
        service_id=1,
        tiers_nom_libre="Tiers Créancier",
    ).beneficiaire is None
