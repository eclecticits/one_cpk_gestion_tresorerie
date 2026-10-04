"""Un import Excel de notes de débit d'experts-comptables.

La feuille porte une ligne par membre et une colonne par libellé (« Cotisation
2026 », « Pénalité AG », « Arriérés »…). Chaque ligne devient une note de débit
— un encaissement non payé —, chaque colonne non vide une ligne de cette note.

L'import garde la trace de ce qu'il a lu : le fichier, les colonnes retenues et
leur poste, les montants. Les notes, elles, renvoient à leur import par
`Encaissement.note_debit_import_id` : c'est ce qui permet de retrouver « les
notes du fichier de mars » sans fouiller les libellés.

Contrairement à `imports_history` (référentiel national des experts, sans
organisation), un import de notes appartient à un conseil : les créances sont
celles de son organisation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NoteDebitImport(Base):
    __tablename__ = "notes_debit_imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    fichier: Mapped[str] = mapped_column(String(300), nullable=False)
    nb_notes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Lignes du fichier écartées (erreur, doublon ignoré) : ce que l'import n'a
    #: PAS créé se lit aussi, sinon un total plus bas que la feuille resterait
    #: inexpliqué.
    nb_lignes_ecartees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    montant_total: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    montant_arrieres: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False, default=0)
    #: Colonnes retenues : libellé, poste d'imputation, total.
    colonnes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    service_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("services.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
