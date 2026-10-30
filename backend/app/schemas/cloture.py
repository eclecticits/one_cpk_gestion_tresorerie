from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel
from uuid import UUID

from app.schemas.base import DecimalBaseModel
from app.schemas.denomination import DenominationOut


class BilletagePayload(BaseModel):
    usd: dict[str, int] = {}
    cdf: dict[str, int] = {}


class ClotureBalanceResponse(DecimalBaseModel):
    date_debut: datetime | None = None
    date_fin: datetime
    taux_change: Decimal = Decimal("1")
    solde_initial_usd: Decimal = Decimal("0")
    solde_initial_cdf: Decimal = Decimal("0")
    total_entrees_usd: Decimal = Decimal("0")
    total_entrees_cdf: Decimal = Decimal("0")
    total_sorties_usd: Decimal = Decimal("0")
    total_sorties_cdf: Decimal = Decimal("0")
    solde_theorique_usd: Decimal = Decimal("0")
    solde_theorique_cdf: Decimal = Decimal("0")
    # Détail des entrées : la caisse ne se remplit pas qu'avec des notes de
    # débit. Sans cette ventilation, un approvisionnement banque -> caisse est
    # noyé dans « Entrées » et le caissier ne peut pas rapprocher son total.
    entrees_encaissements_usd: Decimal = Decimal("0")
    entrees_encaissements_cdf: Decimal = Decimal("0")
    entrees_approvisionnements_usd: Decimal = Decimal("0")
    entrees_approvisionnements_cdf: Decimal = Decimal("0")
    entrees_transferts_usd: Decimal = Decimal("0")
    entrees_transferts_cdf: Decimal = Decimal("0")
    entrees_retours_usd: Decimal = Decimal("0")
    entrees_retours_cdf: Decimal = Decimal("0")
    # Lignes d'approvisionnement de la période (montants sérialisés en texte).
    approvisionnements: list[dict] = []
    # Les coupures sont renvoyées avec la balance : le caissier qui peut
    # clôturer n'a pas nécessairement accès au menu d'administration des
    # dénominations.
    denominations: list[DenominationOut] = []


class ClotureCreateRequest(BaseModel):
    solde_physique_usd: Decimal
    solde_physique_cdf: Decimal
    billetage_usd: dict[str, int] | None = None
    billetage_cdf: dict[str, int] | None = None
    # Compté hors des coupures configurées (pièces, petites coupures, billet
    # abîmé) : entre dans le total du billetage, à expliquer dans l'observation.
    autres_usd: Decimal = Decimal("0")
    autres_cdf: Decimal = Decimal("0")
    observation: str | None = None
    # Un écart constaté ne modifie le solde que si l'utilisateur demande sa
    # régularisation : elle crée alors un encaissement (excédent) ou une sortie
    # (déficit). À défaut, la clôture aboutit quand même et l'écart reste ouvert.
    regulariser_ecart: bool = False
    motif_regularisation: str | None = None


class EcartRegularisationRequest(BaseModel):
    """Régularisation, après coup, d'un écart laissé ouvert."""

    motif: str
    # Restreint la régularisation à une devise ; par défaut les deux sont traitées.
    devise: str | None = None


class OuvertureCreateRequest(BaseModel):
    solde_ouverture_usd: Decimal = Decimal("0")
    solde_ouverture_cdf: Decimal = Decimal("0")
    billetage_usd: dict[str, int] | None = None
    billetage_cdf: dict[str, int] | None = None
    observation: str | None = None
    regulariser_ecart: bool = False
    motif_regularisation: str | None = None


class OuvertureOut(DecimalBaseModel):
    id: int
    reference_numero: str
    date_ouverture: datetime
    caissier_id: UUID | None = None
    solde_ouverture_usd: Decimal
    solde_ouverture_cdf: Decimal
    solde_attendu_usd: Decimal = Decimal("0")
    solde_attendu_cdf: Decimal = Decimal("0")
    ecart_usd: Decimal = Decimal("0")
    ecart_cdf: Decimal = Decimal("0")
    billetage_usd: dict | None = None
    billetage_cdf: dict | None = None
    observation: str | None = None
    statut: str
    # Régularisations créées pour l'écart constaté, et messages d'échec le cas
    # échéant. Un échec n'empêche jamais l'ouverture : l'écart reste ouvert.
    regularisations: list[dict] = []
    regularisation_erreurs: list[str] = []


class ClotureOut(DecimalBaseModel):
    id: int
    reference_numero: str
    date_cloture: datetime
    date_debut: datetime | None = None
    caissier_id: UUID | None = None
    solde_initial_usd: Decimal
    solde_initial_cdf: Decimal
    total_entrees_usd: Decimal
    total_entrees_cdf: Decimal
    total_sorties_usd: Decimal
    total_sorties_cdf: Decimal
    solde_theorique_usd: Decimal
    solde_theorique_cdf: Decimal
    solde_physique_usd: Decimal
    solde_physique_cdf: Decimal
    ecart_usd: Decimal
    ecart_cdf: Decimal
    taux_change_applique: Decimal
    billetage_usd: dict | None = None
    billetage_cdf: dict | None = None
    observation: str | None = None
    pdf_path: str | None = None
    statut: str
    regularisations: list[dict] = []
    regularisation_erreurs: list[str] = []


class CloturePdfDetail(BaseModel):
    date: datetime | None = None
    reference_numero: str | None = None
    beneficiaire: str | None = None
    motif: str | None = None
    montant_paye: Decimal | None = None
    devise: str = "USD"


class CloturePdfEntree(BaseModel):
    date: datetime | None = None
    reference_numero: str | None = None
    nature: str
    tiers: str | None = None
    motif: str | None = None
    montant: Decimal = Decimal("0")
    devise: str = "USD"


class CloturePdfRegularisation(BaseModel):
    devise: str
    sens: str
    montant: Decimal
    motif: str | None = None


class CloturePdfData(DecimalBaseModel):
    cloture: ClotureOut
    caissier_nom: str | None = None
    entrees: list[CloturePdfEntree] = []
    # Les sorties de la période : le nom du champ reste celui du contrat existant.
    details: list[CloturePdfDetail]
    regularisations: list[CloturePdfRegularisation] = []
