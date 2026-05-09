import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.budget import list_budget_lines
from app.api.v1.endpoints.experts import list_experts, require_expert_admin
from app.api.v1.endpoints.remboursements_transport import list_remboursements_transport
from app.core.tenant_context import set_current_tenant_id
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.expert_comptable import ExpertComptable
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.remboursement_transport import RemboursementTransport
from app.models.requisition import Requisition
from app.models.user import User

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _org(name: str, slug: str) -> Organisation:
    now = datetime.now(timezone.utc)
    return Organisation(
        nom=name,
        slug=slug,
        plan_type="ACTIVE",
        status_abonnement="ACTIVE",
        limite_utilisateurs=10,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def _admin_user(email: str, organisation_id: int) -> User:
    return User(
        id=uuid.uuid4(),
        email=email,
        nom="Admin",
        prenom="Tenant",
        role="admin",
        organisation_id=organisation_id,
        active=True,
        is_email_verified=True,
    )


def _budget_poste(
    *,
    organisation_id: int,
    exercice_id: int,
    code: str,
    libelle: str,
    montant: Decimal,
    type_value: str = "DEPENSE",
) -> BudgetPoste:
    return BudgetPoste(
        organisation_id=organisation_id,
        exercice_id=exercice_id,
        code=code,
        libelle=libelle,
        type=type_value,
        active=True,
        montant_prevu=montant,
        montant_engage=Decimal("0"),
        montant_paye=Decimal("0"),
        is_deleted=False,
    )


def _requisition(*, organisation_id: int, numero: str, reference: str) -> Requisition:
    return Requisition(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        numero_requisition=numero,
        reference_numero=reference,
        objet="Paiement test",
        mode_paiement="BANQUE",
        type_requisition="classique",
        status="EN_ATTENTE",
        montant_total=Decimal("125.00"),
    )


async def test_budget_lines_are_strictly_tenant_scoped(db_session):
    set_current_tenant_id(None)
    token = _suffix()
    tenant_defs = [
        ("CPK", f"cpk-{token}"),
        ("Congres", f"congres-{token}"),
        ("CPHK", f"cphk-{token}"),
        ("CPSK", f"cpsk-{token}"),
    ]
    organisations = [_org(name, slug) for name, slug in tenant_defs]
    db_session.add_all(organisations)
    await db_session.flush()

    users: dict[str, User] = {}
    exercices: dict[str, BudgetExercice] = {}
    postes: list[BudgetPoste] = []
    for org in organisations:
        slug_token = org.slug.split("-")[0]
        user = _admin_user(f"admin-{slug_token}-{token}@example.com", org.id)
        exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
        users[org.nom] = user
        exercices[org.nom] = exercice
        db_session.add_all([user, exercice])
    await db_session.flush()

    for org in organisations:
        postes.append(
            _budget_poste(
                organisation_id=org.id,
                exercice_id=exercices[org.nom].id,
                code=f"BUD-{org.nom.upper()}-001",
                libelle=f"Budget {org.nom}",
                montant=Decimal(str(1000 * (organisations.index(org) + 1))),
            )
        )
    db_session.add_all(postes)
    await db_session.commit()

    for org in organisations:
        set_current_tenant_id(org.id)
        response = await list_budget_lines(
            annee=2026,
            type=None,
            active=None,
            service_id=None,
            user=users[org.nom],
            tenant_id=org.id,
            db=db_session,
        )
        assert [line.code for line in response.lignes] == [f"BUD-{org.nom.upper()}-001"]
    set_current_tenant_id(None)


async def test_cross_tenant_budget_link_is_rejected_on_flush(db_session):
    set_current_tenant_id(None)
    token = _suffix()
    org_cpk = _org("CPK", f"cpk-cross-{token}")
    org_congres = _org("Congres", f"congres-cross-{token}")
    db_session.add_all([org_cpk, org_congres])
    await db_session.flush()

    req_cpk = _requisition(
        organisation_id=org_cpk.id,
        numero="REQ-SHARED-0001",
        reference="REQ-SHARED-0001",
    )
    ex_congres = BudgetExercice(organisation_id=org_congres.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add_all([req_cpk, ex_congres])
    await db_session.flush()

    poste_congres = _budget_poste(
        organisation_id=org_congres.id,
        exercice_id=ex_congres.id,
        code="POSTE-CONGRES-001",
        libelle="Poste Congres",
        montant=Decimal("500.00"),
    )
    db_session.add(poste_congres)
    await db_session.commit()

    set_current_tenant_id(org_cpk.id)
    db_session.add(
        LigneRequisition(
            organisation_id=org_cpk.id,
            requisition_id=req_cpk.id,
            budget_poste_id=poste_congres.id,
            rubrique="Rubrique test",
            description="Tentative de liaison croisee",
            quantite=1,
            montant_unitaire=Decimal("10.00"),
            montant_total=Decimal("10.00"),
        )
    )
    with pytest.raises(ValueError, match="Tenant mismatch"):
        await db_session.flush()
    await db_session.rollback()
    set_current_tenant_id(None)


async def test_financial_resources_remain_tenant_scoped(db_session):
    set_current_tenant_id(None)
    token = _suffix()
    org_cpk = _org("CPK", f"cpk-remb-{token}")
    org_congres = _org("Congres", f"congres-remb-{token}")
    db_session.add_all([org_cpk, org_congres])
    await db_session.flush()

    user_cpk = _admin_user(f"admin-remb-cpk-{token}@example.com", org_cpk.id)
    user_congres = _admin_user(f"admin-remb-congres-{token}@example.com", org_congres.id)
    db_session.add_all([user_cpk, user_congres])

    req_cpk = _requisition(
        organisation_id=org_cpk.id,
        numero="REQ-FIN-0001",
        reference="REQ-FIN-0001",
    )
    req_congres = _requisition(
        organisation_id=org_congres.id,
        numero="REQ-FIN-0001",
        reference="REQ-FIN-0001",
    )
    db_session.add_all([req_cpk, req_congres])
    await db_session.flush()

    same_number = f"REM-{token}"
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
                RemboursementTransport(
                    id=uuid.uuid4(),
                    organisation_id=org_cpk.id,
                    numero_remboursement=same_number,
                    reference_numero=same_number,
                    instance="CPK",
                    type_reunion="bureau",
                    nature_reunion="Validation",
                    lieu="Kinshasa",
                date_reunion=now,
                montant_total=Decimal("150.00"),
                requisition_id=req_cpk.id,
                created_by=user_cpk.id,
            ),
                RemboursementTransport(
                    id=uuid.uuid4(),
                    organisation_id=org_congres.id,
                    numero_remboursement=same_number,
                    reference_numero=same_number,
                    instance="CONGRES",
                    type_reunion="bureau",
                    nature_reunion="Validation",
                    lieu="Kinshasa",
                date_reunion=now,
                montant_total=Decimal("220.00"),
                requisition_id=req_congres.id,
                created_by=user_congres.id,
            ),
        ]
    )
    await db_session.commit()

    set_current_tenant_id(org_cpk.id)
    cpk_items = await list_remboursements_transport(
        include="requisition",
        requisition_id=None,
        limit=50,
        offset=0,
        user=user_cpk,
        tenant_id=org_cpk.id,
        db=db_session,
    )
    set_current_tenant_id(org_congres.id)
    congres_items = await list_remboursements_transport(
        include="requisition",
        requisition_id=None,
        limit=50,
        offset=0,
        user=user_congres,
        tenant_id=org_congres.id,
        db=db_session,
    )
    set_current_tenant_id(None)

    assert len(cpk_items) == 1
    assert len(congres_items) == 1
    assert cpk_items[0].requisition.reference_numero == "REQ-FIN-0001"
    assert congres_items[0].requisition.reference_numero == "REQ-FIN-0001"
    assert cpk_items[0].id != congres_items[0].id


async def test_experts_are_shared_but_cn_is_the_only_admin_tenant(db_session):
    set_current_tenant_id(None)
    token = _suffix()
    existing_cn = (
        await db_session.execute(select(Organisation).where(Organisation.slug == "cn"))
    ).scalar_one_or_none()
    org_cn = existing_cn or _org("Conseil National", "cn")
    org_cpk = _org("CPK", f"cpk-experts-{token}")
    if existing_cn is None:
        db_session.add(org_cn)
    db_session.add(org_cpk)
    await db_session.flush()

    user_cn = _admin_user(f"admin-cn-{token}@example.com", org_cn.id)
    user_cpk = _admin_user(f"admin-cpk-experts-{token}@example.com", org_cpk.id)
    db_session.add_all([user_cn, user_cpk])

    expert = ExpertComptable(
        numero_ordre=f"EC-{token}",
        nom_denomination="Expert Global",
        type_ec="EC",
        active=True,
    )
    db_session.add(expert)
    await db_session.commit()

    cpk_list = await list_experts(
        numero_ordre=f"EC-{token}",
        nom=None,
        q=None,
        type_ec=None,
        active=True,
        include_inactive=False,
        statut_professionnel=None,
        order=None,
        limit=50,
        offset=0,
        include_summary=False,
        user=user_cpk,
        db=db_session,
    )
    cn_list = await list_experts(
        numero_ordre=f"EC-{token}",
        nom=None,
        q=None,
        type_ec=None,
        active=True,
        include_inactive=False,
        statut_professionnel=None,
        order=None,
        limit=50,
        offset=0,
        include_summary=False,
        user=user_cn,
        db=db_session,
    )

    assert [item["numero_ordre"] for item in cpk_list] == [f"EC-{token}"]
    assert [item["numero_ordre"] for item in cn_list] == [f"EC-{token}"]

    assert await require_expert_admin(user=user_cn, db=db_session) == user_cn
    with pytest.raises(HTTPException) as exc_info:
        await require_expert_admin(user=user_cpk, db=db_session)
    assert exc_info.value.status_code == 403
