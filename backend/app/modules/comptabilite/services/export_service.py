"""Exports comptables stricts et traçables.

Le fichier logiciel est volontairement construit côté serveur : les contrôles,
les types Excel et l'historique ne peuvent ainsi pas être contournés par une
version ancienne du navigateur.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException, status
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.mouvement_budget_imputation import MouvementBudgetImputation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.modules.comptabilite.models import (
    ComptaCompte,
    ComptaEcriture,
    ComptaExportEcriture,
    ComptaExportHistorique,
    ComptaMappingCompteBancaire,
    ComptaMappingPosteBudgetaire,
    ComptaMappingRubrique,
    ComptaSociete,
    RUBRIQUE_VIREMENTS_INTERNES,
)
from app.modules.comptabilite.schemas.exports import (
    ExportAnomalieOut,
    ExportComptableApercuOut,
    ExportComptableFiltres,
    ExportLigneApercuOut,
)
from app.schemas.reports import ReportJournalLine, ReportJournalResponse


CENT = Decimal("0.01")
STATUTS_EXPORTABLES = ("VALIDEE", "CLOTUREE")
ENTETE_LOGICIEL = ("Date>", "Pièce", "Compte", "Libellé", "Débit", "Crédit")
# Limites du logiciel comptable cible (ACD CDWCompta) : au-delà, il tronque à
# l'import sans prévenir. Le fichier n'est pas tronqué ici — couper un libellé
# est un choix de rédaction — mais le comptable est prévenu avant l'export.
LONGUEUR_LIBELLE_LOGICIEL = 50
LONGUEUR_PIECE_LOGICIEL = 16
ENTETE_CONTROLE = (
    "Date d'opération",
    "Date de valeur",
    "Référence",
    "Bénéficiaire ou payeur",
    "Libellé",
    "Débit",
    "Crédit",
    "Solde",
)


def _q(value: Decimal | int | float | None) -> Decimal:
    return Decimal(value or 0).quantize(CENT, rounding=ROUND_HALF_UP)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@dataclass(slots=True)
class SelectionComptable:
    apercu: ExportComptableApercuOut
    lignes_export: list[ExportLigneApercuOut]
    ecritures: list[ComptaEcriture]
    comptes: dict[int, ComptaCompte]
    empreinte: str
    premier_export_id: UUID | None


async def _journaux_a_lire(
    db: AsyncSession, *, organisation_id: int, filtres: ExportComptableFiltres
) -> list[tuple[str, int | None]]:
    """Les journaux de trésorerie couverts par la sélection : la caisse, et
    chaque compte bancaire actif de la devise (ou le seul demandé)."""
    journaux: list[tuple[str, int | None]] = []
    if filtres.journal in ("CAISSE", "TOUS"):
        journaux.append(("CAISSE", None))
    if filtres.journal in ("BANQUE", "TOUS"):
        if filtres.compte_bancaire_id is not None:
            journaux.append(("BANQUE", filtres.compte_bancaire_id))
        else:
            ids = (
                await db.execute(
                    select(CompteBancaire.id)
                    .where(
                        CompteBancaire.organisation_id == organisation_id,
                        CompteBancaire.account_type == "BANK",
                        CompteBancaire.is_active.is_(True),
                        CompteBancaire.devise == filtres.devise,
                    )
                    .order_by(CompteBancaire.id)
                )
            ).scalars().all()
            journaux.extend(("BANQUE", compte_id) for compte_id in ids)
    return journaux


class _Comptes:
    """Numéros de compte résolus par les mappings, mis en cache.

    Un mapping absent ne bloque pas l'export : le numéro reste vide, et une
    anomalie non bloquante le signale au comptable.
    """

    def __init__(self, db: AsyncSession, organisation_id: int) -> None:
        self.db = db
        self.organisation_id = organisation_id
        self._postes: dict[int, str] = {}
        self._tresorerie: dict[int | None, str] = {}
        self._rubriques: dict[str, str] = {}

    async def poste(self, budget_poste_id: int | None) -> str:
        if budget_poste_id is None:
            return ""
        if budget_poste_id not in self._postes:
            numero = (
                await self.db.execute(
                    select(ComptaCompte.numero)
                    .join(ComptaMappingPosteBudgetaire, ComptaMappingPosteBudgetaire.compte_id == ComptaCompte.id)
                    .where(
                        ComptaMappingPosteBudgetaire.organisation_id == self.organisation_id,
                        ComptaMappingPosteBudgetaire.budget_poste_id == budget_poste_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            self._postes[budget_poste_id] = (numero or "").strip()
        return self._postes[budget_poste_id]

    async def tresorerie(self, compte_bancaire_id: int | None) -> str:
        """Compte de la banque mappée, ou de la caisse unique quand l'identifiant est absent."""
        if compte_bancaire_id not in self._tresorerie:
            if compte_bancaire_id is not None:
                numero = (
                    await self.db.execute(
                        select(ComptaCompte.numero)
                        .join(ComptaMappingCompteBancaire, ComptaMappingCompteBancaire.compte_id == ComptaCompte.id)
                        .where(
                            ComptaMappingCompteBancaire.organisation_id == self.organisation_id,
                            ComptaMappingCompteBancaire.compte_bancaire_id == compte_bancaire_id,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
            else:
                numero = (
                    await self.db.execute(
                        select(ComptaCompte.numero)
                        .join(ComptaSociete, ComptaSociete.compte_caisse_defaut_id == ComptaCompte.id)
                        .where(ComptaSociete.organisation_id == self.organisation_id)
                        .order_by(ComptaSociete.id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
            self._tresorerie[compte_bancaire_id] = (numero or "").strip()
        return self._tresorerie[compte_bancaire_id]

    async def rubrique(self, code: str) -> str:
        if code not in self._rubriques:
            numero = (
                await self.db.execute(
                    select(ComptaCompte.numero)
                    .join(ComptaMappingRubrique, ComptaMappingRubrique.compte_id == ComptaCompte.id)
                    .where(
                        ComptaMappingRubrique.organisation_id == self.organisation_id,
                        ComptaMappingRubrique.code_rubrique == code,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            self._rubriques[code] = (numero or "").strip()
        return self._rubriques[code]


async def _postes_des_operations(
    db: AsyncSession, *, organisation_id: int, lignes: list[ReportJournalLine]
) -> dict[tuple[str, str], list[tuple[int, Decimal]]]:
    """Poste(s) budgétaire(s) de chaque opération du journal.

    Le poste porté par l'opération d'abord ; à défaut, ses imputations
    budgétaires actives (une sortie multi-postes en a plusieurs, chacune avec
    son montant). Un retour reprend le poste de la sortie d'origine.
    """
    ids: dict[str, set[UUID]] = {"ENCAISSEMENT": set(), "SORTIE": set(), "RETOUR": set()}
    for ligne in lignes:
        if ligne.transaction_id and ligne.type_operation in ids:
            ids[ligne.type_operation].add(ligne.transaction_id)

    postes: dict[tuple[str, str], list[tuple[int, Decimal]]] = {}
    if ids["ENCAISSEMENT"]:
        for enc_id, poste_id in (
            await db.execute(
                select(Encaissement.id, Encaissement.budget_poste_id).where(
                    Encaissement.organisation_id == organisation_id,
                    Encaissement.id.in_(ids["ENCAISSEMENT"]),
                    Encaissement.budget_poste_id.is_not(None),
                )
            )
        ).all():
            postes[("ENCAISSEMENT", str(enc_id))] = [(poste_id, Decimal("0"))]
    if ids["SORTIE"]:
        for sortie_id, poste_id in (
            await db.execute(
                select(SortieFonds.id, SortieFonds.budget_poste_id).where(
                    SortieFonds.organisation_id == organisation_id,
                    SortieFonds.id.in_(ids["SORTIE"]),
                    SortieFonds.budget_poste_id.is_not(None),
                )
            )
        ).all():
            postes[("SORTIE", str(sortie_id))] = [(poste_id, Decimal("0"))]
    if ids["RETOUR"]:
        for retour_id, poste_id in (
            await db.execute(
                select(RetourCaisse.id, func.coalesce(RetourCaisse.budget_poste_id, SortieFonds.budget_poste_id))
                .join(SortieFonds, SortieFonds.id == RetourCaisse.sortie_fonds_id)
                .where(
                    RetourCaisse.organisation_id == organisation_id,
                    RetourCaisse.id.in_(ids["RETOUR"]),
                )
            )
        ).all():
            if poste_id is not None:
                postes[("RETOUR", str(retour_id))] = [(poste_id, Decimal("0"))]

    # Sans poste sur l'opération : ses imputations actives, poste par poste.
    colonnes = {
        "ENCAISSEMENT": MouvementBudgetImputation.encaissement_id,
        "SORTIE": MouvementBudgetImputation.sortie_fonds_id,
        "RETOUR": MouvementBudgetImputation.retour_caisse_id,
    }
    for type_operation, colonne in colonnes.items():
        restants = {i for i in ids[type_operation] if (type_operation, str(i)) not in postes}
        if not restants:
            continue
        rows = (
            await db.execute(
                select(colonne, MouvementBudgetImputation.budget_poste_id, func.sum(MouvementBudgetImputation.montant_mouvement))
                .where(
                    MouvementBudgetImputation.organisation_id == organisation_id,
                    MouvementBudgetImputation.statut == "ACTIVE",
                    colonne.in_(restants),
                )
                .group_by(colonne, MouvementBudgetImputation.budget_poste_id)
                .order_by(colonne, MouvementBudgetImputation.budget_poste_id)
            )
        ).all()
        for operation_id, poste_id, montant in rows:
            postes.setdefault((type_operation, str(operation_id)), []).append((poste_id, _q(montant)))
    return postes


async def preparer_export_comptable(
    db: AsyncSession,
    *,
    organisation_id: int,
    filtres: ExportComptableFiltres,
    user=None,
) -> SelectionComptable:
    """Construit l'export pour le logiciel comptable à partir de la trésorerie.

    Même source que le journal de contrôle : chaque mouvement du journal de
    trésorerie de la période (caisse, banques) donne deux lignes, la
    trésorerie et sa contrepartie. Les montants sont ceux de la trésorerie ;
    les numéros de compte viennent des mappings (poste budgétaire, compte
    bancaire, caisse, rubrique des virements internes). Un numéro introuvable
    reste vide, de même qu'une pièce sans numéro : rien ne bloque l'export,
    les anomalies non bloquantes disent où compléter.
    """
    # Import local : le module des rapports importe déjà la comptabilité.
    from app.api.v1.endpoints.reports import journal_tresorerie

    if filtres.compte_bancaire_id is not None:
        compte = (
            await db.execute(
                select(CompteBancaire).where(
                    CompteBancaire.id == filtres.compte_bancaire_id,
                    CompteBancaire.organisation_id == organisation_id,
                    CompteBancaire.account_type == "BANK",
                    CompteBancaire.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if compte is None:
            raise HTTPException(status_code=400, detail="Compte bancaire introuvable ou inactif.")
        if compte.devise != filtres.devise:
            raise HTTPException(
                status_code=400,
                detail=f"Le compte bancaire est tenu en {compte.devise}, pas en {filtres.devise}.",
            )

    comptes = _Comptes(db, organisation_id)
    mouvements: list[tuple[str, int | None, ReportJournalLine]] = []
    for canal, compte_bancaire_id in await _journaux_a_lire(db, organisation_id=organisation_id, filtres=filtres):
        journal = await journal_tresorerie(
            canal=canal,
            devise=filtres.devise,
            compte_bancaire_id=compte_bancaire_id,
            date_debut=filtres.date_debut.isoformat(),
            date_fin=filtres.date_fin.isoformat(),
            user=user,
            db=db,
            tenant_id=organisation_id,
        )
        mouvements.extend((canal, compte_bancaire_id, ligne) for ligne in journal.lignes)
    mouvements.sort(key=lambda item: (_jour(item[2].date), item[2].reference or "", item[0], item[1] or 0))

    postes = await _postes_des_operations(
        db, organisation_id=organisation_id, lignes=[ligne for *_, ligne in mouvements]
    )

    anomalies: list[ExportAnomalieOut] = []
    apercu_lignes: list[ExportLigneApercuOut] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")

    if not mouvements:
        anomalies.append(
            ExportAnomalieOut(
                code="AUCUN_MOUVEMENT",
                message="Aucun mouvement de trésorerie ne correspond à cette sélection.",
            )
        )

    for canal, compte_bancaire_id, mouvement in mouvements:
        entree = _q(mouvement.entree)
        sortie = _q(mouvement.sortie)
        montant = entree or sortie
        if montant <= 0:
            continue
        jour = _jour(mouvement.date)
        piece = (mouvement.reference or "").strip()
        libelle = (mouvement.libelle or "").strip()
        operation = str(mouvement.transaction_id) if mouvement.transaction_id else None
        reperes = piece or f"{jour:%d/%m/%Y} · {libelle[:40]}"
        if len(libelle) > LONGUEUR_LIBELLE_LOGICIEL:
            anomalies.append(
                ExportAnomalieOut(
                    code="LIBELLE_TROP_LONG",
                    message=(
                        f"Libellé de {len(libelle)} caractères : le logiciel comptable n'en garde que "
                        f"{LONGUEUR_LIBELLE_LOGICIEL} (« {libelle[:LONGUEUR_LIBELLE_LOGICIEL]} »)."
                    ),
                    bloquante=False,
                    numero=reperes,
                )
            )
        if len(piece) > LONGUEUR_PIECE_LOGICIEL:
            anomalies.append(
                ExportAnomalieOut(
                    code="PIECE_TROP_LONGUE",
                    message=(
                        f"Numéro de pièce de {len(piece)} caractères : le logiciel comptable n'en garde que "
                        f"{LONGUEUR_PIECE_LOGICIEL}."
                    ),
                    bloquante=False,
                    numero=reperes,
                )
            )

        compte_tresorerie = await comptes.tresorerie(compte_bancaire_id)
        # Contrepartie : le poste budgétaire de l'opération ; pour un mouvement
        # entre la caisse et une banque, le compte des virements internes, qui
        # se solde quand les deux côtés sont passés (pas de double comptage).
        if mouvement.type_operation in ("APPROVISIONNEMENT", "VERSEMENT", "TRANSFERT_ENTREE", "TRANSFERT_SORTIE") or (
            mouvement.transaction_type == "TRANSFERT"
        ):
            contreparties = [(await comptes.rubrique(RUBRIQUE_VIREMENTS_INTERNES), montant)]
        else:
            imputations = postes.get((mouvement.type_operation or "", operation or ""), [])
            if len(imputations) == 1:
                contreparties = [(await comptes.poste(imputations[0][0]), montant)]
            elif imputations and sum((m for _, m in imputations), Decimal("0")) == montant:
                contreparties = [(await comptes.poste(poste_id), m) for poste_id, m in imputations]
            else:
                contreparties = [("", montant)]

        # Entrée : la trésorerie au débit, la contrepartie au crédit ; une
        # sortie, l'inverse.
        tresorerie_au_debit = entree > 0
        lignes_mouvement = [(compte_tresorerie, montant if tresorerie_au_debit else Decimal("0"), Decimal("0") if tresorerie_au_debit else montant)]
        lignes_mouvement.extend(
            (numero, Decimal("0") if tresorerie_au_debit else m, m if tresorerie_au_debit else Decimal("0"))
            for numero, m in contreparties
        )

        for numero, debit, credit in lignes_mouvement:
            if not numero:
                anomalies.append(
                    ExportAnomalieOut(
                        code="COMPTE_VIDE",
                        message="Aucun compte comptable n'est associé à ce mouvement : la colonne Compte reste vide.",
                        bloquante=False,
                        numero=reperes,
                    )
                )
            elif not numero.isdigit() or numero.startswith("0") or len(numero) > 15:
                anomalies.append(
                    ExportAnomalieOut(
                        code="COMPTE_NON_REPRESENTABLE",
                        message=f"Le compte « {numero} » ne s'écrit pas comme un nombre Excel : il est repris tel quel.",
                        bloquante=False,
                        numero=reperes,
                    )
                )
            total_debit += debit
            total_credit += credit
            apercu_lignes.append(
                ExportLigneApercuOut(
                    operation_id=operation,
                    date=jour,
                    piece=piece,
                    compte=numero,
                    libelle=libelle,
                    debit=debit,
                    credit=credit,
                )
            )

    total_debit = _q(total_debit)
    total_credit = _q(total_credit)
    ecart = _q(total_debit - total_credit)
    nombre_operations = sum(1 for *_, m in mouvements if _q(m.entree) or _q(m.sortie))

    empreinte_payload = {
        "source": "TRESORERIE",
        "organisation_id": organisation_id,
        "date_debut": filtres.date_debut.isoformat(),
        "date_fin": filtres.date_fin.isoformat(),
        "journal": filtres.journal,
        "compte_bancaire_id": filtres.compte_bancaire_id,
        "devise": filtres.devise,
        "lignes": [
            (l.date.isoformat(), l.piece, l.compte, l.libelle, str(l.debit), str(l.credit), l.operation_id)
            for l in apercu_lignes
        ],
    }
    empreinte = _sha256(json.dumps(empreinte_payload, sort_keys=True).encode("utf-8"))
    exact_export = (
        await db.execute(
            select(ComptaExportHistorique.id)
            .where(
                ComptaExportHistorique.organisation_id == organisation_id,
                ComptaExportHistorique.type_export == "LOGICIEL_COMPTABLE",
                ComptaExportHistorique.empreinte_selection == empreinte,
            )
            .order_by(ComptaExportHistorique.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if exact_export is not None:
        anomalies.insert(
            0,
            ExportAnomalieOut(
                code="DEJA_EXPORTEE",
                message=f"Cette sélection, à l'identique, figure déjà dans l'export {exact_export}.",
                bloquante=not filtres.autoriser_reexport,
            ),
        )

    apercu = ExportComptableApercuOut(
        date_debut=filtres.date_debut,
        date_fin=filtres.date_fin,
        journal=filtres.journal,
        compte_bancaire_id=filtres.compte_bancaire_id,
        devise=filtres.devise,
        nombre_ecritures=nombre_operations,
        nombre_lignes=len(apercu_lignes),
        total_debit=total_debit,
        total_credit=total_credit,
        ecart=ecart,
        equilibre=ecart == 0,
        exportable=bool(apercu_lignes) and not any(a.bloquante for a in anomalies),
        nombre_deja_exportees=nombre_operations if exact_export is not None else 0,
        lignes=apercu_lignes[:500],
        anomalies=anomalies,
    )
    return SelectionComptable(
        apercu=apercu,
        lignes_export=apercu_lignes,
        ecritures=[],
        comptes={},
        empreinte=empreinte,
        premier_export_id=exact_export,
    )


def creer_xlsx_logiciel(lignes: list[ExportLigneApercuOut]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Journal"
    ws.freeze_panes = "A2"
    remplissage = PatternFill("solid", fgColor="1F4E78")
    for col, valeur in enumerate(ENTETE_LOGICIEL, start=1):
        cellule = ws.cell(1, col, valeur)
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = remplissage
        cellule.alignment = Alignment(horizontal="center")
    for row, ligne in enumerate(lignes, start=2):
        ws.cell(row, 1, datetime.combine(ligne.date, datetime.min.time())).number_format = "mm-dd-yy"
        ws.cell(row, 2, ligne.piece)
        # Un compte numérique part en nombre, comme le modèle l'exige ; un
        # compte absent laisse la cellule vide.
        if ligne.compte.isdigit() and not ligne.compte.startswith("0") and len(ligne.compte) <= 15:
            ws.cell(row, 3, int(ligne.compte)).number_format = "0"
        elif ligne.compte:
            ws.cell(row, 3, ligne.compte)
        ws.cell(row, 4, ligne.libelle)
        if ligne.debit:
            ws.cell(row, 5, float(ligne.debit)).number_format = "0.00"
        if ligne.credit:
            ws.cell(row, 6, float(ligne.credit)).number_format = "0.00"
    for index, largeur in enumerate((13, 24, 18, 72, 16, 16), start=1):
        ws.column_dimensions[get_column_letter(index)].width = largeur
    wb.properties.title = "Import comptable ONEC Smart"
    wb.properties.creator = "ONEC Smart"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _jour(value: datetime | date) -> date:
    """Le jour d'un mouvement, tel que le journal l'affiche.

    Les dates de trésorerie sont stockées avec fuseau horaire, qu'Excel refuse
    (openpyxl lève une TypeError à l'enregistrement) : on n'en garde que le jour.
    """
    return value.date() if isinstance(value, datetime) else value


def creer_controle_bancaire(journal: ReportJournalResponse, format_sortie: str) -> bytes:
    rows = [
        (
            _jour(ligne.date),
            None,
            ligne.reference or "",
            ligne.tiers or "",
            ligne.libelle or "",
            _q(ligne.sortie),
            _q(ligne.entree),
            _q(ligne.solde),
        )
        for ligne in journal.lignes
    ]
    if format_sortie == "CSV":
        text_buffer = io.StringIO(newline="")
        writer = csv.writer(text_buffer, delimiter=";")
        writer.writerow(ENTETE_CONTROLE)
        for row in rows:
            writer.writerow(
                [
                    row[0].isoformat(),
                    "",
                    row[2], row[3], row[4],
                    f"{row[5]:.2f}" if row[5] else "",
                    f"{row[6]:.2f}" if row[6] else "",
                    f"{row[7]:.2f}",
                ]
            )
        return ("\ufeff" + text_buffer.getvalue()).encode("utf-8")

    wb = Workbook()
    ws = wb.active
    ws.title = "Contrôle bancaire"
    ws.freeze_panes = "A2"
    for col, valeur in enumerate(ENTETE_CONTROLE, start=1):
        cellule = ws.cell(1, col, valeur)
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = PatternFill("solid", fgColor="1F4E78")
        cellule.alignment = Alignment(horizontal="center")
    for row_index, row in enumerate(rows, start=2):
        ws.cell(row_index, 1, row[0]).number_format = "dd/mm/yyyy"
        ws.cell(row_index, 2, row[1]).number_format = "dd/mm/yyyy"
        ws.cell(row_index, 3, row[2])
        ws.cell(row_index, 4, row[3])
        ws.cell(row_index, 5, row[4])
        for col_index, value in enumerate(row[5:], start=6):
            ws.cell(row_index, col_index, float(value) if value else None).number_format = "#,##0.00"
    for index, largeur in enumerate((16, 16, 24, 32, 64, 16, 16, 18), start=1):
        ws.column_dimensions[get_column_letter(index)].width = largeur
    wb.properties.title = "Journal de contrôle bancaire ONEC Smart"
    wb.properties.creator = "ONEC Smart"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


async def historiser_export(
    db: AsyncSession,
    *,
    organisation_id: int,
    user_id: UUID | None,
    type_export: str,
    filtres: ExportComptableFiltres,
    nom_fichier: str,
    contenu: bytes,
    empreinte_selection: str,
    nombre_ecritures: int,
    nombre_lignes: int,
    total_debit: Decimal,
    total_credit: Decimal,
    ecriture_ids: list[UUID] | None = None,
    reexport_de_id: UUID | None = None,
) -> ComptaExportHistorique:
    historique = ComptaExportHistorique(
        organisation_id=organisation_id,
        type_export=type_export,
        format=filtres.format,
        journal=filtres.journal,
        compte_bancaire_id=filtres.compte_bancaire_id,
        devise=filtres.devise,
        date_debut=filtres.date_debut,
        date_fin=filtres.date_fin,
        nombre_ecritures=nombre_ecritures,
        nombre_lignes=nombre_lignes,
        total_debit=_q(total_debit),
        total_credit=_q(total_credit),
        ecart=_q(total_debit - total_credit),
        nom_fichier=nom_fichier,
        empreinte_fichier=_sha256(contenu),
        empreinte_selection=empreinte_selection,
        genere_par=user_id,
        reexport_de_id=reexport_de_id,
    )
    db.add(historique)
    await db.flush()
    for ecriture_id in ecriture_ids or []:
        db.add(
            ComptaExportEcriture(
                organisation_id=organisation_id,
                export_id=historique.id,
                ecriture_id=ecriture_id,
            )
        )
    await db.flush()
    return historique


def exiger_exportable(selection: SelectionComptable, filtres: ExportComptableFiltres) -> None:
    if filtres.format != "XLSX":
        raise HTTPException(
            status_code=400,
            detail="Le format logiciel comptable est XLSX : CSV ne conserve pas les types exigés par le modèle.",
        )
    if selection.premier_export_id and not filtres.autoriser_reexport:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cette sélection a déjà été générée dans l'export {selection.premier_export_id}. "
                "Activez explicitement la réexportation si le comptable confirme qu'elle est nécessaire."
            ),
        )
    if not selection.apercu.exportable:
        messages = [a.message for a in selection.apercu.anomalies if a.bloquante]
        raise HTTPException(
            status_code=400,
            detail={"message": "Export bloqué par les contrôles comptables.", "anomalies": messages[:30]},
        )


def empreinte_controle(journal: ReportJournalResponse, filtres: ExportComptableFiltres) -> str:
    payload = {
        "date_debut": filtres.date_debut.isoformat(),
        "date_fin": filtres.date_fin.isoformat(),
        "compte_bancaire_id": filtres.compte_bancaire_id,
        "devise": filtres.devise,
        "lignes": [
            (
                ligne.date.isoformat(), ligne.reference, str(ligne.entree),
                str(ligne.sortie), str(ligne.solde), ligne.transaction_id,
            )
            for ligne in journal.lignes
        ],
    }
    return _sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
