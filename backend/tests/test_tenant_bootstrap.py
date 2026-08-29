import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.api.v1.endpoints.auth import _resolve_user_for_email, discover_tenants
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement
from app.models.hr import HREmployee
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.print_settings import PrintSettings
from app.models.remboursement_transport import ParticipantTransport, RemboursementTransport
from app.models.rbac import Permission, Role
from app.models.service import Service
from app.models.service_member_function import ServiceMemberFunction
from app.models.requisition import Requisition
from app.models.system_settings import SystemSettings
from app.models.user import User


from app.modules.secretariat.models import SecretariatAuditLog
from app.modules.secretariat.models import SecretariatApproval
from app.modules.secretariat.models import SecretariatDocument
from app.services.tenant_manager import bootstrap_tenant_defaults


async def _seed_roles_and_permissions(db_session) -> None:
    admin_role = Role(code="admin", label="Admin")
    demandeur_role = Role(code="demandeur", label="Demandeur")
    db_session.add_all([admin_role, demandeur_role])
    db_session.add(Permission(code="menu_budget", description="Accès budget"))
    await db_session.commit()


async def _seed_reference_org(db_session) -> Organisation:
    slug = f"cpk-{uuid.uuid4().hex[:10]}"
    org = Organisation(
        nom="CPK",
        slug=slug,
        plan_type="ACTIVE",
        status_abonnement="ACTIVE",
        limite_utilisateurs=5,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(org)
    await db_session.flush()

    db_session.add(
        OrganisationSettings(
            organisation_id=org.id,
            max_users=9,
            storage_quota_mb=4096,
            is_ai_enabled=True,
            is_mobile_money_enabled=True,
            is_audit_logs_enabled=True,
            fiscal_year_start=1,
            currency_code="CDF",
        )
    )
    db_session.add(
        PrintSettings(
            organisation_id=org.id,
            organization_name="CPK",
            default_currency="USD",
            secondary_currency="CDF",
            fiscal_year=2026,
        )
    )
    db_session.add(SystemSettings(organisation_id=org.id, updated_at=datetime.now(timezone.utc)))
    db_session.add(CaisseCentrale(organisation_id=org.id, solde_usd=0, solde_cdf=0))
    service = Service(code="ADM", libelle="Administration", organisation_id=org.id, is_active=True)
    db_session.add(service)
    await db_session.flush()
    db_session.add(
        ServiceMemberFunction(
            organisation_id=org.id,
            service_id=service.id,
            label="Président",
            sort_order=1,
            is_default=True,
            is_active=True,
        )
    )
    ex = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(ex)
    await db_session.flush()
    db_session.add(
        BudgetPoste(
            organisation_id=org.id,
            exercice_id=ex.id,
            code="CPK-REF-01",
            libelle="Référence CPK",
            type="DEPENSE",
            active=True,
            montant_prevu=0,
            montant_engage=0,
            montant_paye=0,
        )
    )
    await db_session.commit()
    return org


@pytest.mark.asyncio
async def test_bootstrap_tenant_defaults_is_idempotent_and_copies_reference_basics(db_session):
    await _seed_roles_and_permissions(db_session)
    reference = await _seed_reference_org(db_session)

    bj = Organisation(
        nom="BJ",
        slug="bj",
        plan_type="TRIAL",
        status_abonnement="TRIAL",
        limite_utilisateurs=2,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(bj)
    await db_session.flush()

    admin = User(
        id=uuid.uuid4(),
        email="admin.bj@example.com",
        role="admin",
        organisation_id=bj.id,
        active=True,
        is_email_verified=True,
    )
    db_session.add(admin)
    await db_session.commit()

    await bootstrap_tenant_defaults(db_session, organisation_id=bj.id, template_org_id=reference.id)
    await db_session.commit()
    await bootstrap_tenant_defaults(db_session, organisation_id=bj.id, template_org_id=reference.id)
    await db_session.commit()

    service_res = await db_session.execute(select(Service).where(Service.organisation_id == bj.id))
    services = service_res.scalars().all()
    assert len(services) == 1
    assert services[0].code == "ADM"

    fn_res = await db_session.execute(
        select(ServiceMemberFunction).where(ServiceMemberFunction.organisation_id == bj.id)
    )
    functions = fn_res.scalars().all()
    labels = {item.label for item in functions}
    assert labels == {"Président"}

    settings_res = await db_session.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == bj.id)
    )
    settings = settings_res.scalar_one()
    assert settings.max_users == 9

    budget_res = await db_session.execute(select(BudgetPoste).where(BudgetPoste.organisation_id == bj.id))
    budget_codes = {item.code for item in budget_res.scalars().all()}
    assert budget_codes == {"CPK-REF-01"}

    admin_res = await db_session.execute(select(User).where(User.email == "admin.bj@example.com"))
    admin = admin_res.scalar_one()
    assert admin.service_id is not None
    assert admin.role_id is not None


@pytest.mark.asyncio
async def test_resolve_user_for_email_requires_tenant_when_email_exists_in_multiple_orgs(db_session):
    suffix = uuid.uuid4().hex[:10]
    org_cpk = Organisation(nom="CPK", slug=f"cpk-{suffix}", is_active=True)
    org_bj = Organisation(nom="BJ", slug=f"bj-{suffix}", is_active=True)
    db_session.add_all([org_cpk, org_bj])
    await db_session.flush()

    shared_email = "shared@example.com"
    db_session.add_all(
        [
            User(id=uuid.uuid4(), email=shared_email, role="admin", organisation_id=org_cpk.id, active=True, is_email_verified=True),
            User(id=uuid.uuid4(), email=shared_email, role="admin", organisation_id=org_bj.id, active=True, is_email_verified=True),
        ]
    )
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_user_for_email(db_session, shared_email, explicit_tenant_hint=None)
    assert exc_info.value.status_code == 400

    user, org = await _resolve_user_for_email(
        db_session, shared_email, explicit_tenant_hint=org_bj.slug
    )
    assert user is not None
    assert org is not None
    assert org.slug == org_bj.slug
    assert user.organisation_id == org.id


@pytest.mark.asyncio
async def test_discover_tenants_returns_only_active_memberships(db_session):
    suffix = uuid.uuid4().hex[:10]
    org_bj = Organisation(nom="BJ", slug=f"bj-{suffix}", is_active=True)
    org_cn = Organisation(nom="CN", slug=f"cn-{suffix}", is_active=True)
    db_session.add_all([org_bj, org_cn])
    await db_session.flush()

    email = "multi@example.com"
    db_session.add_all(
        [
            User(id=uuid.uuid4(), email=email, role="admin", organisation_id=org_bj.id, active=True, is_email_verified=True),
            User(id=uuid.uuid4(), email=email, role="demandeur", organisation_id=org_cn.id, active=True, is_email_verified=True),
        ]
    )
    await db_session.commit()

    tenants = await discover_tenants(email=email, db=db_session)
    assert [tenant.slug for tenant in tenants] == [org_bj.slug, org_cn.slug]
