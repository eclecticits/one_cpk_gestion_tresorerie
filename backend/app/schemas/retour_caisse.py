from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import UserInfo


class RetourCaisseCreate(DecimalBaseModel):
    """Enregistre un retour en caisse rattaché à une sortie de fonds.

    Seuls ``sortie_fonds_id`` et ``montant`` sont requis : le canal, la devise,
    le compte bancaire et le poste budgétaire sont hérités de la sortie
    d'origine s'ils ne sont pas fournis.
    """

    sortie_fonds_id: UUID
    montant: Decimal = Field(gt=0)
    type_retour: Literal["reliquat_avance", "correction", "trop_percu"] = "reliquat_avance"
    # Hérités de la sortie d'origine si omis.
    devise: Literal["USD", "CDF"] | None = None
    canal: Literal["CAISSE", "BANQUE"] | None = None
    compte_bancaire_id: int | None = None
    budget_poste_id: int | None = None
    ajuste_budget: bool = True
    mode: str = "cash"
    reference: str | None = None
    motif: str | None = None
    commentaire: str | None = None
    piece_justificative: str | None = None
    date_retour: datetime | str | None = None


class RetourCaisseOut(DecimalBaseModel):
    id: UUID
    organisation_id: int
    sortie_fonds_id: UUID
    requisition_id: UUID | None = None
    type_retour: str
    budget_poste_id: int | None = None
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    ajuste_budget: bool = True
    service_id: int | None = None
    montant: Decimal
    devise: Literal["USD", "CDF"] = "USD"
    canal: Literal["CAISSE", "BANQUE"] = "CAISSE"
    compte_bancaire_id: int | None = None
    mode: str = "cash"
    reference: str | None = None
    reference_numero: str | None = None
    motif: str | None = None
    commentaire: str | None = None
    piece_justificative: str | None = None
    exchange_rate_snapshot: Decimal | None = None
    date_retour: datetime
    statut: str = "VALIDE"
    statut_comptabilisation: str = "NON_COMPTABILISEE"
    message_comptabilisation: str | None = None
    motif_annulation: str | None = None
    annulee_le: datetime | None = None
    annulee_par_id: UUID | None = None
    ancien_statut: str | None = None
    created_by: UUID | None = None
    created_by_user: UserInfo | None = None
    created_at: datetime


class RetoursCaisseListResponse(DecimalBaseModel):
    items: list[RetourCaisseOut]
    total: int
    total_montant: Decimal = Decimal("0")
    # Renseignés uniquement lorsque la liste est filtrée sur une sortie de fonds
    # (permet d'afficher le reliquat encore à justifier).
    sortie_montant_paye: Decimal | None = None
    total_retourne: Decimal | None = None
    reste_a_justifier: Decimal | None = None


class RetourCaisseStatusUpdate(DecimalBaseModel):
    statut: str
    motif_annulation: str | None = None
