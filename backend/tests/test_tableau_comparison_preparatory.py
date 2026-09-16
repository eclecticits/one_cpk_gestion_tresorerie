from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.tableau.comparison_service import compare_preparatory_to_historical
from app.modules.tableau.models import TableauDossier, TableauImport, TableauMemberIdentity, TableauPersonneMoraleSnapshot, TableauSourceRow
from app.modules.tableau.service import build_preparatory_tableau_at_date, import_source_snapshot

from test_tableau_multisource import _xlsx


async def _historical(db, user, *, organisation_id, numero, nom, categorie="EC Indépendant", situation=date(2026, 9, 1)):
    imp = TableauImport(organisation_id=organisation_id, user_id=user.id, exercice="2026", date_situation=situation, source_type="tableau", file_name="historique.xlsx", status="completed")
    db.add(imp); await db.flush()
    db.add(TableauDossier(organisation_id=organisation_id, import_id=imp.id, exercice="2026", numero_ordre=numero, nom=nom, categorie=categorie))
    await db.commit()
    return imp


@pytest.mark.asyncio
async def test_comparison_populations_fields_and_date_context(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "prep.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00200", "DUPONT", "indépendant"], ["EC/18.00201", "PREP ONLY", "salarié"]]), "personnes_physiques", "2026", date(2026, 9, 2))
    historical = await _historical(db_session, test_admin_user, organisation_id=test_admin_user.organisation_id, numero="EC/18.00200", nom="DUPONT", situation=date(2026, 9, 1))
    result = await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 3), historical.id)
    statuses = {row.numero_ordre: row.presence_status for row in result.rows}
    assert statuses["EC/18.00200"] == "MATCHED" and statuses["EC/18.00201"] == "PREPARATORY_ONLY"
    assert result.historical_date_situation == date(2026, 9, 1)
    assert any(d.difference_code == "DATE_CONTEXT_MISMATCH" for row in result.rows for d in row.differences)


@pytest.mark.asyncio
async def test_comparison_historical_only_and_category_equivalence(db_session, test_admin_user):
    historical = await _historical(db_session, test_admin_user, organisation_id=test_admin_user.organisation_id, numero="SEC/18.00202", nom="SOCIETE", categorie="SEC")
    result = await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 1), historical.id)
    assert result.total_historical_only == 1 and next(r for r in result.rows if r.numero_ordre == "SEC/18.00202").presence_status == "HISTORICAL_ONLY"


@pytest.mark.asyncio
async def test_comparison_blocked_projection_and_unknown_category_are_preserved(db_session, test_admin_user):
    out = await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "blocked.xlsx", _xlsx(["N° Ordre", "Société"], [["SEC/18.00203", "BAD"]]), "personnes_morales", "2026", date(2026, 9, 1))
    identity = TableauMemberIdentity(organisation_id=test_admin_user.organisation_id, numero_ordre="EC/18.00203", numero_ordre_normalise="EC/18.00203", member_kind="EC", person_kind="PHYSIQUE", first_seen_import_id=out.imp.id, last_seen_import_id=out.imp.id)
    db_session.add(identity); await db_session.flush()
    snapshot = (await db_session.execute(select(TableauPersonneMoraleSnapshot).where(TableauPersonneMoraleSnapshot.source_import_id == out.imp.id))).scalar_one()
    snapshot.identity_id = identity.id; snapshot.numero_ordre = identity.numero_ordre; await db_session.commit()
    historical = await _historical(db_session, test_admin_user, organisation_id=test_admin_user.organisation_id, numero="EC/18.00203", nom="BAD", categorie="EC Indépendant")
    result = await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 2), historical.id)
    row = next(row for row in result.rows if row.numero_ordre == "EC/18.00203")
    assert row.comparison_status == "BLOCKED" and row.preparatory_projection_status == "BLOCKED"
    assert row.preparatory_category == "UNKNOWN" and row.historical_category == "EC Indépendant"


@pytest.mark.asyncio
async def test_comparison_rejects_historical_import_from_other_organisation(db_session, test_admin_user, test_organisation):
    from app.models.organisation import Organisation
    other = Organisation(nom="Comparison Other", slug="comparison-other", is_active=True)
    db_session.add(other); await db_session.flush()
    historical = await _historical(db_session, test_admin_user, organisation_id=other.id, numero="EC/18.00204", nom="OTHER")
    with pytest.raises(HTTPException):
        await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 1), historical.id)


@pytest.mark.asyncio
async def test_comparison_does_not_write_projection_or_source_rows(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "readonly.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00205", "DUPONT", "indépendant"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    historical = await _historical(db_session, test_admin_user, organisation_id=test_admin_user.organisation_id, numero="EC/18.00205", nom="DIFFERENT")
    before = (await db_session.execute(select(TableauSourceRow).where(TableauSourceRow.organisation_id == test_admin_user.organisation_id))).scalars().all()
    result = await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 1), historical.id)
    after = (await db_session.execute(select(TableauSourceRow).where(TableauSourceRow.organisation_id == test_admin_user.organisation_id))).scalars().all()
    compared = next(row for row in result.rows if row.numero_ordre == "EC/18.00205")
    assert len(before) == len(after) and compared.differences[0].difference_code == "NAME_MISMATCH"


@pytest.mark.asyncio
async def test_comparison_matches_only_by_number_and_detects_name_category_differences(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "matching.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00206", "SAME", "indépendant"], ["EC/18.00207", "SAME", "salarié"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    historical = TableauImport(organisation_id=test_admin_user.organisation_id, user_id=test_admin_user.id, exercice="2026", date_situation=date(2026, 9, 1), source_type="tableau", file_name="matching-h.xlsx", status="completed")
    db_session.add(historical); await db_session.flush()
    db_session.add_all([
        TableauDossier(organisation_id=test_admin_user.organisation_id, import_id=historical.id, exercice="2026", numero_ordre="EC/18.00206", nom="DIFFERENT", categorie="Société"),
        TableauDossier(organisation_id=test_admin_user.organisation_id, import_id=historical.id, exercice="2026", numero_ordre="EC/18.00999", nom="SAME", categorie="EC Salarié"),
    ]); await db_session.commit()
    result = await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 1), historical.id)
    matched = next(r for r in result.rows if r.numero_ordre == "EC/18.00206")
    assert matched.presence_status == "MATCHED" and {d.difference_code for d in matched.differences} == {"NAME_MISMATCH", "CATEGORY_MISMATCH"}
    assert next(r for r in result.rows if r.numero_ordre == "EC/18.00207").presence_status == "PREPARATORY_ONLY"
    assert next(r for r in result.rows if r.numero_ordre == "EC/18.00999").presence_status == "HISTORICAL_ONLY"


@pytest.mark.asyncio
async def test_comparison_detects_duplicate_historical_number_without_silent_overwrite(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "dup-prep.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00208", "DUP", "indépendant"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    historical = TableauImport(organisation_id=test_admin_user.organisation_id, user_id=test_admin_user.id, exercice="2026", date_situation=date(2026, 9, 1), source_type="tableau", file_name="dup-h.xlsx", status="completed")
    db_session.add(historical); await db_session.flush()
    db_session.add_all([TableauDossier(organisation_id=test_admin_user.organisation_id, import_id=historical.id, exercice="2026", numero_ordre="EC/18.00208", nom="A", categorie="EC Indépendant"), TableauDossier(organisation_id=test_admin_user.organisation_id, import_id=historical.id, exercice="2026", numero_ordre=" ec/18.00208 ", nom="B", categorie="EC Indépendant")]); await db_session.commit()
    result = await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 1), historical.id)
    row = next(r for r in result.rows if r.numero_ordre == "EC/18.00208")
    assert result.historical_duplicate_keys == 1 and any(d.difference_code == "HISTORICAL_DUPLICATE_KEY" for d in row.differences)


@pytest.mark.asyncio
async def test_comparison_statistics_invariants(db_session, test_admin_user):
    await import_source_snapshot(db_session, test_admin_user, test_admin_user.organisation_id, "stats-prep.xlsx", _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/18.00209", "A", "indépendant"]]), "personnes_physiques", "2026", date(2026, 9, 1))
    historical = await _historical(db_session, test_admin_user, organisation_id=test_admin_user.organisation_id, numero="EC/18.00210", nom="H")
    result = await compare_preparatory_to_historical(db_session, test_admin_user.organisation_id, date(2026, 9, 1), historical.id)
    assert result.total_matched + result.total_preparatory_only == result.total_preparatory
    assert result.total_matched + result.total_historical_only == result.total_historical
