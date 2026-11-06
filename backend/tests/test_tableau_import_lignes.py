from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest
from fastapi import HTTPException

from app.modules.tableau.import_lignes import lignes_import
from app.modules.tableau.service import import_source_snapshot


def _xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


COLONNES = ["Membre", "Déclaré", "Souscrit", "Fin couverture", "Assureur"]


async def _import_assurances(db, user):
    contenu = _xlsx(COLONNES, [
        ["EC/17.96527 ZEBO Yvon", "Oui", "Oui", "19/11/2025", "ACTIVA"],
        ["EC/17.96528 MUKENDI Paul", "Oui", "Oui", "01/02/2026", "SONAS Générale"],
        ["SEC/18.96001 CABINET X", "Non", "Non", None, None],
    ])
    outcome = await import_source_snapshot(
        db, user, user.organisation_id, "assurances-lignes.xlsx", contenu, "assurances", "2026", date(2026, 10, 1),
    )
    return outcome.imp


@pytest.mark.asyncio
async def test_les_colonnes_du_fichier_reviennent_dans_leur_ordre(db_session, test_admin_user):
    imp = await _import_assurances(db_session, test_admin_user)
    page = await lignes_import(db_session, test_admin_user.organisation_id, imp.id)
    assert page["colonnes"] == COLONNES
    assert page["feuille"] == "Sheet1"
    assert page["total"] == 3
    premiere = page["lignes"][0]
    assert premiere["valeurs"][0] == "EC/17.96527 ZEBO Yvon"
    assert premiere["valeurs"][4] == "ACTIVA"


@pytest.mark.asyncio
async def test_la_recherche_porte_sur_les_valeurs_sans_accents(db_session, test_admin_user):
    imp = await _import_assurances(db_session, test_admin_user)
    org = test_admin_user.organisation_id
    assert (await lignes_import(db_session, org, imp.id, recherche="generale sonas"))["total"] == 1
    # Un nom de colonne n'est pas une valeur.
    assert (await lignes_import(db_session, org, imp.id, recherche="Assureur"))["total"] == 0


@pytest.mark.asyncio
async def test_import_d_un_autre_conseil_introuvable(db_session, test_admin_user):
    imp = await _import_assurances(db_session, test_admin_user)
    with pytest.raises(HTTPException) as refus:
        await lignes_import(db_session, test_admin_user.organisation_id + 10_000, imp.id)
    assert refus.value.status_code == 404
