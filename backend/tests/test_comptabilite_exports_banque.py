"""Contrôles du contrat d'export et du rapprochement bancaire."""

from __future__ import annotations

import io
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook

import app.db.session  # noqa: F401 — active le cloisonnement tenant
from app.core.tenant_context import set_current_tenant_id
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
import app.api.v1.endpoints.reports as reports
from app.modules.comptabilite.models import (
    RUBRIQUE_VIREMENTS_INTERNES,
    ComptaCompte,
    ComptaEcriture,
    ComptaExercice,
    ComptaJournal,
    ComptaLigneEcriture,
    ComptaMappingCompteBancaire,
    ComptaMappingRubrique,
    ComptaReferentiel,
    ComptaSociete,
)
from app.modules.comptabilite.schemas.exports import ExportComptableFiltres
from app.schemas.reports import ReportJournalLine, ReportJournalResponse
from app.modules.comptabilite.services.export_service import (
    ENTETE_LOGICIEL,
    creer_xlsx_logiciel,
    historiser_export,
    preparer_export_comptable,
)
from app.modules.comptabilite.services.rapprochement_bancaire import (
    Candidat,
    importer_releve,
    parser_releve,
    scorer,
)


def _org() -> Organisation:
    suffix = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    return Organisation(
        nom=f"Export {suffix}",
        slug=f"export-{suffix}",
        plan_type="ACTIVE",
        status_abonnement="ACTIVE",
        limite_utilisateurs=10,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


async def _setup(db, organisation_id: int):
    societe = ComptaSociete(
        organisation_id=organisation_id,
        code="SOC",
        raison_sociale="Société export",
    )
    referentiel = ComptaReferentiel(
        organisation_id=organisation_id,
        code="REF",
        libelle="Plan export",
        type_referentiel="PERSONNALISE",
    )
    db.add_all([societe, referentiel])
    await db.flush()
    banque = ComptaCompte(
        organisation_id=organisation_id,
        referentiel_id=referentiel.id,
        numero="5210000001",
        libelle="Banque",
        nature="ACTIF",
        sens_normal="DEBIT",
    )
    produit = ComptaCompte(
        organisation_id=organisation_id,
        referentiel_id=referentiel.id,
        numero="7060000001",
        libelle="Cotisations",
        nature="PRODUIT",
        sens_normal="CREDIT",
    )
    db.add_all([banque, produit])
    await db.flush()
    journal = ComptaJournal(
        organisation_id=organisation_id,
        societe_id=societe.id,
        code="BQ",
        libelle="Banque",
        type_journal="BQ",
    )
    exercice = ComptaExercice(
        organisation_id=organisation_id,
        societe_id=societe.id,
        code="2026",
        date_debut=date(2026, 1, 1),
        date_fin=date(2026, 12, 31),
        referentiel_id=referentiel.id,
        statut="OUVERT",
    )
    compte_bancaire = CompteBancaire(
        organisation_id=organisation_id,
        intitule="Banque non mappée",
        numero_compte="001-TEST",
        devise="USD",
        account_type="BANK",
    )
    db.add_all([journal, exercice, compte_bancaire])
    await db.flush()
    return societe, banque, produit, journal, exercice, compte_bancaire


async def _ecriture(
    db,
    *,
    organisation_id: int,
    societe: ComptaSociete,
    banque: ComptaCompte,
    produit: ComptaCompte,
    journal: ComptaJournal,
    exercice: ComptaExercice,
    numero: str,
    devise: str = "USD",
    statut: str = "VALIDEE",
):
    ecriture = ComptaEcriture(
        organisation_id=organisation_id,
        societe_id=societe.id,
        exercice_id=exercice.id,
        journal_id=journal.id,
        numero=numero,
        date_ecriture=date(2026, 10, 15),
        reference_piece=f"REC-{numero}",
        libelle="Cotisation octobre",
        statut=statut,
        devise=devise,
        module_origine="encaissements",
        type_origine="encaissement",
        objet_origine_id=str(uuid.uuid4()),
    )
    db.add(ecriture)
    await db.flush()
    db.add_all([
        ComptaLigneEcriture(
            organisation_id=organisation_id,
            societe_id=societe.id,
            ecriture_id=ecriture.id,
            compte_id=banque.id,
            ordre=1,
            libelle="Encaissement cotisation",
            debit=Decimal("125.40"),
            credit=Decimal("0"),
            debit_tenue=Decimal("125.40"),
            credit_tenue=Decimal("0"),
            devise=devise,
        ),
        ComptaLigneEcriture(
            organisation_id=organisation_id,
            societe_id=societe.id,
            ecriture_id=ecriture.id,
            compte_id=produit.id,
            ordre=2,
            libelle="Cotisation membre",
            debit=Decimal("0"),
            credit=Decimal("125.40"),
            debit_tenue=Decimal("0"),
            credit_tenue=Decimal("125.40"),
            devise=devise,
        ),
    ])
    await db.flush()
    return ecriture


def _journal_simule(lignes_par_compte: dict[int | None, list[ReportJournalLine]]):
    """Remplace le journal de trésorerie : l'export en reprend les lignes telles quelles."""

    async def journal(*, canal, devise, compte_bancaire_id=None, **_):
        lignes = lignes_par_compte.get(compte_bancaire_id if canal == "BANQUE" else None, [])
        return ReportJournalResponse(canal=canal, devise=devise, compte_bancaire_id=compte_bancaire_id, lignes=lignes)

    return journal


async def _mapper_banque(db, organisation_id: int, compte_bancaire: CompteBancaire, compte: ComptaCompte):
    db.add(ComptaMappingCompteBancaire(
        organisation_id=organisation_id, compte_bancaire_id=compte_bancaire.id, compte_id=compte.id,
    ))
    await db.flush()


async def test_export_logiciel_vient_de_la_tresorerie(db_session, monkeypatch):
    set_current_tenant_id(None)
    org = _org()
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    societe, banque, produit, journal, exercice, compte_bancaire = await _setup(db_session, org.id)
    await _mapper_banque(db_session, org.id, compte_bancaire, banque)
    virements = ComptaCompte(
        organisation_id=org.id, referentiel_id=banque.referentiel_id, numero="5850000001",
        libelle="Virements de fonds", nature="ACTIF", sens_normal="DEBIT",
    )
    db_session.add(virements)
    await db_session.flush()
    db_session.add(ComptaMappingRubrique(
        organisation_id=org.id, code_rubrique=RUBRIQUE_VIREMENTS_INTERNES, compte_id=virements.id,
    ))
    # Une écriture validée existe, mais ce n'est plus elle qui fait l'export.
    await _ecriture(
        db_session, organisation_id=org.id, societe=societe, banque=banque, produit=produit,
        journal=journal, exercice=exercice, numero="BQ-2026-00001",
    )
    await db_session.flush()

    quand = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(reports, "journal_tresorerie", _journal_simule({
        compte_bancaire.id: [
            # Encaissement sans poste budgétaire connu : contrepartie vide.
            ReportJournalLine(
                date=quand, libelle="Cotisation octobre", reference="REC-001", entree=Decimal("125.40"),
                type_operation="ENCAISSEMENT", transaction_id=uuid.uuid4(), transaction_type="ENCAISSEMENT",
            ),
            # Versement de la caisse, sans numéro de pièce : la pièce reste vide.
            ReportJournalLine(
                date=quand, libelle="Versement à la banque", reference=None, entree=Decimal("50"),
                type_operation="VERSEMENT", transaction_id=uuid.uuid4(), transaction_type="SORTIE",
            ),
        ],
    }))

    filtres = ExportComptableFiltres(
        date_debut=date(2026, 10, 1), date_fin=date(2026, 10, 31), journal="BANQUE",
        compte_bancaire_id=compte_bancaire.id, devise="USD", format="XLSX",
    )
    selection = await preparer_export_comptable(db_session, organisation_id=org.id, filtres=filtres)
    apercu = selection.apercu
    assert apercu.exportable is True
    assert apercu.nombre_ecritures == 2
    assert apercu.nombre_lignes == 4
    assert apercu.total_debit == apercu.total_credit == Decimal("175.40")
    lignes = [(l.piece, l.compte, l.debit, l.credit) for l in selection.lignes_export]
    assert ("REC-001", "5210000001", Decimal("125.40"), Decimal("0")) in lignes
    assert ("REC-001", "", Decimal("0"), Decimal("125.40")) in lignes
    assert ("", "5210000001", Decimal("50.00"), Decimal("0")) in lignes
    assert ("", "5850000001", Decimal("0"), Decimal("50.00")) in lignes
    # Le compte vide se signale sans bloquer.
    vides = [a for a in apercu.anomalies if a.code == "COMPTE_VIDE"]
    assert len(vides) == 1 and vides[0].bloquante is False

    contenu = creer_xlsx_logiciel(selection.lignes_export)
    feuille = load_workbook(io.BytesIO(contenu), data_only=True).active
    assert tuple(cell.value for cell in feuille[1]) == ENTETE_LOGICIEL
    assert feuille.max_row == 5
    assert isinstance(feuille["A2"].value, datetime)
    comptes_excel = [feuille.cell(row, 3).value for row in range(2, 6)]
    assert None in comptes_excel
    assert all(isinstance(v, int) for v in comptes_excel if v is not None)

    await historiser_export(
        db_session, organisation_id=org.id, user_id=None, type_export="LOGICIEL_COMPTABLE",
        filtres=filtres, nom_fichier="import.xlsx", contenu=contenu,
        empreinte_selection=selection.empreinte, nombre_ecritures=2, nombre_lignes=4,
        total_debit=Decimal("175.40"), total_credit=Decimal("175.40"), ecriture_ids=[],
    )
    await db_session.flush()
    seconde = await preparer_export_comptable(db_session, organisation_id=org.id, filtres=filtres)
    assert seconde.apercu.exportable is False
    assert "DEJA_EXPORTEE" in {a.code for a in seconde.apercu.anomalies}
    reexport = await preparer_export_comptable(
        db_session, organisation_id=org.id, filtres=filtres.model_copy(update={"autoriser_reexport": True})
    )
    assert reexport.apercu.exportable is True
    assert reexport.premier_export_id is not None
    set_current_tenant_id(None)


async def test_banque_sans_mapping_laisse_le_compte_vide(db_session, monkeypatch):
    set_current_tenant_id(None)
    org = _org()
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    *_, compte_bancaire = await _setup(db_session, org.id)
    monkeypatch.setattr(reports, "journal_tresorerie", _journal_simule({
        compte_bancaire.id: [
            ReportJournalLine(
                date=datetime(2026, 10, 3, tzinfo=timezone.utc), libelle="Frais", reference="BS-9",
                sortie=Decimal("12"), type_operation="SORTIE", transaction_id=uuid.uuid4(), transaction_type="SORTIE",
            ),
        ],
    }))
    filtres = ExportComptableFiltres(
        date_debut=date(2026, 10, 1), date_fin=date(2026, 10, 31), journal="BANQUE",
        compte_bancaire_id=compte_bancaire.id, devise="USD",
    )
    selection = await preparer_export_comptable(db_session, organisation_id=org.id, filtres=filtres)
    assert selection.apercu.exportable is True
    assert [l.compte for l in selection.lignes_export] == ["", ""]
    # Une sortie : la contrepartie au débit, la trésorerie au crédit.
    assert sum(l.debit for l in selection.lignes_export) == Decimal("12.00")
    set_current_tenant_id(None)


def test_parser_releve_preserve_solde_negatif_et_exige_debit_credit_distincts():
    contenu = (
        "Date;Date de valeur;Référence;Bénéficiaire;Libellé;Débit;Crédit;Solde\n"
        "15/10/2026;16/10/2026;FR-01;Fournisseur;Frais bancaires;15,50;;(120,75)\n"
        "17/10/2026;;REC-10;Membre;Cotisation;;125,40;4,65\n"
    ).encode("utf-8")
    lignes = parser_releve(contenu, "releve.csv")
    assert len(lignes) == 2
    assert lignes[0].debit == Decimal("15.50")
    assert lignes[0].credit == Decimal("0")
    assert lignes[0].solde == Decimal("-120.75")
    assert lignes[1].credit == Decimal("125.40")

    candidat = Candidat(
        operation_type="encaissement",
        operation_id=str(uuid.uuid4()),
        date_operation=date(2026, 10, 17),
        reference="REC-10",
        libelle="Cotisation",
        tiers="Membre",
        debit=Decimal("0"),
        credit=Decimal("125.40"),
    )
    assert scorer(lignes[1], candidat) >= Decimal("95")
    assert scorer(lignes[0], candidat) == Decimal("0")


async def test_import_releve_ne_valide_jamais_seul_et_bloque_fichier_duplique(db_session):
    set_current_tenant_id(None)
    org = _org()
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    *_, compte_bancaire = await _setup(db_session, org.id)
    contenu = (
        "Date;Référence;Libellé;Débit;Crédit;Solde\n"
        "20/10/2026;FR-20;Frais de tenue de compte;10,00;;90,00\n"
    ).encode("utf-8")
    releve = await importer_releve(
        db_session,
        organisation_id=org.id,
        user_id=None,
        compte_bancaire_id=compte_bancaire.id,
        filename="releve_octobre.csv",
        content=contenu,
    )
    assert releve.nombre_lignes == 1
    assert releve.nombre_rapprochees == 0
    assert releve.nombre_propositions == 0

    with pytest.raises(HTTPException) as exc_info:
        await importer_releve(
            db_session,
            organisation_id=org.id,
            user_id=None,
            compte_bancaire_id=compte_bancaire.id,
            filename="copie.csv",
            content=contenu,
        )
    assert exc_info.value.status_code == 409
    set_current_tenant_id(None)


async def test_export_logiciel_signale_les_longueurs_que_le_logiciel_tronque(db_session, monkeypatch):
    """Le logiciel cible garde 50 caractères de libellé et 16 de pièce : au-delà
    il coupe sans prévenir. L'export le signale, sans bloquer ni tronquer."""
    set_current_tenant_id(None)
    org = _org()
    db_session.add(org)
    await db_session.flush()
    set_current_tenant_id(org.id)
    societe, banque, produit, journal, exercice, compte_bancaire = await _setup(db_session, org.id)
    await _mapper_banque(db_session, org.id, compte_bancaire, banque)

    quand = datetime(2026, 10, 15, 9, tzinfo=timezone.utc)
    libelle_long = "Cotisation annuelle 2026 de l'expert-comptable — règlement partiel du solde"
    monkeypatch.setattr(reports, "journal_tresorerie", _journal_simule({
        compte_bancaire.id: [
            ReportJournalLine(
                date=quand, libelle=libelle_long, reference="REC-2026-10-000123456", entree=Decimal("10"),
                type_operation="ENCAISSEMENT", transaction_id=uuid.uuid4(), transaction_type="ENCAISSEMENT",
            ),
            ReportJournalLine(
                date=quand, libelle="Cotisation", reference="REC-002", entree=Decimal("10"),
                type_operation="ENCAISSEMENT", transaction_id=uuid.uuid4(), transaction_type="ENCAISSEMENT",
            ),
        ],
    }))
    filtres = ExportComptableFiltres(
        date_debut=date(2026, 10, 1), date_fin=date(2026, 10, 31), journal="BANQUE",
        compte_bancaire_id=compte_bancaire.id, devise="USD", format="XLSX",
    )
    selection = await preparer_export_comptable(db_session, organisation_id=org.id, filtres=filtres)

    codes = [a.code for a in selection.apercu.anomalies]
    assert codes.count("LIBELLE_TROP_LONG") == 1
    assert codes.count("PIECE_TROP_LONGUE") == 1
    assert all(not a.bloquante for a in selection.apercu.anomalies)
    assert selection.apercu.exportable is True
    # Rien n'est coupé dans le fichier : c'est au comptable de reformuler.
    assert libelle_long in [l.libelle for l in selection.lignes_export]
