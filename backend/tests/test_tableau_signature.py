"""Signature des rapports du Tableau : Commission Tableau du conseil, Président ou Présidente, puis le nom."""
from __future__ import annotations

import io
from datetime import date

import openpyxl
import pdfplumber
import pytest
from sqlalchemy import delete

from app.models.commission_member import CommissionMember, CommissionRole
from app.models.service import Service
from app.modules.tableau import rapport_complet as R
from app.modules.tableau import verdict as V
from app.modules.tableau.report_generator import generate_analyse_report
from app.modules.tableau.signature import Signature, commission_du_conseil, qualite_president, signature_commission


def test_commission_du_conseil():
    assert commission_du_conseil("Conseil Provincial de Kinshasa") == "Commission Tableau du Conseil Provincial de Kinshasa"
    assert commission_du_conseil("Conseil National") == "Commission Tableau du Conseil National"
    assert commission_du_conseil("") == "Commission Tableau"


def test_qualite_selon_le_sexe():
    assert qualite_president("M") == "Président"
    assert qualite_president("F") == "Présidente"
    # Sexe inconnu : on n'accorde pas au hasard.
    assert qualite_president(None) == "Président(e)"


SIGNATURE = Signature(commission="Commission Tableau du Conseil Provincial de Kinshasa", qualite="Présidente", nom="KABILA Marie")


def _donnees():
    ctx = R.ContexteRapport(
        exercice="2026", date_situation=date(2026, 1, 10), source="Fichier test.xlsx", organisation="Conseil Provincial de Kinshasa",
        reglages=V.TableauReglages(), exercice_annee=2026, genere_le=date(2026, 11, 8), signature=SIGNATURE,
    )
    dossier = {
        "id": 1, "numero_ordre": "EC/16.00001", "nom": "MEMBRE", "prenom": None, "categorie": "EC Cabinet", "cotisation_payee": True,
        "assurance": None, "chiffre_affaires": None, "heures_forco": 130.0, "sexe": "M", "anciennete": "Ancien",
        "telephone": "", "email": "", "conclusion": V.INSCRIT, "conclusion_motif": None, "raw_data": {},
    }
    return R.construire_donnees([dossier], ctx)


def test_la_signature_clot_le_pdf_et_l_excel():
    with pdfplumber.open(io.BytesIO(R.build_pdf(_donnees()))) as pdf:
        derniere = pdf.pages[-1].extract_text() or ""
    lignes = [l.strip() for l in derniere.splitlines()]
    debut = lignes.index(SIGNATURE.commission)
    assert lignes[debut + 1:debut + 3] == ["Présidente", "KABILA Marie"]

    classeur = openpyxl.load_workbook(io.BytesIO(R.build_excel(_donnees())))
    valeurs = [c.value for c in classeur.worksheets[-1]["B"] if c.value]
    assert valeurs[-3:] == SIGNATURE.lignes()


def test_la_signature_clot_le_rapport_d_analyse():
    texte = generate_analyse_report("2026", {}, [], signature=SIGNATURE.lignes())
    lignes = texte.splitlines()
    assert lignes[lignes.index(SIGNATURE.commission) + 1:lignes.index(SIGNATURE.commission) + 3] == ["Présidente", "KABILA Marie"]
    assert texte.rstrip().endswith("═" * 60)


@pytest.mark.asyncio
async def test_president_de_la_commission_tableau(db_session, test_admin_user):
    org = test_admin_user.organisation_id
    service = Service(code="CTSIGN", libelle="Commission Tableau (test signature)", organisation_id=org)
    db_session.add(service)
    await db_session.flush()
    try:
        # Aucun président désigné : la commission signe seule.
        sans = await signature_commission(db_session, org, "Conseil de test")
        assert sans.lignes() == ["Commission Tableau du Conseil de test", "Président(e)"]

        db_session.add_all([
            CommissionMember(service_id=service.id, full_name="MEMBRE Simple", role_type=CommissionRole.MEMBRE),
            CommissionMember(service_id=service.id, full_name="NSIMBA Claire", role_type=CommissionRole.PRESIDENT, custom_title="Présidente"),
        ])
        await db_session.flush()
        signature = await signature_commission(db_session, org, "Conseil Provincial de Kinshasa")
        assert signature.lignes() == ["Commission Tableau du Conseil Provincial de Kinshasa", "Présidente", "NSIMBA Claire"]
    finally:
        await db_session.rollback()
        await db_session.execute(delete(Service).where(Service.code == "CTSIGN"))
        await db_session.commit()
