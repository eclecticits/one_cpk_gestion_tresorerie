from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.base import DecimalBaseModel
from app.schemas.requisition import RequisitionOut, RequisitionWithUserOut, UserInfo
from uuid import UUID


class SortieFondsCreate(DecimalBaseModel):
    type_sortie: str
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    requisition_id: UUID | None = None
    ordre_decaissement_id: UUID | None = None
    rubrique_code: str | None = None
    budget_poste_id: int | None = None
    service_id: int | None = None
    montant_paye: Decimal = Field(gt=0)
    date_paiement: datetime | str | None = None
    mode_paiement: str
    reference: str | None = None
    devise: Literal["USD", "CDF"] = "USD"
    canal: Literal["CAISSE", "BANQUE"] = "CAISSE"
    compte_bancaire_id: int | None = None
    statut: str | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    created_by: UUID | None = None


class SortieFondsDraftCreate(DecimalBaseModel):
    type_sortie: str = "requisition"
    requisition_id: UUID | None = None
    ordre_decaissement_id: UUID | None = None
    rubrique_code: str | None = None
    budget_poste_id: int | None = None
    service_id: int | None = None
    montant_paye: Decimal = Field(default=Decimal("0"), ge=0)
    date_paiement: datetime | str | None = None
    mode_paiement: str = "cash"
    reference: str | None = None
    devise: Literal["USD", "CDF"] = "USD"
    canal: Literal["CAISSE", "BANQUE"] = "CAISSE"
    compte_bancaire_id: int | None = None
    motif: str | None = None
    beneficiaire: str | None = None
    piece_justificative: str | None = None
    commentaire: str | None = None


class SortieFondsOut(DecimalBaseModel):
    id: UUID
    type_sortie: str
    requisition_id: UUID | None = None
    rubrique_code: str | None = None
    budget_poste_id: int | None = None
    budget_poste_code: str | None = None
    budget_poste_libelle: str | None = None
    service_id: int | None = None
    montant_paye: Decimal
    date_paiement: datetime | None = None
    mode_paiement: str
    reference: str | None = None
    devise: Literal["USD", "CDF"] = "USD"
    canal: Literal["CAISSE", "BANQUE"] = "CAISSE"
    compte_bancaire_id: int | None = None
    reference_numero: str | None = None
    idempotency_key: str | None = None
    pdf_path: str | None = None
    #: Table d'où vient la ligne : `legacy` (`sorties_fonds`) ou
    #: `transfert_interne` (moteur dédié). Même vocabulaire que les lignes
    #: d'entrées internes. L'écran en a besoin pour savoir que « annuler » veut
    #: dire « contre-passer » de ce côté-là, et qu'aucune fenêtre de 30 minutes
    #: ne s'y applique — l'opération n'y réécrit jamais le passé.
    origine: Literal["legacy", "transfert_interne"] = "legacy"
    statut: str
    statut_comptabilisation: str = "NON_COMPTABILISEE"
    message_comptabilisation: str | None = None
    motif_annulation: str | None = None
    annulee_le: datetime | None = None
    annulee_par_id: UUID | None = None
    annulation_ip: str | None = None
    ancien_statut: str | None = None
    exchange_rate_snapshot: Decimal | None = None
    motif: str
    beneficiaire: str
    piece_justificative: str | None = None
    commentaire: str | None = None
    annexes: list[str] | None = None
    created_by: UUID | None = None
    created_by_user: UserInfo | None = None
    programme_par_id: UUID | None = None
    programme_par_user: UserInfo | None = None
    annulee_par_user: UserInfo | None = None
    created_at: datetime
    requisition: RequisitionWithUserOut | RequisitionOut | None = None
    is_reconciled: bool = False
    reconciled_at: datetime | None = None
    reconciled_by_id: UUID | None = None
    bank_statement_ref: str | None = None


class SortiesFondsListResponse(DecimalBaseModel):
    items: list[SortieFondsOut]
    total: int
    total_montant_paye: Decimal = Decimal("0")
    # Détail du total : vraies dépenses vs transferts internes caisse <-> banque.
    total_depenses_reelles: Decimal = Decimal("0")
    total_transferts_internes: Decimal = Decimal("0")
    # Retours en caisse de la période (reliquats rendus) et dépense nette qui en
    # découle : total_depenses_nettes = total_depenses_reelles - total_retours_caisse.
    # Attention : l'export Excel des sorties, lui, déduit les retours du total
    # GÉNÉRAL (transferts internes compris), son pied de colonne vaut donc
    # total_montant_paye - total_retours_caisse, et non total_depenses_nettes.
    total_retours_caisse: Decimal = Decimal("0")
    total_depenses_nettes: Decimal = Decimal("0")


class SortieFondsStatusUpdate(DecimalBaseModel):
    statut: str
    motif_annulation: str | None = None


class SortieFondsPaymentRejectPayload(DecimalBaseModel):
    motif_rejet: str
