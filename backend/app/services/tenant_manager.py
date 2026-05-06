from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.budget import BudgetExercice, BudgetPoste
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.print_settings import PrintSettings
from app.models.subscription import Subscription
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.models.user_service import user_services
from app.models.organisation_settings import OrganisationSettings
from app.services.system_settings_service import get_system_settings
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


def _normalize_service_code(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split()).upper()
    if normalized == "ADMIN":
        return "ADM"
    return normalized


def _normalize_service_libelle(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split())
    if normalized.lower() in {"administration", "administrations"}:
        return "Administration"
    return normalized


def _service_label_match_expr():
    normalized_expr = func.regexp_replace(func.lower(func.btrim(Service.libelle)), r"\s+", " ", "g")
    return normalized_expr.in_(["administration", "administrations"])


DEFAULT_SERVICE_CODE = "ADM"
DEFAULT_SERVICE_LABEL = "Administration"

ORG_SETTINGS_TEMPLATE_FIELDS = (
    "max_users",
    "storage_quota_mb",
    "is_ai_enabled",
    "is_mobile_money_enabled",
    "is_audit_logs_enabled",
    "fiscal_year_start",
    "currency_code",
    "theme_primary_color",
    "theme_sidebar_color",
    "theme_sidebar_text_color",
    "theme_sidebar_active_color",
    "theme_accent_color",
    "theme_text_color",
    "theme_button_text_color",
)

PRINT_SETTINGS_TEMPLATE_FIELDS = (
    "pied_de_page_legal",
    "afficher_qr_code",
    "show_header_logo",
    "show_footer_signature",
    "recu_label_signature",
    "sortie_label_signature",
    "sortie_sig_label_1",
    "sortie_sig_label_2",
    "sortie_sig_label_3",
    "sortie_sig_hint",
    "show_sortie_qr",
    "sortie_qr_base_url",
    "show_sortie_watermark",
    "sortie_watermark_text",
    "sortie_watermark_opacity",
    "paper_format",
    "compact_header",
    "req_titre_officiel",
    "req_label_gauche",
    "req_label_droite",
    "trans_titre_officiel",
    "trans_label_gauche",
    "trans_label_droite",
    "encaissement_libelle_presets",
    "default_currency",
    "secondary_currency",
    "exchange_rate",
    "exchange_rate_cdf",
    "exchange_rate_eur",
    "exchange_rate_xof",
    "fiscal_year",
    "budget_alert_threshold",
    "budget_block_overrun",
    "budget_force_roles",
)


def _copy_template_fields(source: object | None, target: object, fields: tuple[str, ...]) -> None:
    if source is None:
        return
    for field in fields:
        setattr(target, field, getattr(source, field))


async def _fetch_org_settings(db: AsyncSession, organisation_id: int) -> OrganisationSettings | None:
    res = await db.execute(
        select(OrganisationSettings).where(OrganisationSettings.organisation_id == organisation_id).limit(1)
    )
    return res.scalar_one_or_none()


async def _fetch_print_settings(db: AsyncSession, organisation_id: int) -> PrintSettings | None:
    res = await db.execute(
        select(PrintSettings).where(PrintSettings.organisation_id == organisation_id).limit(1)
    )
    return res.scalar_one_or_none()


async def _ensure_org_settings(
    db: AsyncSession,
    *,
    organisation_id: int,
    template_org_id: int,
) -> OrganisationSettings:
    org_settings = await _fetch_org_settings(db, organisation_id)
    if org_settings is not None:
        return org_settings

    template = await _fetch_org_settings(db, template_org_id)
    org_settings = OrganisationSettings(
        organisation_id=organisation_id,
        max_users=2,
        storage_quota_mb=1024,
        is_ai_enabled=False,
        is_mobile_money_enabled=True,
        is_audit_logs_enabled=True,
        fiscal_year_start=1,
        currency_code="CDF",
    )
    _copy_template_fields(template, org_settings, ORG_SETTINGS_TEMPLATE_FIELDS)
    db.add(org_settings)
    await db.flush()
    return org_settings


async def _ensure_print_settings(
    db: AsyncSession,
    *,
    org: Organisation,
    template_org_id: int,
    now: datetime,
) -> PrintSettings:
    print_settings = await _fetch_print_settings(db, org.id)
    if print_settings is None:
        template = await _fetch_print_settings(db, template_org_id)
        print_settings = PrintSettings(
            organisation_id=org.id,
            organization_name=org.nom,
            updated_at=now,
        )
        _copy_template_fields(template, print_settings, PRINT_SETTINGS_TEMPLATE_FIELDS)
        db.add(print_settings)
        await db.flush()
    elif not (print_settings.organization_name or "").strip():
        print_settings.organization_name = org.nom
        print_settings.updated_at = now
    return print_settings


async def _ensure_cash_accounts(db: AsyncSession, *, organisation_id: int) -> None:
    res = await db.execute(
        select(CompteBancaire.devise).where(
            CompteBancaire.organisation_id == organisation_id,
            CompteBancaire.account_type == "CASH",
        )
    )
    existing = {str(row[0] or "").upper() for row in res.all()}
    if "USD" not in existing:
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
    if "CDF" not in existing:
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


async def _ensure_default_service(db: AsyncSession, *, organisation_id: int) -> Service:
    normalized_code = _normalize_service_code(DEFAULT_SERVICE_CODE)
    normalized_label = _normalize_service_libelle(DEFAULT_SERVICE_LABEL)
    res = await db.execute(
        select(Service).where(
            Service.organisation_id == organisation_id,
            (func.regexp_replace(func.upper(func.btrim(Service.code)), r"\s+", " ", "g").in_(["ADM", "ADMIN"]))
            | _service_label_match_expr(),
        )
    )
    service = res.scalar_one_or_none()
    if service is None:
        service = Service(
            code=normalized_code,
            libelle=normalized_label,
            organisation_id=organisation_id,
            is_active=True,
        )
        db.add(service)
        await db.flush()
    else:
        service.code = normalized_code
        service.libelle = normalized_label
        service.is_active = True
    return service


async def _ensure_user_service_membership(db: AsyncSession, *, user: User, service: Service) -> None:
    if user.service_id is None:
        user.service_id = service.id
    link_res = await db.execute(
        select(user_services.c.user_id).where(
            user_services.c.user_id == user.id,
            user_services.c.service_id == service.id,
        )
    )
    if link_res.first() is None:
        await db.execute(
            insert(user_services).values(user_id=user.id, service_id=service.id)
        )


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
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=0, solde_cdf=0))
    org_settings = await _ensure_org_settings(db, organisation_id=org.id, template_org_id=template_org_id)
    await _ensure_print_settings(db, org=org, template_org_id=template_org_id, now=now)
    await _ensure_cash_accounts(db, organisation_id=org.id)
    org.devise_preferee = org_settings.currency_code
    org.limite_utilisateurs = org_settings.max_users

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
    await db.flush()
    admin_service = await _ensure_default_service(db, organisation_id=org.id)
    await _ensure_user_service_membership(db, user=admin, service=admin_service)

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
    if await get_system_settings(db, organisation_id) is None:
        db.add(SystemSettings(organisation_id=organisation_id, updated_at=now))

    org_settings = await _ensure_org_settings(db, organisation_id=organisation_id, template_org_id=template_org_id)
    org.devise_preferee = org_settings.currency_code
    org.limite_utilisateurs = org_settings.max_users

    await _ensure_print_settings(db, org=org, template_org_id=template_org_id, now=now)

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

    await _ensure_cash_accounts(db, organisation_id=organisation_id)

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
        await db.flush()

    admin_service = await _ensure_default_service(db, organisation_id=organisation_id)
    if admin is not None:
        await _ensure_user_service_membership(db, user=admin, service=admin_service)

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
