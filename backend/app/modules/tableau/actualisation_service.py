"""Actualisations immuables du Tableau préparatoire.

Le service ne relit jamais les valeurs courantes du référentiel pour construire
une situation. Il utilise exclusivement un snapshot officiel scellé et la liste
figée des imports disponibles au moment de l'actualisation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expert_comptable import ExpertComptable
from app.models.user import User
from .audit import record_tableau_audit
from .models import (
    TableauActualisation,
    TableauActualisationInput,
    TableauActualisationRow,
    TableauCaDeclaration,
    TableauImport,
    TableauInsuranceDeclaration,
    TableauMemberIdentity,
    TableauPersonneMoraleSnapshot,
    TableauPersonnePhysiqueSnapshot,
    TableauReferenceMember,
    TableauReferenceSnapshot,
    TableauSourceRow,
)
from .official_reference import normalize_official_order
from .service import _insurance_status_from_declarations


RULESET_VERSION = "tableau-preparatoire-v1"
RULESET: dict[str, Any] = {
    "official_baseline": "sealed_reference_snapshot",
    "source_priority": ["OFFICIAL", "PP_OR_PM", "CA", "ASSURANCE"],
    "identity_match": {
        "automatic": "unique_normalized_order_only",
        "suggestions_only": ["name", "email", "phone"],
    },
    "latest_source_value": "max(date_situation, import_created_at, row_id)",
    "missing_source_value": "keep_official_value",
    "official_absence_from_imports": "keep_as_OFFICIAL_ONLY",
}

DETAILED_SOURCE_TYPES = {
    "personnes_physiques",
    "personnes_morales",
    "chiffres_affaires",
    "assurances",
}


async def get_current_tableau_actualisation(
    db: AsyncSession,
    *,
    organisation_id: int,
    date_situation: date,
) -> TableauActualisation | None:
    """Retourne la dernière révision terminée, sans marqueur mutable ``is_current``."""
    return (await db.execute(
        select(TableauActualisation)
        .where(
            TableauActualisation.organisation_id == organisation_id,
            TableauActualisation.date_situation == date_situation,
            TableauActualisation.status == "completed",
        )
        .order_by(TableauActualisation.revision_number.desc())
        .limit(1)
    )).scalars().first()


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return value


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return " ".join(left.casefold().split()) == " ".join(right.casefold().split())
    return _json_value(left) == _json_value(right)


def _identity_kinds(reference: TableauReferenceMember) -> tuple[str, str]:
    values = reference.official_values or {}
    official_kind = str(values.get("type_ec") or "").strip().upper()
    category = str(values.get("categorie_personne") or "").strip().casefold()
    is_company = official_kind == "SEC" or "morale" in category
    return ("SEC", "MORALE") if is_company else ("EC", "PHYSIQUE")


def _source_rank(row: Any, imports_by_id: dict[int, TableauImport]) -> tuple[date, datetime, int]:
    source_import = imports_by_id[row.source_import_id]
    return row.date_situation, source_import.created_at, row.id


def _input_provenance(row: Any, source_type: str, inputs_by_import: dict[int, TableauActualisationInput]) -> dict[str, Any]:
    frozen_input = inputs_by_import[row.source_import_id]
    return {
        "source_type": source_type,
        "import_id": row.source_import_id,
        "file_sha256": frozen_input.file_sha256,
        "date_situation": row.date_situation.isoformat(),
        "source_row_id": row.source_row_id,
    }


def _candidate_signals(
    source_values: dict[str, Any],
    references: Iterable[TableauReferenceMember],
) -> dict[str, list[str]]:
    source_name = " ".join(str(source_values.get("name") or "").casefold().split())
    source_email = str(source_values.get("email") or "").strip().casefold()
    source_phone = "".join(ch for ch in str(source_values.get("phone") or "") if ch.isdigit())
    candidates: dict[str, set[str]] = {"name": set(), "email": set(), "phone": set()}
    for reference in references:
        values = reference.official_values or {}
        official_name = " ".join(str(values.get("nom_denomination") or "").casefold().split())
        official_email = str(values.get("email") or "").strip().casefold()
        official_phone = "".join(ch for ch in str(values.get("telephone") or "") if ch.isdigit())
        if source_name and source_name == official_name:
            candidates["name"].add(str(reference.official_expert_id))
        if source_email and source_email == official_email:
            candidates["email"].add(str(reference.official_expert_id))
        if source_phone and source_phone == official_phone:
            candidates["phone"].add(str(reference.official_expert_id))
    return {signal: sorted(ids) for signal, ids in candidates.items() if ids}


async def create_tableau_actualisation(
    db: AsyncSession,
    user: User,
    *,
    organisation_id: int,
    date_situation: date,
    reference_snapshot_id: int,
) -> TableauActualisation:
    """Matérialise une nouvelle révision sans modifier les révisions précédentes.

    ``actualized_at`` constitue automatiquement le cutoff technique : seuls les
    imports déjà disponibles, applicables à ``date_situation``, sont figés comme
    entrées. Le seul paramètre temporel métier est donc ``date_situation``.
    """
    actualized_at = datetime.now(timezone.utc)
    reference_snapshot = (await db.execute(
        select(TableauReferenceSnapshot).where(
            TableauReferenceSnapshot.id == reference_snapshot_id,
        )
    )).scalar_one_or_none()
    if reference_snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot officiel introuvable")
    if reference_snapshot.sealed_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Le snapshot officiel n'est pas scellé")

    # Deux demandes simultanées pour la même situation doivent recevoir deux
    # numéros distincts. Le verrou transactionnel est stable et n'ajoute aucune
    # table technique au domaine.
    revision_lock_key = ((organisation_id & 0x7FFFFFFF) << 32) | date_situation.toordinal()
    await db.execute(select(func.pg_advisory_xact_lock(revision_lock_key)))
    previous_revision = (await db.execute(
        select(TableauActualisation)
        .where(
            TableauActualisation.organisation_id == organisation_id,
            TableauActualisation.date_situation == date_situation,
        )
        .order_by(TableauActualisation.revision_number.desc())
        .with_for_update()
        .limit(1)
    )).scalars().first()
    revision_number = (previous_revision.revision_number if previous_revision else 0) + 1

    selected_imports = list((await db.execute(
        select(TableauImport)
        .where(
            TableauImport.organisation_id == organisation_id,
            TableauImport.source_type.in_(DETAILED_SOURCE_TYPES),
            TableauImport.status.in_(("completed", "partial")),
            TableauImport.date_situation <= date_situation,
            TableauImport.created_at <= actualized_at,
        )
        .order_by(TableauImport.date_situation, TableauImport.created_at, TableauImport.id)
    )).scalars().all())

    actualisation = TableauActualisation(
        organisation_id=organisation_id,
        date_situation=date_situation,
        revision_number=revision_number,
        actualized_at=actualized_at,
        reference_snapshot_id=reference_snapshot.id,
        ruleset_version=RULESET_VERSION,
        ruleset_json=RULESET,
        status="processing",
        created_by=user.id,
        metadata_json={
            "knowledge_cutoff_at": actualized_at.isoformat(),
            "knowledge_cutoff_mode": "automatic_at_actualisation",
        },
    )
    db.add(actualisation)
    try:
        await db.flush()
        inputs_by_import: dict[int, TableauActualisationInput] = {}
        for source_import in selected_imports:
            frozen_input = TableauActualisationInput(
                actualisation_id=actualisation.id,
                import_id=source_import.id,
                source_type=source_import.source_type,
                date_situation=source_import.date_situation,
                file_sha256=source_import.file_sha256,
                file_name=source_import.file_name,
            )
            db.add(frozen_input)
            inputs_by_import[source_import.id] = frozen_input
        await db.flush()

        references = list((await db.execute(
            select(TableauReferenceMember)
            .where(TableauReferenceMember.snapshot_id == reference_snapshot.id)
            .order_by(TableauReferenceMember.id)
        )).scalars().all())
        current_official_ids = set((await db.execute(select(ExpertComptable.id))).scalars().all())
        identities = list((await db.execute(
            select(TableauMemberIdentity)
            .where(TableauMemberIdentity.organisation_id == organisation_id)
            .order_by(TableauMemberIdentity.id)
        )).scalars().all())

        references_by_order: dict[str, list[TableauReferenceMember]] = defaultdict(list)
        references_by_official_id: dict[Any, TableauReferenceMember] = {}
        references_by_id: dict[int, TableauReferenceMember] = {}
        for reference in references:
            references_by_order[reference.numero_ordre_normalise].append(reference)
            references_by_official_id[reference.official_expert_id] = reference
            references_by_id[reference.id] = reference

        identity_by_official_id = {
            identity.expert_comptable_id: identity
            for identity in identities
            if identity.expert_comptable_id is not None
        }
        identity_by_snapshot_official_id: dict[str, TableauMemberIdentity] = {}
        for identity in identities:
            frozen_id = (identity.reference_match_metadata or {}).get("snapshot_official_id")
            if frozen_id:
                identity_by_snapshot_official_id[str(frozen_id)] = identity

        official_identity_by_reference_id: dict[int, TableauMemberIdentity] = {}
        identities_by_order: dict[str, list[TableauMemberIdentity]] = defaultdict(list)
        for identity in identities:
            identities_by_order[identity.numero_ordre_normalise].append(identity)

        for reference in references:
            identity = identity_by_official_id.get(reference.official_expert_id)
            if identity is None:
                identity = identity_by_snapshot_official_id.get(str(reference.official_expert_id))
            exact_reference_is_unique = len(references_by_order[reference.numero_ordre_normalise]) == 1
            if identity is None and exact_reference_is_unique:
                unlinked = [
                    candidate for candidate in identities_by_order[reference.numero_ordre_normalise]
                    if candidate.expert_comptable_id is None and candidate.origin_type != "OFFICIAL"
                ]
                if len(unlinked) == 1 and reference.official_expert_id in current_official_ids:
                    identity = unlinked[0]
                    identity.expert_comptable_id = reference.official_expert_id
                    identity.reference_status = "MATCHED_OFFICIAL"
                    identity.reference_match_method = "SNAPSHOT_EXACT_ORDER"
                    identity.reference_match_metadata = {
                        "snapshot_id": reference_snapshot.id,
                        "snapshot_official_id": str(reference.official_expert_id),
                    }
                    identity_by_official_id[reference.official_expert_id] = identity
            if identity is None:
                member_kind, person_kind = _identity_kinds(reference)
                identity = TableauMemberIdentity(
                    organisation_id=organisation_id,
                    numero_ordre=reference.numero_ordre,
                    numero_ordre_normalise=reference.numero_ordre_normalise,
                    expert_comptable_id=(
                        reference.official_expert_id
                        if reference.official_expert_id in current_official_ids
                        else None
                    ),
                    member_kind=member_kind,
                    person_kind=person_kind,
                    classification_status="official",
                    reference_status="MATCHED_OFFICIAL",
                    reference_match_method="OFFICIAL_SNAPSHOT_SEED",
                    reference_match_metadata={
                        "snapshot_id": reference_snapshot.id,
                        "snapshot_official_id": str(reference.official_expert_id),
                    },
                    origin_type="OFFICIAL",
                    first_seen_at=reference_snapshot.captured_at,
                    first_seen_import_id=None,
                    last_seen_at=reference_snapshot.captured_at,
                    last_seen_import_id=None,
                )
                db.add(identity)
                identities.append(identity)
                identities_by_order[identity.numero_ordre_normalise].append(identity)
                if identity.expert_comptable_id is not None:
                    identity_by_official_id[identity.expert_comptable_id] = identity
            official_identity_by_reference_id[reference.id] = identity
        await db.flush()

        selected_import_ids = set(inputs_by_import)
        imports_by_id = {source_import.id: source_import for source_import in selected_imports}
        if selected_import_ids:
            pp_rows = list((await db.execute(select(TableauPersonnePhysiqueSnapshot).where(
                TableauPersonnePhysiqueSnapshot.source_import_id.in_(selected_import_ids)
            ))).scalars().all())
            pm_rows = list((await db.execute(select(TableauPersonneMoraleSnapshot).where(
                TableauPersonneMoraleSnapshot.source_import_id.in_(selected_import_ids)
            ))).scalars().all())
            ca_rows = list((await db.execute(select(TableauCaDeclaration).where(
                TableauCaDeclaration.source_import_id.in_(selected_import_ids)
            ))).scalars().all())
            insurance_rows = list((await db.execute(select(TableauInsuranceDeclaration).where(
                TableauInsuranceDeclaration.source_import_id.in_(selected_import_ids)
            ))).scalars().all())
            source_rows = list((await db.execute(select(TableauSourceRow).where(
                TableauSourceRow.import_id.in_(selected_import_ids)
            ))).scalars().all())
        else:
            pp_rows, pm_rows, ca_rows, insurance_rows, source_rows = [], [], [], [], []

        identity_by_id = {identity.id: identity for identity in identities}
        reference_by_identity_id: dict[int, TableauReferenceMember] = {}
        for reference_id, identity in official_identity_by_reference_id.items():
            reference_by_identity_id[identity.id] = references_by_id[reference_id]

        canonical_by_identity_id: dict[int, TableauMemberIdentity] = {}
        for identity in identities:
            reference = references_by_official_id.get(identity.expert_comptable_id)
            if reference is not None:
                canonical_by_identity_id[identity.id] = official_identity_by_reference_id[reference.id]
                continue
            matching_references = references_by_order.get(identity.numero_ordre_normalise, [])
            if len(matching_references) == 1:
                canonical_by_identity_id[identity.id] = official_identity_by_reference_id[matching_references[0].id]
            else:
                canonical_by_identity_id[identity.id] = identity
                if len(matching_references) > 1 and identity.origin_type != "OFFICIAL":
                    identity.reference_status = "AMBIGUOUS"
                    identity.reference_match_method = None
                    identity.reference_match_metadata = {
                        "snapshot_id": reference_snapshot.id,
                        "reason": "DUPLICATE_NORMALIZED_ORDER",
                        "candidate_official_ids": [str(item.official_expert_id) for item in matching_references],
                    }

        def canonical_for_id(identity_id: int | None) -> TableauMemberIdentity | None:
            if identity_id is None:
                return None
            return canonical_by_identity_id.get(identity_id) or identity_by_id.get(identity_id)

        pp_by_identity: dict[int, list[TableauPersonnePhysiqueSnapshot]] = defaultdict(list)
        pm_by_identity: dict[int, list[TableauPersonneMoraleSnapshot]] = defaultdict(list)
        ca_by_identity: dict[int, list[TableauCaDeclaration]] = defaultdict(list)
        insurance_by_identity: dict[int, list[TableauInsuranceDeclaration]] = defaultdict(list)

        for row in pp_rows:
            canonical = canonical_for_id(row.identity_id)
            if canonical is not None:
                pp_by_identity[canonical.id].append(row)
        for row in pm_rows:
            canonical = canonical_for_id(row.identity_id)
            if canonical is not None:
                pm_by_identity[canonical.id].append(row)

        canonical_ids_by_order: dict[str, set[int]] = defaultdict(set)
        for identity in canonical_by_identity_id.values():
            canonical_ids_by_order[identity.numero_ordre_normalise].add(identity.id)
        for reference_id, identity in official_identity_by_reference_id.items():
            canonical_ids_by_order[references_by_id[reference_id].numero_ordre_normalise].add(identity.id)

        orphan_ca = 0
        for row in ca_rows:
            canonical = canonical_for_id(row.member_identity_id)
            if canonical is None and row.numero_ordre_normalise:
                candidates = canonical_ids_by_order.get(row.numero_ordre_normalise, set())
                canonical = identity_by_id[next(iter(candidates))] if len(candidates) == 1 else None
            if canonical is None:
                orphan_ca += 1
            else:
                ca_by_identity[canonical.id].append(row)

        orphan_insurance = 0
        for row in insurance_rows:
            canonical = canonical_for_id(row.member_identity_id)
            if canonical is None and row.numero_ordre_normalise:
                candidates = canonical_ids_by_order.get(row.numero_ordre_normalise, set())
                canonical = identity_by_id[next(iter(candidates))] if len(candidates) == 1 else None
            if canonical is None:
                orphan_insurance += 1
            else:
                insurance_by_identity[canonical.id].append(row)

        source_row_by_id = {row.id: row for row in source_rows}
        row_identities: dict[int, TableauMemberIdentity] = {
            identity.id: identity for identity in official_identity_by_reference_id.values()
        }
        for snapshot_row in [*pp_rows, *pm_rows]:
            canonical = canonical_for_id(snapshot_row.identity_id)
            if canonical is not None:
                row_identities[canonical.id] = canonical

        status_counts: Counter[str] = Counter()
        for identity in sorted(row_identities.values(), key=lambda item: (item.numero_ordre_normalise, item.id)):
            reference = reference_by_identity_id.get(identity.id)
            official_values = _json_value(dict(reference.official_values or {})) if reference else {}
            proposed_values = dict(official_values)
            provenance: dict[str, Any] = {}
            if reference:
                for field_name in official_values:
                    provenance[field_name] = {
                        "source_type": "OFFICIAL_SNAPSHOT",
                        "snapshot_id": reference_snapshot.id,
                        "reference_member_id": reference.id,
                        "row_checksum": reference.row_checksum,
                    }

            pp_candidates = pp_by_identity.get(identity.id, [])
            pm_candidates = pm_by_identity.get(identity.id, [])
            ca_candidates = ca_by_identity.get(identity.id, [])
            insurance_candidates = insurance_by_identity.get(identity.id, [])
            has_new_sources = bool(pp_candidates or pm_candidates or ca_candidates or insurance_candidates)
            anomalies: list[dict[str, Any]] = []
            conflict = False
            blocked = False

            if pp_candidates and pm_candidates:
                conflict = True
                anomalies.append({"code": "MULTIPLE_PERSON_KINDS", "severity": "ERROR"})
            if reference and len(references_by_order[reference.numero_ordre_normalise]) > 1:
                # L'identité officielle reste certaine par son UUID ; seule une
                # identité source portant ce numéro ne peut être auto-rattachée.
                anomalies.append({"code": "DUPLICATE_OFFICIAL_NORMALIZED_ORDER", "severity": "WARNING"})

            def apply_value(field_name: str, value: Any, source_row: Any, source_type: str) -> None:
                if value is None or value == "":
                    return
                proposed_values[field_name] = _json_value(value)
                provenance[field_name] = _input_provenance(source_row, source_type, inputs_by_import)

            latest_person_row: Any | None = None
            latest_person_type: str | None = None
            if pp_candidates:
                latest_person_row = max(pp_candidates, key=lambda item: _source_rank(item, imports_by_id))
                latest_person_type = "PP"
                same_date = [item for item in pp_candidates if item.date_situation == latest_person_row.date_situation]
                if len(same_date) > 1:
                    conflict = True
                    anomalies.append({"code": "AMBIGUOUS_PP_SNAPSHOT_DATE", "severity": "ERROR"})
                apply_value("nom_denomination", latest_person_row.nom, latest_person_row, "PP")
                apply_value("sexe", latest_person_row.sexe, latest_person_row, "PP")
                apply_value("telephone", latest_person_row.telephone, latest_person_row, "PP")
                apply_value("email", latest_person_row.email, latest_person_row, "PP")
                apply_value("statut_professionnel", latest_person_row.statut_normalise, latest_person_row, "PP")
                apply_value("cabinet_attache", latest_person_row.cabinet_attache, latest_person_row, "PP")
                apply_value("nif", latest_person_row.nif, latest_person_row, "PP")
                apply_value("nom_employeur", latest_person_row.nom_employeur, latest_person_row, "PP")
                apply_value("active", latest_person_row.actif, latest_person_row, "PP")
                apply_value("date_naissance", latest_person_row.date_naissance, latest_person_row, "PP")
                apply_value("ville", latest_person_row.ville, latest_person_row, "PP")
                apply_value("adresse", latest_person_row.adresse, latest_person_row, "PP")
                apply_value("assure_synthetique", latest_person_row.assure_synthetique, latest_person_row, "PP")
            if pm_candidates:
                selected_pm = max(pm_candidates, key=lambda item: _source_rank(item, imports_by_id))
                if latest_person_row is None or _source_rank(selected_pm, imports_by_id) > _source_rank(latest_person_row, imports_by_id):
                    latest_person_row = selected_pm
                    latest_person_type = "PM"
                same_date = [item for item in pm_candidates if item.date_situation == selected_pm.date_situation]
                if len(same_date) > 1:
                    conflict = True
                    anomalies.append({"code": "AMBIGUOUS_PM_SNAPSHOT_DATE", "severity": "ERROR"})
                apply_value("nom_denomination", selected_pm.societe, selected_pm, "PM")
                apply_value("raison_sociale", selected_pm.societe, selected_pm, "PM")
                apply_value("telephone", selected_pm.telephone, selected_pm, "PM")
                apply_value("email", selected_pm.email, selected_pm, "PM")
                apply_value("nif", selected_pm.numero_impot, selected_pm, "PM")
                apply_value("ville", selected_pm.ville, selected_pm, "PM")
                apply_value("adresse", selected_pm.adresse, selected_pm, "PM")
                apply_value("assure_synthetique", selected_pm.assure_synthetique, selected_pm, "PM")

            if latest_person_row is not None:
                source_row = source_row_by_id.get(latest_person_row.source_row_id)
                for error in (source_row.normalization_errors if source_row else []) or []:
                    anomalies.append(_json_value(error))
                    if str(error.get("severity") or "").upper() == "BLOCKING":
                        blocked = True
                if reference:
                    expected_kind, _ = _identity_kinds(reference)
                    if normalize_official_order(latest_person_row.numero_ordre) != reference.numero_ordre_normalise:
                        conflict = True
                        anomalies.append({
                            "code": "OFFICIAL_SOURCE_ORDER_MISMATCH",
                            "severity": "ERROR",
                            "official_value": reference.numero_ordre,
                            "source_value": latest_person_row.numero_ordre,
                        })
                    if (latest_person_type == "PP" and expected_kind != "EC") or (
                        latest_person_type == "PM" and expected_kind != "SEC"
                    ):
                        # L'identité et les autres valeurs restent consolidables.
                        # L'incompatibilité de source est une anomalie de
                        # classification, pas une impossibilité de produire
                        # une proposition.
                        conflict = True
                        anomalies.append({"code": "SOURCE_TYPE_MISMATCH", "severity": "WARNING"})

            person_source_row_id = latest_person_row.source_row_id if latest_person_row is not None else None
            related_observations = [*ca_candidates, *insurance_candidates]
            seen_error_rows: set[int] = set()
            if person_source_row_id is not None:
                seen_error_rows.add(person_source_row_id)
            for observation in related_observations:
                if observation.source_row_id in seen_error_rows:
                    continue
                seen_error_rows.add(observation.source_row_id)
                source_row = source_row_by_id.get(observation.source_row_id)
                for error in (source_row.normalization_errors if source_row else []) or []:
                    frozen_error = _json_value(error)
                    if isinstance(frozen_error, dict):
                        frozen_error = {
                            **frozen_error,
                            "source_row_id": observation.source_row_id,
                            "import_id": observation.source_import_id,
                        }
                    anomalies.append(frozen_error)
                    if str(error.get("severity") or "").upper() == "BLOCKING":
                        blocked = True

            if ca_candidates:
                ca_values = [
                    {
                        "annee": row.annee,
                        "devise": row.devise_normalisee,
                        "ca_facture": _json_value(row.ca_facture),
                        "ca_collecte": _json_value(row.ca_collecte),
                        "date_situation": row.date_situation.isoformat(),
                        "import_id": row.source_import_id,
                    }
                    for row in sorted(ca_candidates, key=lambda item: _source_rank(item, imports_by_id))
                ]
                proposed_values["chiffres_affaires"] = ca_values
                proposed_values["ca_present"] = any(row.ca_present for row in ca_candidates)
                provenance["chiffres_affaires"] = {
                    "source_type": "CA",
                    "imports": sorted({row.source_import_id for row in ca_candidates}),
                }
                provenance["ca_present"] = dict(provenance["chiffres_affaires"])

            if insurance_candidates:
                insurance_values = [
                    {
                        "declare": row.declare_normalise,
                        "souscrit": row.souscrit_normalise,
                        "fin_couverture": _json_value(row.fin_couverture),
                        "annee_souscription": row.annee_souscription,
                        "assureur": row.assureur_normalise,
                        "date_situation": row.date_situation.isoformat(),
                        "import_id": row.source_import_id,
                    }
                    for row in sorted(insurance_candidates, key=lambda item: _source_rank(item, imports_by_id))
                ]
                proposed_values["assurances"] = insurance_values
                proposed_values["insurance_status"] = _insurance_status_from_declarations(
                    insurance_candidates, date_situation
                )
                provenance["assurances"] = {
                    "source_type": "ASSURANCE",
                    "imports": sorted({row.source_import_id for row in insurance_candidates}),
                }
                provenance["insurance_status"] = dict(provenance["assurances"])

            reference_status = "MATCHED_OFFICIAL" if reference else identity.reference_status
            if reference is None and reference_status in {"UNRESOLVED", "ABSENT_DU_REFERENTIEL"}:
                source_values = {
                    "name": proposed_values.get("nom_denomination"),
                    "email": proposed_values.get("email"),
                    "phone": proposed_values.get("telephone"),
                }
                candidate_signals = _candidate_signals(source_values, references)
                candidate_union = {candidate for values in candidate_signals.values() for candidate in values}
                if candidate_union:
                    reference_status = "AMBIGUOUS" if len(candidate_union) > 1 else "UNRESOLVED"
                    anomalies.append({
                        "code": "OFFICIAL_MATCH_REQUIRES_REVIEW",
                        "severity": "WARNING",
                        "candidate_signals": candidate_signals,
                    })
                else:
                    reference_status = "ABSENT_DU_REFERENTIEL"
                    identity.reference_status = reference_status
                    identity.reference_match_method = None
                    identity.reference_match_metadata = None

            differences = []
            for field_name in sorted(set(official_values) | set(proposed_values)):
                official_value = official_values.get(field_name)
                proposed_value = proposed_values.get(field_name)
                if _same_value(official_value, proposed_value):
                    continue
                differences.append({
                    "field": field_name,
                    "official_value": official_value,
                    "proposed_value": proposed_value,
                    "change": "ADDED" if field_name not in official_values else "CHANGED",
                })

            if blocked:
                proposal_status = "BLOCKED"
            elif reference_status in {"AMBIGUOUS", "UNRESOLVED"} and reference is None:
                proposal_status = "AMBIGUOUS_MATCH"
            elif reference is None:
                proposal_status = "NEW_IDENTITY"
            elif conflict:
                proposal_status = "CONFLICT"
            elif not has_new_sources:
                proposal_status = "OFFICIAL_ONLY"
            elif differences:
                proposal_status = "UPDATE_PROPOSED"
            else:
                proposal_status = "UNCHANGED"

            status_counts[proposal_status] += 1
            db.add(TableauActualisationRow(
                actualisation_id=actualisation.id,
                identity_id=identity.id,
                official_expert_id=reference.official_expert_id if reference else None,
                numero_ordre=reference.numero_ordre if reference else identity.numero_ordre,
                reference_status=reference_status,
                proposal_status=proposal_status,
                official_values=official_values,
                proposed_values=_json_value(proposed_values),
                field_provenance=_json_value(provenance),
                differences_json=_json_value(differences),
                anomalies_json=_json_value(anomalies),
            ))

        # Les lignes sont écrites tant que la révision est en état processing.
        # Le trigger SQL interdira toute mutation après le passage à completed.
        await db.flush()
        actualisation.metadata_json = {
            **(actualisation.metadata_json or {}),
            "input_count": len(selected_imports),
            "reference_member_count": len(references),
            "result_row_count": len(row_identities),
            "orphan_ca_count": orphan_ca,
            "orphan_insurance_count": orphan_insurance,
            "proposal_status_counts": dict(status_counts),
            "missing_input_hash_count": sum(
                1 for source_import in selected_imports if not source_import.file_sha256
            ),
        }
        actualisation.status = "completed"
        await record_tableau_audit(
            db,
            organisation_id=organisation_id,
            user_id=user.id,
            action="tableau.actualisation.create",
            target_type="tableau_actualisation",
            target_id=actualisation.id,
            metadata_json={
                "date_situation": date_situation,
                "revision_number": revision_number,
                "reference_snapshot_id": reference_snapshot.id,
                "input_count": len(selected_imports),
                "result_row_count": len(row_identities),
                "ruleset_version": RULESET_VERSION,
            },
        )
        await db.commit()
        await db.refresh(actualisation)
        return actualisation
    except Exception:
        await db.rollback()
        raise
