from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete

from app.modules.tableau.models import TableauSortieMembre

from app.modules.tableau.service import get_base_tableau, import_source_snapshot
from app.modules.tableau.sorties import annuler_sortie, declarer_sortie


def _xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def _base(db, user, exercice: str):
    org = user.organisation_id
    pp = _xlsx(
        ["N° Ordre", "Nom", "Statut", "Actif"],
        [["EC/18.97070", "DUPONT Jean", "en cabinet", "Oui"], ["EC/18.97071", "MUKENDI Paul", "salarié", "Oui"]],
    )
    pm = _xlsx(["N° d'ordre", "Société"], [["SEC/18.97001", "CABINET X"]])
    situation = date(int(exercice), 6, 1)
    await import_source_snapshot(db, user, org, f"pp-{exercice}.xlsx", pp, "personnes_physiques", exercice, situation)
    await import_source_snapshot(db, user, org, f"pm-{exercice}.xlsx", pm, "personnes_morales", exercice, situation)


@pytest_asyncio.fixture(autouse=True)
async def _sans_sorties_residuelles(db_session):
    """Les sorties sont validées en base (commit) : on les retire pour les autres tests."""
    yield
    await db_session.rollback()
    await db_session.execute(delete(TableauSortieMembre).where(TableauSortieMembre.numero_ordre.like("%.97%")))
    await db_session.commit()


def _numeros(base) -> set[str]:
    return {m["numero_ordre"] for m in base["membres_a_completer"]}


@pytest.mark.asyncio
async def test_un_membre_decede_quitte_la_base_en_exercice_et_garde_sa_categorie(db_session, test_admin_user):
    org = test_admin_user.organisation_id
    await _base(db_session, test_admin_user, exercice="2031")
    sortie = await declarer_sortie(
        db_session, test_admin_user, org, "tenant-test",
        numero_ordre=" ec/18.97070 ", nom="DUPONT Jean", categorie="EC Cabinet",
        situation="DECEDE", date_effet=date(2026, 3, 12), lieu_deces="Kinshasa",
    )
    assert sortie.numero_ordre == "EC/18.97070"

    en_exercice = await get_base_tableau(db_session, [org], exercice="2031")
    assert _numeros(en_exercice) == {"EC/18.97071", "SEC/18.97001"}

    sortis = await get_base_tableau(db_session, [org], exercice="2031", situation="sortis")
    [membre] = sortis["membres_a_completer"]
    assert membre["categorie"] == "EC Cabinet"
    assert membre["conclusion"] is None
    assert membre["sortie"]["libelle"] == "Décédé le 12/03/2026 à Kinshasa"

    tous = await get_base_tableau(db_session, [org], exercice="2031", situation="tous")
    assert len(tous["membres_a_completer"]) == 3


@pytest.mark.asyncio
async def test_la_sortie_ne_touche_pas_les_exercices_anterieurs(db_session, test_admin_user):
    org = test_admin_user.organisation_id
    await _base(db_session, test_admin_user, exercice="2019")
    await declarer_sortie(
        db_session, test_admin_user, org, "tenant-test",
        numero_ordre="EC/18.97070", nom="DUPONT Jean", categorie="EC Cabinet",
        situation="DECEDE", date_effet=date(2026, 3, 12), lieu_deces="Kinshasa",
    )
    base_2019 = await get_base_tableau(db_session, [org], exercice="2019")
    assert "EC/18.97070" in _numeros(base_2019)


@pytest.mark.asyncio
async def test_une_societe_qui_cesse_d_exister_par_fusion_nomme_l_absorbante(db_session, test_admin_user):
    org = test_admin_user.organisation_id
    await _base(db_session, test_admin_user, exercice="2032")
    with pytest.raises(HTTPException) as refus:
        await declarer_sortie(
            db_session, test_admin_user, org, "tenant-test",
            numero_ordre="SEC/18.97001", nom="CABINET X", categorie="Société",
            situation="CESSE", date_effet=date(2026, 1, 31), motif_cessation="FUSION",
        )
    assert refus.value.status_code == 422
    await declarer_sortie(
        db_session, test_admin_user, org, "tenant-test",
        numero_ordre="SEC/18.97001", nom="CABINET X", categorie="Société",
        situation="CESSE", date_effet=date(2026, 1, 31), motif_cessation="FUSION", societe_absorbante="CABINET Y",
    )
    base = await get_base_tableau(db_session, [org], exercice="2032", situation="CESSE")
    [membre] = base["membres_a_completer"]
    assert membre["sortie"]["libelle"] == "A cessé d'exister le 31/01/2026 (fusion-absorption par CABINET Y)"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("categorie", "situation", "extra"),
    [
        ("EC Cabinet", "DECEDE", {}),  # lieu du décès manquant
        ("Société", "DECEDE", {"lieu_deces": "Kinshasa"}),  # une société ne décède pas
        ("EC Salarié", "CESSE", {"motif_cessation": "DISSOLUTION"}),
        ("EC Salarié", "RADIE", {}),  # référence de la décision manquante
    ],
)
async def test_saisies_incompletes_ou_incoherentes_refusees(db_session, test_admin_user, categorie, situation, extra):
    with pytest.raises(HTTPException) as refus:
        await declarer_sortie(
            db_session, test_admin_user, test_admin_user.organisation_id, "tenant-test",
            numero_ordre="EC/18.97071", nom="X", categorie=categorie,
            situation=situation, date_effet=date(2026, 1, 1), **extra,
        )
    assert refus.value.status_code == 422


@pytest.mark.asyncio
async def test_annuler_la_sortie_reintegre_le_membre(db_session, test_admin_user):
    org = test_admin_user.organisation_id
    await _base(db_session, test_admin_user, exercice="2033")
    sortie = await declarer_sortie(
        db_session, test_admin_user, org, "tenant-test",
        numero_ordre="EC/18.97071", nom="MUKENDI Paul", categorie="EC Salarié",
        situation="RADIE", date_effet=date(2026, 2, 1), reference_decision="CN/2026/014",
    )
    assert "EC/18.97071" not in _numeros(await get_base_tableau(db_session, [org], exercice="2033"))
    await annuler_sortie(db_session, test_admin_user, org, sortie.id)
    assert "EC/18.97071" in _numeros(await get_base_tableau(db_session, [org], exercice="2033"))
