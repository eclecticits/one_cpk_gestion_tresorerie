from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.subscription import Subscription
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.models.organisation_settings import OrganisationSettings
from app.services.budget_template import ensure_core_budget_postes


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def add_months(dt: datetime, months: int) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_month = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    day = min(dt.day, days_in_month[month - 1])
    return dt.replace(year=year, month=month, day=day)


def _generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def _clone_budget_structure(
    db: AsyncSession,
    *,
    source_org_id: int,
    target_org_id: int,
) -> None:
    ex_res = await db.execute(
        select(BudgetExercice).where(BudgetExercice.organisation_id == source_org_id)
    )
    exercices = ex_res.scalars().all()
    if not exercices:
        return

    ex_map: dict[int, BudgetExercice] = {}
    for ex in exercices:
        new_ex = BudgetExercice(
            organisation_id=target_org_id,
            annee=ex.annee,
            statut=ex.statut,
        )
        db.add(new_ex)
        await db.flush()
        ex_map[ex.id] = new_ex

    poste_res = await db.execute(
        select(BudgetPoste).where(BudgetPoste.organisation_id == source_org_id)
    )
    postes = poste_res.scalars().all()
    poste_map: dict[int, BudgetPoste] = {}
    for poste in postes:
        new_poste = BudgetPoste(
            organisation_id=target_org_id,
            exercice_id=ex_map[poste.exercice_id].id,
            code=poste.code,
            libelle=poste.libelle,
            parent_code=poste.parent_code,
            parent_id=None,
            type=poste.type,
            active=poste.active,
            montant_prevu=poste.montant_prevu,
            montant_engage=poste.montant_engage,
            montant_paye=poste.montant_paye,
            is_global=poste.is_global,
            is_deleted=poste.is_deleted,
            deleted_at=poste.deleted_at,
            deleted_by=poste.deleted_by,
        )
        db.add(new_poste)
        await db.flush()
        poste_map[poste.id] = new_poste

    for poste in postes:
        if poste.parent_id and poste.parent_id in poste_map:
            poste_map[poste.id].parent_id = poste_map[poste.parent_id].id


async def provision_new_tenant(
    db: AsyncSession,
    *,
    organisation_name: str,
    slug: str,
    plan_id: int,
    admin_email: str,
    admin_phone: str | None = None,
    trial_days: int = 14,
    template_org_id: int = 1,
    paid_months: int | None = None,
) -> tuple[Organisation, Subscription, str]:
    now = _utcnow()

    org = Organisation(
        nom=organisation_name.strip(),
        slug=slug.strip().lower(),
        plan_type="TRIAL",
        status_abonnement="TRIAL",
        date_expiration_abonnement=now + timedelta(days=trial_days),
        limite_utilisateurs=2,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(org)
    await db.flush()

    await _clone_budget_structure(db, source_org_id=template_org_id, target_org_id=org.id)
    await ensure_core_budget_postes(db, organisation_id=org.id)

    db.add(SystemSettings(organisation_id=org.id, updated_at=now))
    db.add(PrintSettings(organisation_id=org.id, organization_name=org.nom, updated_at=now))
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=0, solde_cdf=0))
    db.add(
        OrganisationSettings(
            organisation_id=org.id,
            max_users=2,
            storage_quota_mb=1024,
            is_ai_enabled=False,
            is_mobile_money_enabled=True,
            is_audit_logs_enabled=True,
            fiscal_year_start=1,
            currency_code="CDF",
        )
    )

    cash_usd = CompteBancaire(
        organisation_id=org.id,
        banque_id=None,
        intitule="Caisse USD",
        numero_compte=f"CASH-USD-{org.id}",
        solde_initial=0,
        solde_actuel=0,
        devise="USD",
        account_type="CASH",
        is_active=True,
    )
    cash_cdf = CompteBancaire(
        organisation_id=org.id,
        banque_id=None,
        intitule="Caisse CDF",
        numero_compte=f"CASH-CDF-{org.id}",
        solde_initial=0,
        solde_actuel=0,
        devise="CDF",
        account_type="CASH",
        is_active=True,
    )
    db.add(cash_usd)
    db.add(cash_cdf)

    temp_password = _generate_temp_password()
    admin = User(
        email=admin_email.strip().lower(),
        nom=organisation_name.strip(),
        prenom="Admin",
        hashed_password=hash_password(temp_password),
        role="admin",
        organisation_id=org.id,
        active=True,
        must_change_password=True,
        is_first_login=True,
        is_email_verified=False,
    )
    db.add(admin)

    subscription = Subscription(
        organisation_id=org.id,
        plan_id=plan_id,
        status="TRIAL",
        trial_end=now + timedelta(days=trial_days),
        current_period_end=now + timedelta(days=trial_days),
        created_at=now,
        updated_at=now,
    )
    db.add(subscription)
    if paid_months and paid_months > 0:
        subscription.status = "ACTIVE"
        subscription.trial_end = None
        subscription.current_period_end = add_months(now, paid_months)
        org.status_abonnement = "ACTIVE"
        org.plan_type = "PAID"
        org.date_expiration_abonnement = subscription.current_period_end

    await db.commit()
    return org, subscription, temp_password


async def activate_reserved_tenant(
    db: AsyncSession,
    *,
    organisation_id: int,
    plan_id: int,
    admin_email: str,
    admin_phone: str | None = None,
    paid_months: int = 1,
    template_org_id: int = 1,
) -> tuple[Organisation, Subscription, str]:
    now = _utcnow()
    org_res = await db.execute(select(Organisation).where(Organisation.id == organisation_id))
    org = org_res.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation introuvable")

    # Seed base data if missing
    settings_res = await db.execute(
        select(SystemSettings).where(SystemSettings.organisation_id == organisation_id).limit(1)
    )
    if settings_res.scalar_one_or_none() is None:
        db.add(SystemSettings(organisation_id=organisation_id, updated_at=now))

    org_settings_res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == organisation_id).limit(1)
    )
    org_settings = org_settings_res.scalar_one_or_none()
    if org_settings is None:
        db.add(
            OrganisationSettings(
                organisation_id=organisation_id,
                max_users=2,
                storage_quota_mb=1024,
                is_ai_enabled=False,
                is_mobile_money_enabled=True,
                is_audit_logs_enabled=True,
                fiscal_year_start=1,
                currency_code="CDF",
            )
        )
        org.devise_preferee = "CDF"
    else:
        org.devise_preferee = org_settings.currency_code
        org.limite_utilisateurs = org_settings.max_users

    print_res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == organisation_id).limit(1)
    )
    if print_res.scalar_one_or_none() is None:
        db.add(PrintSettings(organisation_id=organisation_id, organization_name=org.nom, updated_at=now))

    caisse_res = await db.execute(
        select(CaisseCentrale).where(CaisseCentrale.organisation_id == organisation_id).limit(1)
    )
    if caisse_res.scalar_one_or_none() is None:
        db.add(CaisseCentrale(organisation_id=organisation_id, solde_usd=0, solde_cdf=0))

    budget_res = await db.execute(
        select(BudgetExercice.id).where(BudgetExercice.organisation_id == organisation_id).limit(1)
    )
    if budget_res.scalar_one_or_none() is None:
        await _clone_budget_structure(db, source_org_id=template_org_id, target_org_id=organisation_id)
    await ensure_core_budget_postes(db, organisation_id=organisation_id)

    comptes_res = await db.execute(
        select(CompteBancaire.id).where(CompteBancaire.organisation_id == organisation_id).limit(1)
    )
    if comptes_res.scalar_one_or_none() is None:
        db.add(
            CompteBancaire(
                organisation_id=organisation_id,
                banque_id=None,
                intitule="Caisse USD",
                numero_compte=f"CASH-USD-{organisation_id}",
                solde_initial=0,
                solde_actuel=0,
                devise="USD",
                account_type="CASH",
                is_active=True,
            )
        )
        db.add(
            CompteBancaire(
                organisation_id=organisation_id,
                banque_id=None,
                intitule="Caisse CDF",
                numero_compte=f"CASH-CDF-{organisation_id}",
                solde_initial=0,
                solde_actuel=0,
                devise="CDF",
                account_type="CASH",
                is_active=True,
            )
        )

    user_res = await db.execute(
        select(User).where(User.email == admin_email.lower().strip(), User.organisation_id == organisation_id)
    )
    admin = user_res.scalar_one_or_none()
    temp_password = ""
    if admin is None:
        temp_password = _generate_temp_password()
        admin = User(
            email=admin_email.strip().lower(),
            nom=org.nom,
            prenom="Admin",
            hashed_password=hash_password(temp_password),
            role="admin",
            organisation_id=organisation_id,
            active=True,
            must_change_password=True,
            is_first_login=True,
            is_email_verified=False,
        )
        db.add(admin)

    sub_res = await db.execute(
        select(Subscription).where(Subscription.organisation_id == organisation_id).limit(1)
    )
    subscription = sub_res.scalar_one_or_none()
    if subscription is None:
        subscription = Subscription(
            organisation_id=organisation_id,
            plan_id=plan_id,
            status="PENDING_PAYMENT",
            created_at=now,
            updated_at=now,
        )
        db.add(subscription)

    subscription.plan_id = plan_id
    subscription.status = "ACTIVE"
    subscription.trial_end = None
    subscription.current_period_end = add_months(now, paid_months)
    subscription.updated_at = now

    org.status_abonnement = "ACTIVE"
    org.date_expiration_abonnement = subscription.current_period_end
    if org.limite_utilisateurs != 0:
        org.limite_utilisateurs = max(org.limite_utilisateurs or 0, 1)
    org.updated_at = now

    await db.commit()
    return org, subscription, temp_password
