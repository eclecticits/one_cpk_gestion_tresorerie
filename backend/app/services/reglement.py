"""Volets de règlement d'une réquisition.

Une réquisition peut mêler plusieurs modes de paiement — et plusieurs comptes
bancaires — d'une ligne à l'autre. Un « volet » est le regroupement des lignes
qui partagent le même couple (mode de paiement, compte bancaire) : c'est l'unité
qui sera autorisée puis payée, indépendamment des autres.

Le volet n'est pas une table. C'est une lecture des lignes, calculée ici pour
que la règle vive à un seul endroit plutôt que d'être réécrite dans chaque
endpoint qui en a besoin.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

# Modes acceptés sur une ligne ou sur un ordre : ce sont des modes exécutables,
# qui donnent lieu à un mouvement de trésorerie réel.
MODES_PAIEMENT = frozenset({"cash", "mobile_money", "virement", "card", "cheque"})

# Résumé porté par la réquisition quand ses lignes ne s'accordent pas. Ce n'est
# PAS un mode exécutable : il ne doit jamais atteindre un ordre de décaissement
# ni une sortie de fonds.
MODE_PAIEMENT_MIXTE = "mixte"

CANAL_CAISSE = "CAISSE"
CANAL_BANQUE = "BANQUE"


def normaliser_mode(mode: str | None) -> str:
    return (mode or "").strip().lower()


def canal_pour_mode(mode: str | None) -> str:
    """Canal de trésorerie d'où sort l'argent pour ce mode.

    Seul l'encaissement/décaissement en espèces passe par la caisse ; tout le
    reste transite par un compte. Règle reprise telle quelle du contrôle
    historique des sorties de fonds, pour ne pas requalifier l'existant.
    """
    return CANAL_CAISSE if normaliser_mode(mode) == "cash" else CANAL_BANQUE


@dataclass(frozen=True)
class VoletCle:
    """Identité d'un volet. C'est aussi ce qui identifie la sortie de fonds
    correspondante, qui porte déjà ces deux colonnes."""

    mode_paiement: str
    compte_bancaire_id: int | None

    @property
    def canal(self) -> str:
        return canal_pour_mode(self.mode_paiement)


@dataclass
class Volet:
    cle: VoletCle
    montant_total: Decimal = Decimal("0")
    lignes_ids: list[Any] = field(default_factory=list)

    @property
    def mode_paiement(self) -> str:
        return self.cle.mode_paiement

    @property
    def compte_bancaire_id(self) -> int | None:
        return self.cle.compte_bancaire_id

    @property
    def canal(self) -> str:
        return self.cle.canal

    def to_payload(self) -> dict[str, Any]:
        return {
            "mode_paiement": self.mode_paiement,
            "canal": self.canal,
            "compte_bancaire_id": self.compte_bancaire_id,
            "montant_total": self.montant_total,
            "lignes_ids": [str(lid) for lid in self.lignes_ids],
        }


def _cle_de_ligne(ligne: Any, mode_defaut: str) -> VoletCle:
    mode = normaliser_mode(getattr(ligne, "mode_paiement", None)) or normaliser_mode(mode_defaut)
    compte = getattr(ligne, "compte_bancaire_id", None)
    # Le compte n'a de sens que pour un volet bancaire : le neutraliser côté
    # caisse évite de scinder un volet espèces en deux à cause d'un résidu.
    if canal_pour_mode(mode) == CANAL_CAISSE:
        compte = None
    return VoletCle(mode_paiement=mode, compte_bancaire_id=compte)


def calculer_volets(lignes: Iterable[Any], *, mode_defaut: str = "cash") -> list[Volet]:
    """Regroupe les lignes par couple (mode, compte), en préservant l'ordre
    d'apparition pour que l'affichage reste stable d'un appel à l'autre."""
    volets: OrderedDict[VoletCle, Volet] = OrderedDict()
    for ligne in lignes:
        cle = _cle_de_ligne(ligne, mode_defaut)
        volet = volets.get(cle)
        if volet is None:
            volet = Volet(cle=cle)
            volets[cle] = volet
        volet.montant_total += Decimal(str(getattr(ligne, "montant_total", 0) or 0))
        ligne_id = getattr(ligne, "id", None)
        if ligne_id is not None:
            volet.lignes_ids.append(ligne_id)
    return list(volets.values())


def resume_mode_paiement(volets: list[Volet], *, defaut: str = "cash") -> str:
    """Valeur à porter sur la réquisition : le mode unique si les lignes
    s'accordent, `mixte` sinon.

    Deux volets qui partagent le mode mais visent des comptes bancaires
    différents ne rendent pas la réquisition « mixte » au sens du mode : elle
    reste `virement`. C'est bien un règlement en plusieurs volets, mais le mode
    affiché sur la pièce et dans les filtres reste juste.
    """
    if not volets:
        return normaliser_mode(defaut) or "cash"
    modes = {volet.mode_paiement for volet in volets}
    if len(modes) == 1:
        return next(iter(modes))
    return MODE_PAIEMENT_MIXTE


async def resoudre_compte_bancaire(
    compte_bancaire_id: int | None,
    *,
    mode_paiement: str | None,
    tenant_id: int,
    db: Any,
) -> int | None:
    """Valide le compte associé à un règlement et le renvoie normalisé.

    Règle unique, partagée par la réquisition, la ligne et l'ordre : un volet
    caisse n'a pas de compte, un volet bancaire en exige un, actif, du tenant et
    de type BANK.
    """
    from sqlalchemy import select

    from app.models.compte_bancaire import CompteBancaire

    # Import tardif : `fastapi` est déjà une dépendance du projet, mais le
    # module reste utilisable hors contexte HTTP pour les calculs purs.
    from fastapi import HTTPException, status

    mode = normaliser_mode(mode_paiement)
    if canal_pour_mode(mode) == CANAL_CAISSE:
        return None
    if mode == "virement" and compte_bancaire_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="compte_bancaire_id requis pour paiement bancaire",
        )
    # Modes bancaires sans compte désigné (mobile money, carte) : tolérés ici,
    # le compte est alors exigé au moment du paiement. Comportement historique
    # conservé pour ne pas invalider des réquisitions existantes.
    if compte_bancaire_id is None:
        return None

    res = await db.execute(
        select(CompteBancaire).where(
            CompteBancaire.id == compte_bancaire_id,
            CompteBancaire.organisation_id == tenant_id,
        )
    )
    compte = res.scalar_one_or_none()
    if compte is None or compte.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="compte_bancaire_id invalide"
        )
    if (compte.account_type or "BANK").upper() != "BANK":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="compte_bancaire_id invalide"
        )
    return compte_bancaire_id


def est_reglement_multi_volets(volets: list[Volet]) -> bool:
    """Un règlement en plusieurs volets impose le décaissement progressif : la
    caisse ne peut pas solder en un seul paiement ce qui sort de deux endroits
    différents."""
    return len(volets) > 1
