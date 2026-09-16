from __future__ import annotations

import io
import inspect
from datetime import date, datetime

import openpyxl
import pytest
from sqlalchemy import select

from app.modules.tableau.models import (
    TableauDossier,
    TableauCaDeclaration,
    TableauInsuranceDeclaration,
    TableauImport,
    TableauMemberIdentity,
    TableauPersonneMoraleSnapshot,
    TableauPersonnePhysiqueSnapshot,
    TableauSourceRow,
)
from app.modules.tableau.service import build_preparatory_tableau_at_date, ca_present_at_date, get_ca_declarations_at_date, get_insurance_declarations_at_date, get_personne_physique_at_date, import_source_snapshot, insurance_status_at_date
from app.modules.tableau.source_adapters import file_sha256, parse_source_excel, row_sha256
import app.modules.tableau.service as tableau_service


def _xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("source_type", "headers", "row"),
    [
        ("personnes_physiques", ["N° d'ordre", "Nom", "Statut"], ["EC/18.00062", "DUPONT Jean", "indépendant"]),
        ("personnes_morales", ["N° d'ordre", "Société", "Ville"], ["SEC/18.00001", "CABINET X", "Kinshasa"]),
        ("chiffres_affaires", ["N° d'ordre", "Année", "Devise", "CA facturé"], ["EC/18.00062", 2025, "USD", 1000]),
        ("assurances", ["Membre", "Déclaré", "Souscrit", "Assureur"], ["SEC/18.00001", "Oui", "Oui", "Assureur X"]),
    ],
)
def test_source_adapter_accepts_each_source_type(source_type, headers, row):
    result = parse_source_excel(_xlsx(headers, [row]), source_type)
    assert len(result.rows) == 1
    assert result.rows[0].raw_data[headers[0]] == row[0]
    assert result.rows[0].business_key_candidate == str(row[0])


def test_source_snapshot_preserves_raw_row_and_hash():
    content = _xlsx(
        ["N° Ordre", "Nom", "Assuré", "CA facturé", "Date naissance", "Vide"],
        [["  EC/18.00062 ", "DUPONT Jean", "OUI", "1 250 000,50", datetime(1980, 1, 2), None]],
    )
    result = parse_source_excel(content, "personnes_physiques")
    raw = result.rows[0].raw_data
    assert raw["N° Ordre"] == "  EC/18.00062 "
    assert raw["Assuré"] == "OUI"
    assert raw["CA facturé"] == "1 250 000,50"
    assert raw["Date naissance"] == "1980-01-02T00:00:00"
    assert raw["Vide"] is None
    assert result.rows[0].normalized_data["numero_ordre"] == "  EC/18.00062 "
    assert len(file_sha256(content)) == 64


def test_file_and_row_fingerprints_are_distinct_concepts():
    content_a = _xlsx(["N° d'ordre", "Nom"], [["EC/18.00062", "DUPONT"]])
    raw = {"N° d'ordre": "EC/18.00062", "Nom": "DUPONT"}
    assert row_sha256(raw) != file_sha256(content_a)
    assert row_sha256(raw) == row_sha256(dict(raw))


@pytest.mark.parametrize("order_header", ["N° Ordre", "N° d'ordre", "N° ordre", "Numéro d'ordre"])
def test_real_order_header_variants_are_recognized_without_overmatching(order_header):
    accepted = parse_source_excel(_xlsx([order_header, "Nom"], [["EC/18.00062", "DUPONT"]]), "personnes_physiques")
    assert len(accepted.rows) == 1
    rejected = parse_source_excel(_xlsx(["Référence libre", "Nom"], [["EC/18.00062", "DUPONT"]]), "personnes_physiques")
    assert rejected.rows == []
    assert any(error["champ"] == "headers" for error in rejected.errors)


def test_real_export_column_sets_are_accepted():
    fixtures = {
        "personnes_physiques": [
            "N° Ordre", "Nom", "Sexe", "Actif", "Date naissance", "Téléphone", "Email", "Ville",
            "Statut", "N° impôt", "Assuré", "AMLCO", "% 120 FOR", "% 80 FOR",
        ],
        "personnes_morales": [
            "N° Ordre", "Société", "Téléphone", "Email", "Ville", "Numéro impôt", "Cotisation",
            "Solde", "Assuré", "Nb employés", "Nb EC", "Nb StA",
        ],
        "chiffres_affaires": [
            "N° d'ordre", "Membre", "Actif", "Année", "Devise", "CA facturé", "CA collecté", "Date mise à jour",
        ],
        "assurances": [
            "Membre", "Déclaré", "Souscrit", "Fin couverture", "Année de souscription", "Assureur", "Période",
        ],
    }
    values = {
        "personnes_physiques": ["EC/18.00062", "DUPONT", "M", "Oui", date(1980, 1, 2), "0800000000", "a@b.cd", "Kinshasa", "indépendant", "NIF1", "Oui", "Non", 80, 20],
        "personnes_morales": ["SEC/18.00001", "SOCIETE X", "0800000000", "a@b.cd", "Kinshasa", "NIF2", "Oui", 0, "Oui", 4, 2, 1],
        "chiffres_affaires": ["EC/18.00062", "DUPONT", "Oui", 2025, "USD", "1 250 000,50", "1 000 000", date(2026, 1, 2)],
        "assurances": ["EC/18.00062", "Oui", "Oui", date(2026, 12, 31), 2026, "Assureur X", "annuelle"],
    }
    for source_type, headers in fixtures.items():
        result = parse_source_excel(_xlsx(headers, [values[source_type]]), source_type)
        assert len(result.rows) == 1, (source_type, result.errors)
        assert result.errors == [], (source_type, result.errors)


@pytest.mark.asyncio
async def test_snapshot_import_is_idempotent_for_same_file_and_situation(db_session, test_admin_user):
    content = _xlsx(["N° d'ordre", "Nom"], [["EC/18.00062", "DUPONT Jean"]])
    kwargs = dict(
        db=db_session,
        user=test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        file_name="physiques.xlsx",
        content=content,
        source_type="personnes_physiques",
        exercice="2026",
        date_situation=date(2026, 6, 1),
    )
    first = await import_source_snapshot(**kwargs)
    second = await import_source_snapshot(**kwargs)
    assert first.duplicate_detected is False
    assert second.duplicate_detected is True
    rows = (await db_session.execute(select(TableauSourceRow).where(TableauSourceRow.import_id == first.imp.id))).scalars().all()
    assert len(rows) == 1
    assert rows[0].raw_data["Nom"] == "DUPONT Jean"
    dossiers = (await db_session.execute(select(TableauDossier).where(TableauDossier.import_id == first.imp.id))).scalars().all()
    assert dossiers == []


@pytest.mark.asyncio
async def test_same_file_new_situation_creates_new_snapshot(db_session, test_admin_user):
    content = _xlsx(["N° d'ordre", "Nom"], [["EC/18.00063", "MUKENDI Paul"]])
    common = dict(db=db_session, user=test_admin_user, organisation_id=test_admin_user.organisation_id,
                  file_name="physiques-2.xlsx", content=content, source_type="personnes_physiques", exercice="2026")
    first = await import_source_snapshot(**common, date_situation=date(2026, 6, 2))
    second = await import_source_snapshot(**common, date_situation=date(2026, 7, 2))
    assert first.imp.id != second.imp.id
    assert second.duplicate_detected is False


@pytest.mark.asyncio
async def test_same_bytes_different_source_type_are_distinct(db_session, test_admin_user):
    content = _xlsx(["N° d'ordre", "Nom", "Année"], [["EC/18.00064", "KABAMBA", 2025]])
    common = dict(db=db_session, user=test_admin_user, organisation_id=test_admin_user.organisation_id,
                  file_name="same-bytes.xlsx", content=content, exercice="2026", date_situation=date(2026, 6, 3))
    first = await import_source_snapshot(**common, source_type="personnes_physiques")
    second = await import_source_snapshot(**common, source_type="personnes_morales")
    assert first.duplicate_detected is False
    assert second.duplicate_detected is False
    assert first.imp.id != second.imp.id


@pytest.mark.asyncio
async def test_same_file_different_organisation_is_distinct(db_session, test_admin_user, test_organisation):
    from app.models.organisation import Organisation

    other = Organisation(nom="Autre organisation", slug="tableau-multisource-other", is_active=True)
    db_session.add(other)
    await db_session.flush()
    content = _xlsx(["N° d'ordre", "Nom"], [["EC/18.00065", "KABAMBA"]])
    common = dict(db=db_session, user=test_admin_user, file_name="org.xlsx", content=content,
                  source_type="personnes_physiques", exercice="2026", date_situation=date(2026, 6, 4))
    first = await import_source_snapshot(organisation_id=test_admin_user.organisation_id, **common)
    second = await import_source_snapshot(organisation_id=other.id, **common)
    assert first.duplicate_detected is False
    assert second.duplicate_detected is False


@pytest.mark.asyncio
async def test_pp_creates_internal_ec_identity_and_snapshot_without_tableau_dossier(db_session, test_admin_user):
    content = _xlsx(["N° Ordre", "Nom", "Statut", "Actif"], [["EC/18.00070", "DUPONT Jean", "indépendant", "Oui"]])
    outcome = await import_source_snapshot(
        db_session, test_admin_user, test_admin_user.organisation_id, "pp.xlsx", content,
        "personnes_physiques", "2026", date(2026, 9, 1),
    )
    identity = (await db_session.execute(select(TableauMemberIdentity).where(TableauMemberIdentity.numero_ordre == "EC/18.00070"))).scalar_one()
    snapshot = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.source_import_id == outcome.imp.id))).scalar_one()
    assert identity.member_kind == "EC"
    assert identity.person_kind == "PHYSIQUE"
    assert snapshot.identity_id == identity.id
    assert snapshot.statut_normalise == "INDEPENDANT"
    assert (await db_session.execute(select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_pm_creates_internal_sec_identity(db_session, test_admin_user):
    content = _xlsx(["N° Ordre", "Société", "Nb employés", "Nb EC", "Nb StA"], [["SEC/18.00071", "SOCIETE X", 5, 2, 1]])
    await import_source_snapshot(
        db_session, test_admin_user, test_admin_user.organisation_id, "pm.xlsx", content,
        "personnes_morales", "2026", date(2026, 9, 1),
    )
    identity = (await db_session.execute(select(TableauMemberIdentity).where(TableauMemberIdentity.numero_ordre == "SEC/18.00071"))).scalar_one()
    snapshot = (await db_session.execute(select(TableauPersonneMoraleSnapshot).where(TableauPersonneMoraleSnapshot.numero_ordre == "SEC/18.00071"))).scalar_one()
    assert identity.member_kind == "SEC"
    assert identity.person_kind == "MORALE"
    assert snapshot.nb_ec == 2


@pytest.mark.asyncio
async def test_identity_is_reused_and_snapshots_are_append_only(db_session, test_admin_user):
    first_content = _xlsx(["N° Ordre", "Nom", "Téléphone"], [["EC/18.00072", "DUPONT", "A"]])
    second_content = _xlsx(["N° Ordre", "Nom", "Téléphone"], [["EC/18.00072", "DUPONT", "B"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "a.xlsx", first_content, "personnes_physiques", "2026", date(2026, 9, 1))
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "b.xlsx", second_content, "personnes_physiques", "2026", date(2026, 9, 12))
    identities = (await db_session.execute(select(TableauMemberIdentity).where(TableauMemberIdentity.numero_ordre == "EC/18.00072"))).scalars().all()
    snapshots = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.numero_ordre == "EC/18.00072").order_by(TableauPersonnePhysiqueSnapshot.date_situation))).scalars().all()
    assert len(identities) == 1
    assert [snapshot.telephone for snapshot in snapshots] == ["A", "B"]


@pytest.mark.asyncio
async def test_snapshot_can_be_reconstructed_at_a_situation_date(db_session, test_admin_user):
    for situation, phone in ((date(2026, 9, 1), "A"), (date(2026, 9, 12), "B")):
        content = _xlsx(["N° Ordre", "Nom", "Téléphone"], [["EC/18.00073", "DUPONT", phone]])
        await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, f"{phone}.xlsx", content, "personnes_physiques", "2026", situation)
    snapshot = await get_personne_physique_at_date(db_session, test_admin_user.organisation_id, " ec/18.00073 ", date(2026, 9, 5))
    assert snapshot is not None and snapshot.telephone == "A"


@pytest.mark.asyncio
async def test_incompatible_prefix_is_anomaly_without_conversion(db_session, test_admin_user):
    content = _xlsx(["N° Ordre", "Nom"], [["SEC/18.00074", "SOCIETE X"]])
    outcome = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "bad-pp.xlsx", content, "personnes_physiques", "2026", date(2026, 9, 1))
    row = (await db_session.execute(select(TableauSourceRow).where(TableauSourceRow.import_id == outcome.imp.id))).scalar_one()
    assert row.business_key_candidate == "SEC/18.00074"
    assert row.normalization_status == "warning"
    assert "SEC/18.00074" in {i.numero_ordre for i in (await db_session.execute(select(TableauMemberIdentity))).scalars().all()}
    assert (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.source_row_id == row.id))).scalars().all()


@pytest.mark.asyncio
async def test_absence_in_later_partial_import_does_not_deactivate_member(db_session, test_admin_user):
    content = _xlsx(["N° Ordre", "Nom", "Actif"], [["EC/18.00075", "DUPONT", "Oui"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "initial.xlsx", content, "personnes_physiques", "2026", date(2026, 9, 1))
    empty = _xlsx(["N° Ordre", "Nom", "Actif"], [])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "partial.xlsx", empty, "personnes_physiques", "2026", date(2026, 9, 12))
    identity = (await db_session.execute(select(TableauMemberIdentity).where(TableauMemberIdentity.numero_ordre == "EC/18.00075"))).scalar_one()
    assert identity.classification_status == "classified"


@pytest.mark.asyncio
async def test_unknown_values_remain_null_and_are_not_defaulted(db_session, test_admin_user):
    content = _xlsx(["N° Ordre", "Nom", "Actif", "AMLCO", "% 120 FOR"], [["EC/18.00076", "DUPONT", "PEUT-ETRE", "?", "inconnu"]])
    outcome = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "unknown.xlsx", content, "personnes_physiques", "2026", date(2026, 9, 1))
    snapshot = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.source_import_id == outcome.imp.id))).scalar_one()
    assert snapshot.actif is None and snapshot.amlco is None and snapshot.pourcentage_120_for is None
    row = (await db_session.execute(select(TableauSourceRow).where(TableauSourceRow.import_id == outcome.imp.id))).scalar_one()
    assert row.normalization_status == "warning"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statut", "header", "value", "field", "expected"),
    [
        ("en cabinet", "Cabinet d'attache", "SEC/22.00088", "cabinet_attache", "SEC/22.00088"),
        ("indépendant", "NIF", "A1502382C", "nif", "A1502382C"),
        ("salarié", "Nom de l'employeur", "Ministère des Finances", "nom_employeur", "Ministère des Finances"),
    ],
)
async def test_pp_contextual_status_fields_are_snapshot_values(db_session, test_admin_user, statut, header, value, field, expected):
    content = _xlsx(["N° Ordre", "Nom", "Statut", header], [["EC/18.00077", "DUPONT", statut, value]])
    outcome = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, f"contextual-{field}.xlsx", content, "personnes_physiques", "2026", date(2026, 9, 1))
    snapshot = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.source_import_id == outcome.imp.id))).scalar_one()
    assert getattr(snapshot, field) == expected
    assert snapshot.nif is None if field != "nif" else True


@pytest.mark.asyncio
async def test_pp_status_change_keeps_identity_and_old_snapshot(db_session, test_admin_user):
    for name, situation, statut, header, value in (
        ("ind.xlsx", date(2026, 9, 1), "indépendant", "NIF", "A1502382C"),
        ("cab.xlsx", date(2026, 9, 12), "en cabinet", "Cabinet d'attache", "SEC/22.00088"),
    ):
        await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, name, _xlsx(["N° Ordre", "Nom", "Statut", header], [["EC/18.00078", "DUPONT", statut, value]]), "personnes_physiques", "2026", situation)
    identity = (await db_session.execute(select(TableauMemberIdentity).where(TableauMemberIdentity.numero_ordre == "EC/18.00078"))).scalar_one()
    snapshots = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.numero_ordre == "EC/18.00078").order_by(TableauPersonnePhysiqueSnapshot.date_situation))).scalars().all()
    assert len(snapshots) == 2 and snapshots[0].nif == "A1502382C" and snapshots[1].cabinet_attache == "SEC/22.00088"
    assert identity.member_kind == "EC" and identity.person_kind == "PHYSIQUE"


@pytest.mark.asyncio
async def test_pp_contextual_mismatch_is_warning_and_raw_is_preserved(db_session, test_admin_user):
    content = _xlsx(["N° Ordre", "Nom", "Statut", "NIF"], [["EC/18.00079", "DUPONT", "indépendant", "SEC/22.00088"]])
    outcome = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "bad-context.xlsx", content, "personnes_physiques", "2026", date(2026, 9, 1))
    snapshot = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.source_import_id == outcome.imp.id))).scalar_one()
    row = (await db_session.execute(select(TableauSourceRow).where(TableauSourceRow.import_id == outcome.imp.id))).scalar_one()
    assert snapshot.nif is None
    assert row.raw_data["NIF"] == "SEC/22.00088"
    assert "SEC" in str(row.normalization_errors)


@pytest.mark.asyncio
async def test_insurance_ec_and_sec_are_rattachees_without_dossier(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom"], [["EC/18.00090", "DUPONT"]])
    pm = _xlsx(["N° Ordre", "Société"], [["SEC/18.00091", "SOCIETE"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ass-pp.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ass-pm.xlsx", pm, "personnes_morales", "2026", date(2026, 9, 1))
    content = _xlsx(["Membre", "Déclaré", "Souscrit", "Fin couverture", "Année de souscription", "Assureur", "Période"], [["EC/18.00090", "Oui", "Oui", date(2027, 12, 31), 2026, "  Assureur X  ", "annuelle"], ["SEC/18.00091", "Oui", "Non", date(2025, 12, 31), 2026, "Assureur Y", "annuelle"]])
    outcome = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "assurances.xlsx", content, "assurances", "2026", date(2026, 9, 2))
    rows = (await db_session.execute(select(TableauInsuranceDeclaration).where(TableauInsuranceDeclaration.source_import_id == outcome.imp.id).order_by(TableauInsuranceDeclaration.id))).scalars().all()
    assert [row.member_identity_id is not None for row in rows] == [True, True]
    assert rows[0].declare_normalise is True and rows[0].souscrit_normalise is True
    assert rows[0].assureur_normalise == "assureur x" and rows[0].periode_normalisee == "annuelle"
    assert (await db_session.execute(select(TableauDossier).where(TableauDossier.import_id == outcome.imp.id))).scalars().all() == []


@pytest.mark.asyncio
async def test_insurance_orphan_and_multiple_history_are_preserved(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom"], [["EC/18.00092", "DUPONT"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ass-pp2.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    headers = ["Membre", "Déclaré", "Souscrit", "Fin couverture", "Année de souscription", "Assureur"]
    first = _xlsx(headers, [["EC/18.00092", "Oui", "Oui", date(2026, 12, 31), 2026, "A"]])
    second = _xlsx(headers, [["EC/18.00092", "Oui", "Oui", date(2027, 12, 31), 2026, "B"], ["INCONNU", "?", "?", "bad", "bad", ""]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ass-1.xlsx", first, "assurances", "2026", date(2026, 9, 2))
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ass-2.xlsx", second, "assurances", "2026", date(2026, 9, 10))
    rows = (await db_session.execute(select(TableauInsuranceDeclaration).where(TableauInsuranceDeclaration.numero_ordre_normalise == "EC/18.00092"))).scalars().all()
    orphan = (await db_session.execute(select(TableauInsuranceDeclaration).where(TableauInsuranceDeclaration.source_import_id == out.imp.id, TableauInsuranceDeclaration.numero_ordre_normalise.is_(None)))).scalar_one()
    assert len(rows) == 2 and orphan.member_identity_id is None
    assert len(await get_insurance_declarations_at_date(db_session, test_admin_user.organisation_id, "EC/18.00092", date(2026, 9, 10))) == 2


@pytest.mark.asyncio
async def test_insurance_tri_state_temporal_status(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom"], [["EC/18.00093", "DUPONT"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ass-pp3.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    headers = ["Membre", "Déclaré", "Souscrit", "Fin couverture", "Année de souscription", "Assureur"]
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "future.xlsx", _xlsx(headers, [["EC/18.00093", "Oui", "Oui", date(2027, 12, 31), 2026, "A"]]), "assurances", "2026", date(2026, 9, 2))
    assert await insurance_status_at_date(db_session, test_admin_user.organisation_id, "EC/18.00093", date(2026, 10, 1)) == "TRUE"
    assert await insurance_status_at_date(db_session, test_admin_user.organisation_id, "EC/18.00093", date(2028, 1, 1)) == "FALSE"


@pytest.mark.asyncio
async def test_preparatory_projection_is_independent_and_exposes_source_indicators(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom", "Statut", "Actif", "Assuré"], [["EC/18.00094", "DUPONT", "en cabinet", "Non", "Oui"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "proj-pp.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    ca = _xlsx(["N° d'ordre", "Membre", "Année", "Devise", "CA facturé"], [["EC/18.00094", "DUPONT", 2025, "USD", "100"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "proj-ca.xlsx", ca, "chiffres_affaires", "2026", date(2026, 9, 2))
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 3))
    row = next(item for item in projection.rows if item.numero_ordre == "EC/18.00094")
    assert row.tableau_category == "EC Cabinet" and row.actif is False
    assert row.ca_present is True and row.ca_declaration_count == 1
    assert row.insurance_status == "UNKNOWN" and row.assure_source is True


@pytest.mark.asyncio
async def test_projection_temporal_selection_and_future_exclusion(db_session, test_admin_user):
    for name, situation, phone in (("temporal-a.xlsx", date(2026, 9, 1), "A"), ("temporal-b.xlsx", date(2026, 9, 12), "B")):
        await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, name, _xlsx(["N° Ordre", "Nom", "Téléphone", "Statut"], [["EC/18.00100", "DUPONT", phone, "indépendant"]]), "personnes_physiques", "2026", situation)
    before = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 10))
    after = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 15))
    assert next(r for r in before.rows if r.numero_ordre == "EC/18.00100").source_dates["personne"] == date(2026, 9, 1)
    assert next(r for r in after.rows if r.numero_ordre == "EC/18.00100").source_dates["personne"] == date(2026, 9, 12)


@pytest.mark.asyncio
async def test_projection_same_date_is_deterministic_and_reports_ambiguity(db_session, test_admin_user):
    for name, phone in (("same-a.xlsx", "A"), ("same-b.xlsx", "B")):
        await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, name, _xlsx(["N° Ordre", "Nom", "Téléphone", "Statut"], [["EC/18.00101", "DUPONT", phone, "indépendant"]]), "personnes_physiques", "2026", date(2026, 9, 5))
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 5))
    row = next(r for r in projection.rows if r.numero_ordre == "EC/18.00101")
    assert "AMBIGUOUS_SNAPSHOT_DATE" in row.anomaly_codes
    assert row.projection_status == "WARNING"


@pytest.mark.asyncio
async def test_projection_insurance_mismatch_tri_state_and_orphans(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom", "Assuré"], [["EC/18.00102", "DUPONT", "Non"], ["EC/18.00103", "MARTIN", "Oui"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "mismatch-pp.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    headers = ["Membre", "Déclaré", "Souscrit", "Fin couverture", "Année de souscription", "Assureur"]
    insurance = _xlsx(headers, [["EC/18.00102", "Oui", "Oui", date(2027, 12, 31), 2026, "A"], ["UNKNOWN", "?", "?", None, 2026, "" ]])
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "mismatch-ass.xlsx", insurance, "assurances", "2026", date(2026, 9, 2))
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 3))
    row = next(r for r in projection.rows if r.numero_ordre == "EC/18.00102")
    assert row.insurance_status == "TRUE" and row.assure_source is False and row.insurance_source_mismatch is True
    assert len(projection.orphan_insurance) == 1 and projection.orphan_insurance[0].source_import_id == out.imp.id
    unknown = next(r for r in projection.rows if r.numero_ordre == "EC/18.00103")
    assert unknown.insurance_status == "UNKNOWN" and unknown.insurance_source_mismatch is False


@pytest.mark.asyncio
async def test_projection_keeps_inactive_and_orphan_ca_outside_member_rows(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom", "Actif", "Statut"], [["EC/18.00104", "DUPONT", "Non", "indépendant"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "inactive.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    ca = _xlsx(["N° d'ordre", "Membre", "Année", "Devise", "CA facturé"], [["UNKNOWN", "X", 2026, "USD", "10"]])
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "orphan-ca-proj.xlsx", ca, "chiffres_affaires", "2026", date(2026, 9, 2))
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 3))
    row = next(r for r in projection.rows if r.numero_ordre == "EC/18.00104")
    assert row.actif is False
    assert len(projection.orphan_ca) == 1 and projection.orphan_ca[0].source_import_id == out.imp.id


@pytest.mark.asyncio
async def test_projection_reports_identity_without_snapshot(db_session, test_admin_user):
    seed = _xlsx(["N° Ordre", "Nom"], [["EC/18.00105", "DUPONT"]])
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "seed-no-snapshot.xlsx", seed, "personnes_physiques", "2026", date(2026, 9, 1))
    import_ref = (await db_session.execute(select(TableauImport).where(TableauImport.id == out.imp.id))).scalar_one()
    identity = TableauMemberIdentity(organisation_id=test_admin_user.organisation_id, numero_ordre="EC/18.00106", numero_ordre_normalise="EC/18.00106", member_kind="EC", person_kind="PHYSIQUE", first_seen_import_id=import_ref.id, last_seen_import_id=import_ref.id)
    db_session.add(identity)
    await db_session.commit()
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 2))
    row = next(r for r in projection.rows if r.numero_ordre == "EC/18.00106")
    assert "IDENTITY_WITHOUT_SNAPSHOT" in row.anomaly_codes and row.projection_status == "BLOCKED"


def test_projection_function_has_no_official_or_historical_dependency():
    source = inspect.getsource(tableau_service.build_preparatory_tableau_at_date)
    assert all(token not in source for token in ("ExpertComptable", "experts_comptables", "TableauDossier", "CategoryChangesHistory", "ImportsHistory"))


@pytest.mark.asyncio
async def test_projection_ec_independent_category_and_context(db_session, test_admin_user):
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "proj-ind.xlsx", _xlsx(["N° Ordre", "Nom", "Statut", "NIF"], [["EC/18.00110", "DUPONT", "indépendant", "A1502382C"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 2))
    identity_id = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot.identity_id).where(TableauPersonnePhysiqueSnapshot.source_import_id == out.imp.id))).scalar_one()
    row = next(r for r in projection.rows if r.identity_id == identity_id)
    assert (row.member_kind, row.person_kind, row.tableau_category) == ("EC", "PHYSIQUE", "EC Indépendant")
    assert row.nif == "A1502382C" and row.cabinet_attache is None and row.nom_employeur is None


@pytest.mark.asyncio
async def test_projection_ec_salarie_category_and_context(db_session, test_admin_user):
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "proj-sal.xlsx", _xlsx(["N° Ordre", "Nom", "Statut", "Nom de l'employeur"], [["EC/18.00111", "MARTIN", "salarié", "FPI"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 2))
    identity_id = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot.identity_id).where(TableauPersonnePhysiqueSnapshot.source_import_id == out.imp.id))).scalar_one()
    row = next(r for r in projection.rows if r.identity_id == identity_id)
    assert (row.member_kind, row.person_kind, row.tableau_category) == ("EC", "PHYSIQUE", "EC Salarié")
    assert row.nom_employeur == "FPI" and row.cabinet_attache is None and row.nif is None


@pytest.mark.asyncio
async def test_projection_sec_category_is_presentation_only(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "proj-sec.xlsx", _xlsx(["N° Ordre", "Société"], [["SEC/18.00112", "SOCIETE"]]), "personnes_morales", "2026", date(2026, 9, 1))
    row = next(r for r in (await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 2))).rows if r.numero_ordre == "SEC/18.00112")
    assert (row.member_kind, row.person_kind, row.tableau_category, row.numero_ordre) == ("SEC", "MORALE", "Société", "SEC/18.00112")


@pytest.mark.asyncio
async def test_projection_detects_ec_with_pm_snapshot(db_session, test_admin_user):
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "conflict-pm.xlsx", _xlsx(["N° Ordre", "Société"], [["SEC/18.00113", "SOCIETE"]]), "personnes_morales", "2026", date(2026, 9, 1))
    identity = TableauMemberIdentity(organisation_id=test_admin_user.organisation_id, numero_ordre="EC/18.00114", numero_ordre_normalise="EC/18.00114", member_kind="EC", person_kind="PHYSIQUE", first_seen_import_id=out.imp.id, last_seen_import_id=out.imp.id)
    db_session.add(identity); await db_session.flush()
    snapshot = (await db_session.execute(select(TableauPersonneMoraleSnapshot).where(TableauPersonneMoraleSnapshot.source_import_id == out.imp.id))).scalar_one()
    snapshot.identity_id = identity.id; snapshot.numero_ordre = identity.numero_ordre; await db_session.commit()
    row = next(r for r in (await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 2))).rows if r.identity_id == identity.id)
    assert "EC_WITH_PM_SNAPSHOT" in row.anomaly_codes and row.projection_status == "BLOCKED" and row.member_kind == "EC"


@pytest.mark.asyncio
async def test_projection_detects_sec_with_pp_snapshot(db_session, test_admin_user):
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "conflict-pp.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00115", "DUPONT", "indépendant"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    identity = TableauMemberIdentity(organisation_id=test_admin_user.organisation_id, numero_ordre="SEC/18.00116", numero_ordre_normalise="SEC/18.00116", member_kind="SEC", person_kind="MORALE", first_seen_import_id=out.imp.id, last_seen_import_id=out.imp.id)
    db_session.add(identity); await db_session.flush()
    snapshot = (await db_session.execute(select(TableauPersonnePhysiqueSnapshot).where(TableauPersonnePhysiqueSnapshot.source_import_id == out.imp.id))).scalar_one()
    snapshot.identity_id = identity.id; snapshot.numero_ordre = identity.numero_ordre; await db_session.commit()
    row = next(r for r in (await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 2))).rows if r.identity_id == identity.id)
    assert "SEC_WITH_PP_SNAPSHOT" in row.anomaly_codes and row.projection_status == "BLOCKED" and row.member_kind == "SEC" and row.tableau_category == "Société"


@pytest.mark.asyncio
async def test_projection_isolation_between_organisations(db_session, test_admin_user):
    from app.models.organisation import Organisation
    other = Organisation(nom="Projection Other", slug="projection-other", is_active=True)
    db_session.add(other); await db_session.flush()
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "iso-a.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00117", "A", "indépendant"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    await import_source_snapshot(db_session, test_admin_user, other.id, "iso-b.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00117", "B", "salarié"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    a = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 2)); b = await build_preparatory_tableau_at_date(db_session, other.id, date(2026, 9, 2))
    assert [r.nom_denomination for r in a.rows if r.numero_ordre == "EC/18.00117"] == ["A"]
    assert [r.nom_denomination for r in b.rows if r.numero_ordre == "EC/18.00117"] == ["B"]
    assert all(r.organisation_id == test_admin_user.organisation_id for r in a.rows) and all(r.organisation_id == other.id for r in b.rows)


@pytest.mark.asyncio
async def test_projection_ca_future_and_multiple_currencies(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ca-proj-pp.xlsx", _xlsx(["N° Ordre", "Nom"], [["EC/18.00118", "DUPONT"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    headers = ["N° d'ordre", "Membre", "Année", "Devise", "CA facturé"]
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ca-cdf.xlsx", _xlsx(headers, [["EC/18.00118", "DUPONT", 2025, "CDF", "10"]]), "chiffres_affaires", "2026", date(2026, 9, 1))
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ca-usd.xlsx", _xlsx(headers, [["EC/18.00118", "DUPONT", 2025, "USD", "20"]]), "chiffres_affaires", "2026", date(2026, 9, 20))
    before = next(r for r in (await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 10))).rows if r.numero_ordre == "EC/18.00118")
    after = next(r for r in (await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 21))).rows if r.numero_ordre == "EC/18.00118")
    assert before.ca_declaration_count == 1 and before.derniere_date_situation_ca == date(2026, 9, 1)
    assert after.ca_declaration_count == 2 and set(after.devises_ca_connues) == {"CDF", "USD"}


@pytest.mark.asyncio
async def test_projection_explicit_insurance_true_and_false(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ins-proj-pp.xlsx", _xlsx(["N° Ordre", "Nom"], [["EC/18.00119", "A"], ["EC/18.00120", "B"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    headers = ["Membre", "Déclaré", "Souscrit", "Fin couverture", "Année de souscription", "Assureur"]
    content = _xlsx(headers, [["EC/18.00119", "Oui", "Oui", date(2027, 1, 1), 2026, "A"], ["EC/18.00120", "Oui", "Oui", date(2026, 1, 1), 2026, "B"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ins-proj.xlsx", content, "assurances", "2026", date(2026, 9, 2))
    projection = await build_preparatory_tableau_at_date(db_session, test_admin_user.organisation_id, date(2026, 9, 10))
    assert next(r for r in projection.rows if r.numero_ordre == "EC/18.00119").insurance_status == "TRUE"
    assert next(r for r in projection.rows if r.numero_ordre == "EC/18.00120").insurance_status == "FALSE"


@pytest.mark.asyncio
async def test_ca_ec_is_rattache_et_decimal_preserved(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom"], [["EC/18.00080", "DUPONT"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "pp-ca.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    content = _xlsx(["N° d'ordre", "Membre", "Actif", "Année", "Devise", "CA facturé", "CA collecté", "Date mise à jour"], [["EC/18.00080", "DUPONT", "Oui", 2025, "usd", "1 250 000,50", "1 000 000", date(2026, 9, 2)]])
    outcome = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ca.xlsx", content, "chiffres_affaires", "2026", date(2026, 9, 3))
    row = (await db_session.execute(select(TableauCaDeclaration).where(TableauCaDeclaration.source_import_id == outcome.imp.id))).scalar_one()
    assert row.member_identity_id is not None
    assert row.ca_facture == 1250000.50 and row.ca_collecte == 1000000
    assert row.devise_normalisee == "USD" and row.annee == 2025 and row.ca_present is True


@pytest.mark.asyncio
async def test_ca_sec_orphan_and_invalid_number_do_not_create_identity(db_session, test_admin_user):
    content = _xlsx(["N° d'ordre", "Membre", "Année", "Devise", "CA facturé"], [["SEC/18.00081", "SOCIETE", 2025, "EUR", "10,00"], ["", "ORPHELIN", "bad", "???", "x"]])
    outcome = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "ca-orphans.xlsx", content, "chiffres_affaires", "2026", date(2026, 9, 4))
    declarations = (await db_session.execute(select(TableauCaDeclaration).where(TableauCaDeclaration.source_import_id == outcome.imp.id).order_by(TableauCaDeclaration.id))).scalars().all()
    assert len(declarations) == 2
    assert declarations[0].member_identity_id is None and declarations[0].numero_ordre_normalise == "SEC/18.00081"
    assert declarations[1].member_identity_id is None and declarations[1].annee is None
    assert (await db_session.execute(select(TableauMemberIdentity).where(TableauMemberIdentity.numero_ordre == "SEC/18.00081"))).scalars().all() == []


@pytest.mark.asyncio
async def test_ca_history_duplicates_and_temporal_projection(db_session, test_admin_user):
    pp = _xlsx(["N° Ordre", "Nom"], [["EC/18.00082", "DUPONT"]])
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "pp-ca2.xlsx", pp, "personnes_physiques", "2026", date(2026, 9, 1))
    headers = ["N° d'ordre", "Membre", "Année", "Devise", "CA facturé", "CA collecté"]
    for name, situation, amount, rows in (("ca-a.xlsx", date(2026, 9, 5), "1000", 1), ("ca-b.xlsx", date(2026, 9, 10), "1200", 2)):
        values = [["EC/18.00082", "DUPONT", 2025, "USD", amount, amount] for _ in range(rows)]
        await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, name, _xlsx(headers, values), "chiffres_affaires", "2026", situation)
    observations = await get_ca_declarations_at_date(db_session, test_admin_user.organisation_id, "EC/18.00082", date(2026, 9, 10))
    assert len(observations) == 3
    assert await ca_present_at_date(db_session, test_admin_user.organisation_id, "EC/18.00082", date(2026, 9, 10)) is True
    source_rows = (await db_session.execute(select(TableauSourceRow).where(TableauSourceRow.import_id == observations[-1].source_import_id))).scalars().all()
    assert any("Doublon exact" in str(row.normalization_errors) for row in source_rows)


def test_tableau_import_has_no_official_expert_dependency():
    assert not any("experts_comptables" in str(f.target_fullname) for f in TableauImport.__table__.foreign_keys)
    assert not any("experts_comptables" in str(f.target_fullname) for f in TableauSourceRow.__table__.foreign_keys)


def test_multisource_pipeline_has_no_official_or_legacy_import_side_effects():
    source = inspect.getsource(tableau_service.import_source_snapshot)
    assert "ExpertComptable" not in source
    assert "CategoryChangesHistory" not in source
    assert "ImportsHistory" not in source
    assert "TableauDossier(" not in source
