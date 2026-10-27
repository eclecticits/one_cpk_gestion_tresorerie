from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.api.v1.endpoints.reports import journal_tresorerie
from app.db.session import get_db
from app.models.user import User
from app.modules.comptabilite.models import (
    ComptaExportHistorique,
    ComptaReleveBancaireImport,
    ComptaReleveBancaireLigne,
)
from app.modules.comptabilite.schemas.exports import (
    ExportComptableApercuOut,
    ExportComptableFiltres,
    ExportHistoriqueOut,
)
from app.modules.comptabilite.schemas.rapprochement import (
    DecisionRapprochementIn,
    ReleveBancaireImportOut,
    ReleveBancaireLigneOut,
)
from app.modules.comptabilite.services.export_service import (
    creer_controle_bancaire,
    creer_xlsx_logiciel,
    empreinte_controle,
    exiger_exportable,
    historiser_export,
    preparer_export_comptable,
)
from app.modules.comptabilite.services.rapprochement_bancaire import (
    _ligne_out,
    decider_rapprochement,
    importer_releve,
    releve_out,
)
from app.schemas.reports import ReportJournalResponse
from app.services.audit_service import log_action


router = APIRouter()
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_CSV = "text/csv; charset=utf-8"
LECTURE_BANQUE = [
    "compta.lecture", "compta.saisie", "compta.validation", "compta.cloture",
    "compta.parametrage", "compta.export",
]


@router.post(
    "/exports/apercu",
    response_model=ExportComptableApercuOut,
    dependencies=[Depends(has_permission("compta.export"))],
)
async def apercu_export_comptable(
    filtres: ExportComptableFiltres,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ExportComptableApercuOut:
    selection = await preparer_export_comptable(
        db, organisation_id=tenant_id, filtres=filtres
    )
    return selection.apercu


@router.post(
    "/exports/logiciel-comptable",
    dependencies=[Depends(has_permission("compta.export"))],
)
async def export_logiciel_comptable(
    filtres: ExportComptableFiltres,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Sérialise les exports logiciels d'une organisation : deux clics
    # simultanés ne peuvent pas contourner le contrôle anti-réexport.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :organisation_id)"),
        {"namespace": 0x4F4E4543, "organisation_id": tenant_id},
    )
    selection = await preparer_export_comptable(
        db, organisation_id=tenant_id, filtres=filtres
    )
    exiger_exportable(selection, filtres)
    # L'aperçu est volontairement plafonné à 500 lignes, mais le fichier doit
    # toujours contenir la sélection complète.
    contenu = creer_xlsx_logiciel(selection.lignes_export)
    nom_fichier = (
        f"Import_comptable_{filtres.journal}_{filtres.devise}_"
        f"{filtres.date_debut:%Y%m%d}_{filtres.date_fin:%Y%m%d}.xlsx"
    )
    await historiser_export(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        type_export="LOGICIEL_COMPTABLE",
        filtres=filtres,
        nom_fichier=nom_fichier,
        contenu=contenu,
        empreinte_selection=selection.empreinte,
        nombre_ecritures=selection.apercu.nombre_ecritures,
        nombre_lignes=selection.apercu.nombre_lignes,
        total_debit=selection.apercu.total_debit,
        total_credit=selection.apercu.total_credit,
        ecriture_ids=[ecriture.id for ecriture in selection.ecritures],
        reexport_de_id=selection.premier_export_id if filtres.autoriser_reexport else None,
    )
    await db.commit()
    return Response(
        contenu,
        media_type=MIME_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@router.post(
    "/exports/controle-bancaire",
    dependencies=[Depends(has_permission("compta.export"))],
)
async def export_controle_bancaire(
    filtres: ExportComptableFiltres,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if filtres.journal != "BANQUE" or filtres.compte_bancaire_id is None:
        raise HTTPException(
            status_code=400,
            detail="Le journal de contrôle exige un compte bancaire précis.",
        )
    journal = await journal_tresorerie(
        canal="BANQUE",
        devise=filtres.devise,
        compte_bancaire_id=filtres.compte_bancaire_id,
        date_debut=filtres.date_debut.isoformat(),
        date_fin=filtres.date_fin.isoformat(),
        user=user,
        db=db,
        tenant_id=tenant_id,
    )
    contenu = creer_controle_bancaire(journal, filtres.format)
    extension = filtres.format.lower()
    nom_fichier = (
        f"Controle_bancaire_{filtres.compte_bancaire_id}_{filtres.devise}_"
        f"{filtres.date_debut:%Y%m%d}_{filtres.date_fin:%Y%m%d}.{extension}"
    )
    empreinte = empreinte_controle(journal, filtres)
    await historiser_export(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        type_export="CONTROLE_BANCAIRE",
        filtres=filtres,
        nom_fichier=nom_fichier,
        contenu=contenu,
        empreinte_selection=empreinte,
        nombre_ecritures=0,
        nombre_lignes=len(journal.lignes),
        # Convention du relevé bancaire : sorties au débit, entrées au crédit.
        total_debit=journal.total_sorties,
        total_credit=journal.total_entrees,
    )
    await db.commit()
    media_type = MIME_XLSX if filtres.format == "XLSX" else MIME_CSV
    return Response(
        contenu,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'},
    )


@router.get(
    "/exports/historique",
    response_model=list[ExportHistoriqueOut],
    dependencies=[Depends(has_permission("compta.export"))],
)
async def historique_exports(
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ExportHistoriqueOut]:
    exports = list(
        (
            await db.execute(
                select(ComptaExportHistorique)
                .where(ComptaExportHistorique.organisation_id == tenant_id)
                .order_by(ComptaExportHistorique.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
    )
    return [ExportHistoriqueOut.model_validate(item) for item in exports]


@router.get(
    "/banques/mouvements",
    response_model=ReportJournalResponse,
    dependencies=[Depends(has_any_permission(LECTURE_BANQUE))],
)
async def mouvements_bancaires(
    compte_bancaire_id: int,
    devise: str,
    date_debut: date | None = None,
    date_fin: date | None = None,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportJournalResponse:
    return await journal_tresorerie(
        canal="BANQUE",
        devise=devise,
        compte_bancaire_id=compte_bancaire_id,
        date_debut=date_debut.isoformat() if date_debut else None,
        date_fin=date_fin.isoformat() if date_fin else None,
        user=user,
        db=db,
        tenant_id=tenant_id,
    )


@router.post(
    "/banques/releves/import",
    response_model=ReleveBancaireImportOut,
    dependencies=[Depends(has_any_permission(["compta.saisie", "compta.validation", "compta.parametrage"]))],
)
async def import_releve_bancaire(
    compte_bancaire_id: int,
    file: UploadFile = File(...),
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReleveBancaireImportOut:
    content = await file.read()
    # Évite deux imports simultanés du même fichier sur le même compte : le
    # second attend, puis rencontre l'empreinte créée par le premier.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :compte_id)"),
        {"namespace": 0x42414E4B, "compte_id": compte_bancaire_id},
    )
    releve = await importer_releve(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        compte_bancaire_id=compte_bancaire_id,
        filename=file.filename or "releve",
        content=content,
    )
    await db.commit()
    await db.refresh(releve)
    return await releve_out(db, releve)


@router.get(
    "/banques/releves",
    response_model=list[ReleveBancaireImportOut],
    dependencies=[Depends(has_any_permission(LECTURE_BANQUE))],
)
async def liste_releves_bancaires(
    compte_bancaire_id: int | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ReleveBancaireImportOut]:
    stmt = select(ComptaReleveBancaireImport).where(
        ComptaReleveBancaireImport.organisation_id == tenant_id
    )
    if compte_bancaire_id is not None:
        stmt = stmt.where(ComptaReleveBancaireImport.compte_bancaire_id == compte_bancaire_id)
    releves = list(
        (await db.execute(stmt.order_by(ComptaReleveBancaireImport.created_at.desc()).limit(limit)))
        .scalars().all()
    )
    return [
        ReleveBancaireImportOut(
            id=item.id,
            compte_bancaire_id=item.compte_bancaire_id,
            devise=item.devise,
            nom_fichier=item.nom_fichier,
            format=item.format,
            statut=item.statut,
            nombre_lignes=item.nombre_lignes,
            nombre_doublons=item.nombre_doublons,
            nombre_propositions=item.nombre_propositions,
            nombre_rapprochees=item.nombre_rapprochees,
            importe_par=item.importe_par,
            created_at=item.created_at,
            lignes=[],
        )
        for item in releves
    ]


@router.get(
    "/banques/releves/{releve_id}",
    response_model=ReleveBancaireImportOut,
    dependencies=[Depends(has_any_permission(LECTURE_BANQUE))],
)
async def detail_releve_bancaire(
    releve_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ReleveBancaireImportOut:
    releve = (
        await db.execute(
            select(ComptaReleveBancaireImport).where(
                ComptaReleveBancaireImport.id == releve_id,
                ComptaReleveBancaireImport.organisation_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if releve is None:
        raise HTTPException(status_code=404, detail="Import de relevé introuvable.")
    return await releve_out(db, releve)


@router.patch(
    "/banques/releves/lignes/{ligne_id}",
    response_model=ReleveBancaireLigneOut,
    dependencies=[Depends(has_permission("compta.validation"))],
)
async def valider_rapprochement_bancaire(
    ligne_id: UUID,
    payload: DecisionRapprochementIn,
    tenant_id: int = Depends(get_current_tenant_id),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReleveBancaireLigneOut:
    avant = (
        await db.execute(
            select(
                ComptaReleveBancaireLigne.statut_rapprochement,
                ComptaReleveBancaireLigne.operation_type,
                ComptaReleveBancaireLigne.operation_id,
            ).where(
                ComptaReleveBancaireLigne.id == ligne_id,
                ComptaReleveBancaireLigne.organisation_id == tenant_id,
            )
        )
    ).one_or_none()
    ligne = await decider_rapprochement(
        db,
        organisation_id=tenant_id,
        user_id=user.id,
        ligne_id=ligne_id,
        decision=payload.decision,
        operation_type=payload.operation_type,
        operation_id=payload.operation_id,
    )
    # La ligne ne garde que la dernière décision ; l'audit garde toutes les
    # autres, annulations comprises.
    await log_action(
        db,
        user_id=user.id,
        action=f"COMPTA_RAPPROCHEMENT_{payload.decision}",
        target_table="compta_releve_bancaire_lignes",
        target_id=str(ligne.id),
        old_value=dict(avant._mapping) if avant else None,
        new_value={
            "statut": ligne.statut_rapprochement,
            "operation_type": ligne.operation_type,
            "operation_id": ligne.operation_id,
        },
    )
    await db.commit()
    await db.refresh(ligne)
    return _ligne_out(ligne)
