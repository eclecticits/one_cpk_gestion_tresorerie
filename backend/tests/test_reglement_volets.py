"""Découpage d'une réquisition en volets de règlement.

Une réquisition peut mêler plusieurs modes de paiement — et plusieurs comptes
bancaires — d'une ligne à l'autre. Le volet est le regroupement des lignes
partageant le même couple (mode, compte) : c'est l'unité qui sera autorisée puis
payée indépendamment des autres.

Ces tests portent sur la règle pure, sans base : ils fixent le contrat que le
reste de la chaîne (ordres de décaissement, sorties de fonds) tient pour acquis.
"""

from decimal import Decimal

import pytest

from app.services.reglement import (
    CANAL_BANQUE,
    CANAL_CAISSE,
    MODE_PAIEMENT_MIXTE,
    calculer_volets,
    canal_pour_mode,
    est_reglement_multi_volets,
    resume_mode_paiement,
)


class _Ligne:
    """Double minimal d'une LigneRequisition : le calcul ne lit que ces champs."""

    def __init__(self, ligne_id, mode, compte, montant):
        self.id = ligne_id
        self.mode_paiement = mode
        self.compte_bancaire_id = compte
        self.montant_total = Decimal(str(montant))


def test_lignes_homogenes_donnent_un_seul_volet():
    volets = calculer_volets(
        [_Ligne(1, "cash", None, "10"), _Ligne(2, "cash", None, "20")]
    )

    assert len(volets) == 1
    assert volets[0].montant_total == Decimal("30")
    assert volets[0].canal == CANAL_CAISSE
    assert resume_mode_paiement(volets) == "cash"
    assert est_reglement_multi_volets(volets) is False


def test_modes_differents_donnent_un_reglement_mixte():
    volets = calculer_volets(
        [
            _Ligne(1, "cash", None, "100"),
            _Ligne(2, "virement", 7, "250"),
            _Ligne(3, "cash", None, "25"),
        ]
    )

    assert len(volets) == 2
    caisse, banque = volets
    # Les lignes non contiguës du même volet sont bien regroupées.
    assert caisse.montant_total == Decimal("125")
    assert caisse.lignes_ids == [1, 3]
    assert banque.montant_total == Decimal("250")
    assert banque.canal == CANAL_BANQUE
    assert resume_mode_paiement(volets) == MODE_PAIEMENT_MIXTE
    assert est_reglement_multi_volets(volets) is True


def test_deux_comptes_bancaires_font_deux_volets_sans_rendre_le_mode_mixte():
    """Une dépense réglée depuis deux banques reste un virement.

    C'est bien un règlement en plusieurs volets — donc à décaissement
    progressif — mais le mode affiché sur la pièce et dans les filtres doit
    rester juste : « virement », pas « mixte ».
    """
    volets = calculer_volets(
        [_Ligne(1, "virement", 7, "10"), _Ligne(2, "virement", 9, "20")]
    )

    assert len(volets) == 2
    assert {v.compte_bancaire_id for v in volets} == {7, 9}
    assert resume_mode_paiement(volets) == "virement"
    assert est_reglement_multi_volets(volets) is True


def test_compte_residuel_sur_une_ligne_caisse_ne_scinde_pas_le_volet():
    """Un compte laissé sur une ligne repassée en caisse ne doit pas créer un
    second volet espèces : le compte n'a de sens que côté banque."""
    volets = calculer_volets(
        [_Ligne(1, "cash", 7, "10"), _Ligne(2, "cash", None, "20")]
    )

    assert len(volets) == 1
    assert volets[0].compte_bancaire_id is None
    assert volets[0].montant_total == Decimal("30")


def test_ligne_sans_mode_herite_du_mode_par_defaut():
    volets = calculer_volets([_Ligne(1, None, None, "10")], mode_defaut="virement")

    assert volets[0].mode_paiement == "virement"
    assert volets[0].canal == CANAL_BANQUE


def test_requisition_sans_ligne_conserve_son_mode():
    assert calculer_volets([]) == []
    assert resume_mode_paiement([], defaut="virement") == "virement"


@pytest.mark.parametrize(
    "mode,canal_attendu",
    [
        ("cash", CANAL_CAISSE),
        ("CASH", CANAL_CAISSE),
        ("virement", CANAL_BANQUE),
        ("mobile_money", CANAL_BANQUE),
        ("cheque", CANAL_BANQUE),
    ],
)
def test_canal_derive_du_mode(mode, canal_attendu):
    assert canal_pour_mode(mode) == canal_attendu


def test_mixte_n_est_pas_un_mode_executable():
    """Garde-fou : `mixte` résume une pièce, il ne doit jamais désigner un
    mouvement de trésorerie. Un ordre ou une sortie qui le porterait serait
    impayable — on vérifie qu'il reste hors de la liste des modes."""
    from app.services.reglement import MODES_PAIEMENT

    assert MODE_PAIEMENT_MIXTE not in MODES_PAIEMENT
