from __future__ import annotations

from datetime import date
import re

import pytest
from sqlalchemy import event, func, select

from app.models.expert_comptable import ExpertComptable
from app.modules.tableau.actualisation_service import (
    create_tableau_actualisation,
    get_current_tableau_actualisation,
)
from app.modules.tableau.models import (
    TableauActualisationInput,
    TableauActualisationRow,
    TableauCaDeclaration,
    TableauMemberIdentity,
    TableauReferenceMember,
)
from app.modules.tableau.official_reference import capture_official_snapshot
from app.modules.tableau.service import import_source_snapshot
from test_tableau_multisource import _xlsx


async def _official(
    db,
    *,
    numero: str,
    name: str,
    phone: str | None = None,
    email: str | None = None,
    type_ec: str = "EC",
) -> ExpertComptable:
    expert = ExpertComptable(
        numero_ordre=numero,
        nom_denomination=name,
        telephone=phone,
        email=email,
        type_ec=type_ec,
        categorie_personne="Personne Morale" if type_ec == "SEC" else "Personne Physique",
        active=True,
    )
    db.add(expert)
    await db.commit()
    await db.refresh(expert)
    return expert


async def _actualisation_row(db, actualisation_id: int, numero: str) -> TableauActualisationRow:
    return (await db.execute(
        select(TableauActualisationRow).where(
            TableauActualisationRow.actualisation_id == actualisation_id,
            TableauActualisationRow.numero_ordre == numero,
        )
    )).scalar_one()


@pytest.mark.asyncio
async def test_snapshot_is_explicit_national_and_keeps_legacy_order_without_province(db_session, test_admin_user):
    expert = await _official(
        db_session,
        numero="LT/09001",
        name="EXPERT HISTORIQUE",
        phone="0810000001",
    )

    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    frozen = (await db_session.execute(select(TableauReferenceMember).where(
        TableauReferenceMember.snapshot_id == snapshot.id,
        TableauReferenceMember.official_expert_id == expert.id,
    ))).scalar_one()

    assert snapshot.scope_type == "NATIONAL"
    assert snapshot.scope_definition_json["include_without_province"] is True
    assert snapshot.sealed_at is not None
    assert frozen.numero_ordre == "LT/09001"
    assert frozen.province_attache is None
    assert frozen.official_values["telephone"] == "0810000001"


@pytest.mark.asyncio
async def test_official_without_any_new_source_is_kept_as_official_only(db_session, test_admin_user):
    expert = await _official(
        db_session,
        numero="EC/26.09002",
        name="OFFICIEL SANS IMPORT",
        phone="0810000002",
    )
    snapshot = await capture_official_snapshot(db_session, test_admin_user)

    actualisation = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 1, 2),
        reference_snapshot_id=snapshot.id,
    )
    row = (await db_session.execute(select(TableauActualisationRow).where(
        TableauActualisationRow.actualisation_id == actualisation.id,
        TableauActualisationRow.official_expert_id == expert.id,
    ))).scalar_one()

    assert row.proposal_status == "OFFICIAL_ONLY"
    assert row.reference_status == "MATCHED_OFFICIAL"
    assert row.official_values == row.proposed_values
    identity = (await db_session.execute(select(TableauMemberIdentity).where(
        TableauMemberIdentity.id == row.identity_id
    ))).scalar_one()
    assert identity.origin_type == "OFFICIAL"
    assert identity.first_seen_import_id is None
    assert identity.last_seen_import_id is None


@pytest.mark.asyncio
async def test_pp_exact_order_matches_official_and_materializes_field_provenance(db_session, test_admin_user):
    expert = await _official(
        db_session,
        numero="LT/09003",
        name="LEGACY MATCH",
        phone="0810000003",
    )
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    imported = await import_source_snapshot(
        db_session,
        test_admin_user,
        test_admin_user.organisation_id,
        "legacy-update.xlsx",
        _xlsx(["N° Ordre", "Nom", "Téléphone", "Statut"], [["LT/09003", "LEGACY MATCH", "0990000003", "indépendant"]]),
        "personnes_physiques",
        "2026",
        date(2026, 9, 3),
    )
    identity = (await db_session.execute(select(TableauMemberIdentity).where(
        TableauMemberIdentity.numero_ordre_normalise == "LT/09003"
    ))).scalar_one()
    assert imported.imp.status == "completed"
    assert identity.expert_comptable_id == expert.id
    assert identity.reference_status == "MATCHED_OFFICIAL"

    actualisation = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 3),
        reference_snapshot_id=snapshot.id,
    )
    row = await _actualisation_row(db_session, actualisation.id, "LT/09003")
    phone_difference = next(item for item in row.differences_json if item["field"] == "telephone")

    assert row.proposal_status == "UPDATE_PROPOSED"
    assert phone_difference == {
        "field": "telephone",
        "official_value": "0810000003",
        "proposed_value": "0990000003",
        "change": "CHANGED",
    }
    assert row.field_provenance["telephone"]["source_type"] == "PP"
    assert row.field_provenance["telephone"]["import_id"] == imported.imp.id
    assert row.field_provenance["telephone"]["file_sha256"] == imported.imp.file_sha256


@pytest.mark.asyncio
async def test_pp_address_is_proposed_without_erasing_official(db_session, test_admin_user):
    expert = await _official(db_session, numero="EC/26.09106", name="ADRESSE", phone="081")
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    imported = await import_source_snapshot(
        db_session, test_admin_user, test_admin_user.organisation_id,
        "address.xlsx", _xlsx(["N° Ordre", "Nom", "Adresse"], [[expert.numero_ordre, expert.nom_denomination, "Nouvelle adresse"]]),
        "personnes_physiques", "2026", date(2026, 9, 16),
    )
    actualisation = await create_tableau_actualisation(
        db_session, test_admin_user, organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 16), reference_snapshot_id=snapshot.id,
    )
    row = await _actualisation_row(db_session, actualisation.id, expert.numero_ordre)
    assert row.proposed_values["adresse"] == "Nouvelle adresse"
    assert row.official_values.get("adresse") is None
    assert row.field_provenance["adresse"]["import_id"] == imported.imp.id
    assert row.proposal_status == "UPDATE_PROPOSED"


@pytest.mark.asyncio
async def test_source_kind_mismatch_keeps_consolidation_and_reports_conflict(db_session, test_admin_user):
    expert = await _official(db_session, numero="SEC/26.09007", name="SEC DANS PP", type_ec="SEC")
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    await import_source_snapshot(
        db_session, test_admin_user, test_admin_user.organisation_id,
        "wrong-kind.xlsx", _xlsx(["N° Ordre", "Nom", "Téléphone"], [[expert.numero_ordre, expert.nom_denomination, "099"]]),
        "personnes_physiques", "2026", date(2026, 9, 7),
    )
    actualisation = await create_tableau_actualisation(
        db_session, test_admin_user, organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 7), reference_snapshot_id=snapshot.id,
    )
    row = await _actualisation_row(db_session, actualisation.id, expert.numero_ordre)
    assert row.proposal_status == "CONFLICT"
    assert row.proposed_values["telephone"] == "099"
    assert any("incompatible" in str(item.get("message", "")).lower() for item in row.anomalies_json)


@pytest.mark.asyncio
async def test_new_pp_identity_stays_outside_official_registry(db_session, test_admin_user):
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    before = (await db_session.execute(select(func.count()).select_from(ExpertComptable))).scalar_one()
    imported = await import_source_snapshot(
        db_session,
        test_admin_user,
        test_admin_user.organisation_id,
        "new-identity.xlsx",
        _xlsx(["N° Ordre", "Nom", "Statut"], [["EC/26.09004", "NOUVELLE IDENTITE UNIQUE", "salarié"]]),
        "personnes_physiques",
        "2026",
        date(2026, 9, 4),
    )
    identity = (await db_session.execute(select(TableauMemberIdentity).where(
        TableauMemberIdentity.last_seen_import_id == imported.imp.id
    ))).scalar_one()
    assert identity.expert_comptable_id is None
    assert identity.reference_status == "ABSENT_DU_REFERENTIEL"

    actualisation = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 4),
        reference_snapshot_id=snapshot.id,
    )
    row = await _actualisation_row(db_session, actualisation.id, "EC/26.09004")
    after = (await db_session.execute(select(func.count()).select_from(ExpertComptable))).scalar_one()

    assert row.reference_status == "ABSENT_DU_REFERENTIEL"
    assert row.proposal_status == "NEW_IDENTITY"
    assert row.official_values == {}
    assert after == before


@pytest.mark.asyncio
async def test_duplicate_normalized_official_order_never_auto_matches(db_session, test_admin_user):
    first = await _official(db_session, numero="EC/26.09005", name="AMBIGU A")
    second = await _official(db_session, numero=" ec/26.09005 ", name="AMBIGU B")
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    imported = await import_source_snapshot(
        db_session,
        test_admin_user,
        test_admin_user.organisation_id,
        "ambiguous.xlsx",
        _xlsx(["N° Ordre", "Nom"], [["EC/26.09005", "SOURCE AMBIGUE"]]),
        "personnes_physiques",
        "2026",
        date(2026, 9, 5),
    )
    identity = (await db_session.execute(select(TableauMemberIdentity).where(
        TableauMemberIdentity.last_seen_import_id == imported.imp.id
    ))).scalar_one()

    assert identity.reference_status == "AMBIGUOUS"
    assert identity.expert_comptable_id is None
    assert set(identity.reference_match_metadata["candidate_official_ids"]) == {str(first.id), str(second.id)}

    actualisation = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 5),
        reference_snapshot_id=snapshot.id,
    )
    source_row = (await db_session.execute(select(TableauActualisationRow).where(
        TableauActualisationRow.actualisation_id == actualisation.id,
        TableauActualisationRow.identity_id == identity.id,
    ))).scalar_one()
    assert source_row.proposal_status == "AMBIGUOUS_MATCH"
    assert source_row.official_expert_id is None


@pytest.mark.asyncio
async def test_revision_is_append_only_and_freezes_inputs_hashes(db_session, test_admin_user):
    await _official(
        db_session,
            numero="EC/26.09206",
        name="REVISION TEST",
        phone="0810000006",
    )
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    pp = await import_source_snapshot(
        db_session,
        test_admin_user,
        test_admin_user.organisation_id,
        "revision-pp.xlsx",
            _xlsx(["N° Ordre", "Nom", "Téléphone"], [["EC/26.09206", "REVISION TEST", "0990000006"]]),
        "personnes_physiques",
        "2026",
        date(2026, 9, 6),
    )
    first = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 6),
        reference_snapshot_id=snapshot.id,
    )
    first_row_before = await _actualisation_row(db_session, first.id, "EC/26.09206")
    assert "chiffres_affaires" not in first_row_before.proposed_values

    ca = await import_source_snapshot(
        db_session,
        test_admin_user,
        test_admin_user.organisation_id,
        "revision-ca.xlsx",
        _xlsx(
            ["N° d'ordre", "Membre", "Année", "Devise", "CA facturé"],
                [["EC/26.09206", "REVISION TEST", 2026, "USD", "1000"]],
        ),
        "chiffres_affaires",
        "2026",
        date(2026, 9, 6),
    )
    second = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 6),
        reference_snapshot_id=snapshot.id,
    )
    first_row_after = await _actualisation_row(db_session, first.id, "EC/26.09206")
    second_row = await _actualisation_row(db_session, second.id, "EC/26.09206")
    first_inputs = list((await db_session.execute(select(TableauActualisationInput).where(
        TableauActualisationInput.actualisation_id == first.id
    ))).scalars().all())
    second_inputs = list((await db_session.execute(select(TableauActualisationInput).where(
        TableauActualisationInput.actualisation_id == second.id
    ))).scalars().all())
    current = await get_current_tableau_actualisation(
        db_session,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 6),
    )

    assert (first.revision_number, second.revision_number) == (1, 2)
    assert current.id == second.id
    assert first.actualized_at < second.actualized_at
    assert first_row_after.proposed_values == first_row_before.proposed_values
    assert "chiffres_affaires" not in first_row_after.proposed_values
    assert second_row.proposed_values["chiffres_affaires"][0]["ca_facture"] == "1000.00"
    assert {item.import_id for item in first_inputs} >= {pp.imp.id}
    assert ca.imp.id not in {item.import_id for item in first_inputs}
    assert {item.import_id for item in second_inputs} >= {pp.imp.id, ca.imp.id}
    assert next(item for item in second_inputs if item.import_id == ca.imp.id).file_sha256 == ca.imp.file_sha256


@pytest.mark.asyncio
async def test_same_snapshot_reproduces_old_official_values_after_registry_change(db_session, test_admin_user):
    expert = await _official(
        db_session,
        numero="EC/26.09007",
        name="REPRODUCTION",
        phone="0810000007",
    )
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    first = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 7),
        reference_snapshot_id=snapshot.id,
    )

    expert.telephone = "0999999999"
    await db_session.commit()
    second = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 7),
        reference_snapshot_id=snapshot.id,
    )
    first_row = (await db_session.execute(select(TableauActualisationRow).where(
        TableauActualisationRow.actualisation_id == first.id,
        TableauActualisationRow.official_expert_id == expert.id,
    ))).scalar_one()
    second_row = (await db_session.execute(select(TableauActualisationRow).where(
        TableauActualisationRow.actualisation_id == second.id,
        TableauActualisationRow.official_expert_id == expert.id,
    ))).scalar_one()

    assert first_row.official_values["telephone"] == "0810000007"
    assert second_row.official_values["telephone"] == "0810000007"
    assert first_row.proposed_values == second_row.proposed_values


@pytest.mark.asyncio
async def test_ca_alone_is_preserved_but_never_creates_an_identity(db_session, test_admin_user):
    snapshot = await capture_official_snapshot(db_session, test_admin_user)
    imported = await import_source_snapshot(
        db_session,
        test_admin_user,
        test_admin_user.organisation_id,
        "orphan-ca-actualisation.xlsx",
        _xlsx(
            ["N° d'ordre", "Membre", "Année", "Devise", "CA facturé"],
            [["LT/09999", "ORPHELIN CA", 2026, "USD", "500"]],
        ),
        "chiffres_affaires",
        "2026",
        date(2026, 9, 8),
    )
    declaration = (await db_session.execute(select(TableauCaDeclaration).where(
        TableauCaDeclaration.source_import_id == imported.imp.id
    ))).scalar_one()
    identity = (await db_session.execute(select(TableauMemberIdentity).where(
        TableauMemberIdentity.organisation_id == test_admin_user.organisation_id,
        TableauMemberIdentity.numero_ordre_normalise == "LT/09999",
    ))).scalar_one_or_none()
    assert declaration.member_identity_id is None
    assert declaration.ca_present is True
    assert identity is None

    actualisation = await create_tableau_actualisation(
        db_session,
        test_admin_user,
        organisation_id=test_admin_user.organisation_id,
        date_situation=date(2026, 9, 8),
        reference_snapshot_id=snapshot.id,
    )
    assert actualisation.metadata_json["orphan_ca_count"] >= 1


@pytest.mark.asyncio
async def test_tableau_workflow_never_emits_dml_on_official_registry(db_session, test_admin_user):
    await _official(
        db_session,
        numero="EC/26.09008",
        name="READ ONLY SENTINEL",
        phone="0810000008",
    )
    statements: list[str] = []
    sync_engine = db_session.bind.sync_engine

    def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(sync_engine, "before_cursor_execute", capture_statement)
    try:
        snapshot = await capture_official_snapshot(db_session, test_admin_user)
        await import_source_snapshot(
            db_session,
            test_admin_user,
            test_admin_user.organisation_id,
            "read-only-sentinel.xlsx",
            _xlsx(["N° Ordre", "Nom", "Téléphone"], [["EC/26.09008", "READ ONLY SENTINEL", "0990000008"]]),
            "personnes_physiques",
            "2026",
            date(2026, 9, 9),
        )
        await create_tableau_actualisation(
            db_session,
            test_admin_user,
            organisation_id=test_admin_user.organisation_id,
            date_situation=date(2026, 9, 9),
            reference_snapshot_id=snapshot.id,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture_statement)

    official_dml = [
        statement for statement in statements
        if "experts_comptables" in statement.casefold()
        and re.match(r"^\s*(insert|update|delete)\b", statement, flags=re.IGNORECASE)
    ]
    assert official_dml == []
