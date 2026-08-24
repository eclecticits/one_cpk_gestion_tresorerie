"""Administration du canal WhatsApp : réglages, destinataires, gabarits, journal.

Ce routeur ne contient aucune logique d'envoi. Il configure, il montre, et il
délègue : la mise en file, la dé-duplication et la remise appartiennent à
`app/services/notifications/`. C'est ce partage qui permet à l'écran de
paramètres de tester une configuration exactement par le même chemin qu'un
paiement réel — un test qui emprunterait un raccourci ne testerait rien.

Trois invariants tiennent tout le module :

* **Cloisonnement tenant.** Chaque route résout l'organisation par
  `get_current_tenant_id` et filtre explicitement dessus, y compris pour les
  membres du Bureau (jointure sur `Service.organisation_id`) et pour le journal.
  Aucune route n'atteint la ligne d'un autre tenant, super-admin compris : le
  contexte tenant du super-admin est celui de l'organisation qu'il consulte.
* **Le secret ne sort jamais.** La clé API entre chiffrée par
  `encrypt_secret` et ne ressort sous aucune forme — ni en clair, ni masquée.
  `has_api_key` est la seule information rendue à son sujet.
* **Un numéro se mérite.** L'historique montre les numéros en clair à qui
  possède `treso.notifications.history` ; à qui n'a que la lecture, ils sont
  masqués par `mask_phone`.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_tenant_id, get_current_user, has_any_permission, has_permission
from app.core.auth_user import cached_permission_codes
from app.core.encryption import encrypt_secret
from app.core.permissions import resolve_permission_code
from app.db.session import get_db
from app.models.commission_member import CommissionMember
from app.models.notification_log import (
    CHANNEL_WHATSAPP,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SENT,
    STATUS_SKIPPED,
    NotificationLog,
)
from app.models.organisation import Organisation
from app.models.rbac import Permission, role_permissions
from app.models.service import Service
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.whatsapp import (
    DeliveryOut,
    EventOption,
    NotificationLogOut,
    NotificationLogPage,
    ProviderOption,
    RecipientOut,
    RecipientUpdate,
    ResendResult,
    TemplateOut,
    TemplatesEnvelope,
    TemplatesSaveResult,
    TemplatesUpdate,
    WhatsAppSettingsEnvelope,
    WhatsAppSettingsOut,
    WhatsAppSettingsUpdate,
    WhatsAppTestRequest,
    WhatsAppTestResult,
)
from app.services.audit_service import get_request_ip, log_action
from app.services.notifications import (
    ALL_EVENTS,
    EVENT_LABELS,
    FUND_OUTFLOW,
    OUTFLOW_EVENTS,
    PAYMENT_COMPLEMENT,
    PAYMENT_EVENTS,
    PAYMENT_PROFORMA_CONVERTED,
    PAYMENT_RECEIVED,
    PAYMENT_REMINDER,
    REQUISITION_APPROVED,
    TEST_MESSAGE,
    Recipient,
    available_providers,
    build_dedup_key,
    deliver_pending,
    describe_whatsapp_settings,
    format_phone_display,
    get_provider,
    load_bureau_members,
    load_whatsapp_settings,
    mask_phone,
    normalize_phone,
    notify_whatsapp,
)
from app.services.notifications import templates as wa_templates
from app.services.system_settings_service import consolidate_system_settings, get_system_settings

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.whatsapp")


# ── Vocabulaire d'affichage ──────────────────────────────────────────────────

PERM_READ = "treso.notifications.read"
PERM_UPDATE = "treso.notifications.update"
PERM_HISTORY = "treso.notifications.history"
PERM_TEST = "treso.notifications.test"

#: Ordre d'affichage des événements : paiements, sorties, puis le test.
#: Construit depuis `ALL_EVENTS` pour qu'un événement ajouté au vocabulaire
#: apparaisse sans qu'on ait à revenir ici.
_PREFERRED_EVENT_ORDER = (
    PAYMENT_RECEIVED,
    PAYMENT_PROFORMA_CONVERTED,
    PAYMENT_COMPLEMENT,
    PAYMENT_REMINDER,
    FUND_OUTFLOW,
    REQUISITION_APPROVED,
    TEST_MESSAGE,
)

STATUS_LABELS: dict[str, str] = {
    STATUS_PENDING: "En attente",
    STATUS_SENT: "Envoyé",
    STATUS_FAILED: "Échec",
    STATUS_SKIPPED: "Ignoré",
}

KNOWN_STATUSES = frozenset(STATUS_LABELS)

RECIPIENT_STATUS_LABELS: dict[str, str] = {
    "ready": "Prêt",
    "no_phone": "Numéro manquant ou invalide",
    "opted_out": "Notifications désactivées",
}

#: `entity_type` réservé aux envois de vérification. Un test ne se rattache à
#: aucune opération métier : il ne doit surtout pas en inventer une, sinon
#: l'historique laisserait croire à une sortie de fonds qui n'a jamais existé.
TEST_ENTITY_TYPE = "whatsapp_test"


def _ordered_events() -> list[str]:
    known = [event for event in _PREFERRED_EVENT_ORDER if event in ALL_EVENTS]
    extra = sorted(ALL_EVENTS - set(known))
    return known + extra


def _event_family(event_type: str) -> str:
    """Famille d'activation : c'est elle que `WhatsAppSettings.accepts` consulte."""
    if event_type in PAYMENT_EVENTS:
        return "payments"
    if event_type in OUTFLOW_EVENTS:
        return "sorties"
    return "service"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Accès et cloisonnement ───────────────────────────────────────────────────


async def _has_permission_code(db: AsyncSession, user: User, code: str) -> bool:
    """Reproduit la décision de `has_permission` sans lever, pour un choix d'affichage.

    Les gardes de route disent « entrez » ou « n'entrez pas » ; ici on a besoin
    d'une nuance — montrer un numéro entier ou le masquer — donc d'un booléen.
    La logique est calquée sur `app/api/deps.py` : court-circuit des rôles
    historiques, permissions déjà résolues dans le contexte, repli en base.
    """
    role = (user.role or "").lower()
    if role in {"super_admin", "admin"}:
        return True

    resolved = resolve_permission_code(code)
    codes = cached_permission_codes(user)
    if codes is not None:
        return resolved in codes or code in codes

    role_id = getattr(user, "role_id", None)
    if not role_id:
        return False
    found = (
        await db.execute(
            select(Permission.id)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role_id)
            .where(Permission.code.in_({resolved, code}))
            .limit(1)
        )
    ).scalar_one_or_none()
    return found is not None


async def _organisation_name(db: AsyncSession, tenant_id: int) -> str:
    name = (
        await db.execute(select(Organisation.nom).where(Organisation.id == tenant_id).limit(1))
    ).scalar_one_or_none()
    return name or ""


async def _settings_row(db: AsyncSession, tenant_id: int) -> SystemSettings:
    """Ligne de réglages du tenant, créée à la volée si elle manque.

    Même geste que `admin.py` pour `/notification-settings` : un tenant sans
    ligne n'est pas une erreur, c'est un tenant qui n'a jamais rien réglé.
    """
    row = await get_system_settings(db, tenant_id)
    if row is None:
        row = SystemSettings(organisation_id=tenant_id, updated_at=_utcnow())
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _assign(row: SystemSettings, column: str, value) -> None:
    """Écrit une colonne si le modèle la porte réellement.

    Garde-fou volontaire : sur un déploiement où la migration n'est pas encore
    passée, `setattr` sur une colonne absente réussirait en silence côté Python
    et ne persisterait rien. On préfère le savoir.
    """
    if not hasattr(type(row), column):
        logger.warning("whatsapp.column_missing column=%s", column)
        return
    setattr(row, column, value)


def _member_function_label(member: CommissionMember) -> str:
    """Fonction affichée : libellé du référentiel, sinon titre libre, sinon rôle.

    Même règle que `recipients._function_label`, qui est privé au service.
    """
    function = getattr(member, "function", None)
    label = getattr(function, "label", "") if function is not None else ""
    if label:
        return str(label)
    custom = getattr(member, "custom_title", None)
    if custom:
        return str(custom)
    role = getattr(member, "role_type", None)
    return getattr(role, "value", "") or ""


async def _load_member(db: AsyncSession, tenant_id: int, member_id: int) -> CommissionMember:
    """Membre du Bureau du tenant courant, ou 404.

    Le filtre tenant passe par la jointure sur `Service` et non par le filtre
    implicite de session : `commission_members` ne porte pas d'`organisation_id`,
    et une lecture sans jointure traverserait les organisations.
    """
    member = (
        await db.execute(
            select(CommissionMember)
            .join(Service, Service.id == CommissionMember.service_id)
            .where(CommissionMember.id == member_id, Service.organisation_id == tenant_id)
            .options(selectinload(CommissionMember.function))
        )
    ).scalar_one_or_none()
    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Membre du Bureau introuvable."
        )
    return member


# ── Mise en forme ────────────────────────────────────────────────────────────


def _public_settings(row: SystemSettings | None) -> WhatsAppSettingsOut:
    """Vue publique validée. `describe_whatsapp_settings` garantit l'absence de secret."""
    described = describe_whatsapp_settings(row)
    raw_templates = described.get("templates") or {}
    described["templates"] = {
        str(key): value for key, value in raw_templates.items() if isinstance(value, str)
    }
    return WhatsAppSettingsOut(**described)


def _readiness_warning(settings_obj) -> str:
    """Motif pour lequel le canal ne pourrait pas émettre, ou chaîne vide.

    Les motifs viennent de `is_configured()` et ne contiennent jamais la clé —
    seulement le fait qu'elle manque.
    """
    if not settings_obj.enabled:
        return "Le canal WhatsApp est désactivé : aucun message ne partira."
    ok, reason = get_provider(settings_obj.provider, settings_obj.provider_config).is_configured()
    return "" if ok else reason


async def _settings_envelope(db: AsyncSession, tenant_id: int) -> WhatsAppSettingsEnvelope:
    """Réponse complète des réglages : l'état, et de quoi l'éditer.

    Construite au même endroit pour la lecture et pour l'écriture — un `PUT` qui
    ne rendrait pas exactement ce que rend le `GET` obligerait l'écran à
    recharger pour se croire à jour.
    """
    row = await _settings_row(db, tenant_id)
    settings_obj = await load_whatsapp_settings(
        db, tenant_id, await _organisation_name(db, tenant_id)
    )
    return WhatsAppSettingsEnvelope(
        settings=_public_settings(row),
        providers=[ProviderOption(**option) for option in available_providers()],
        default_templates=dict(wa_templates.DEFAULT_TEMPLATES),
        template_variables=dict(wa_templates.TEMPLATE_VARIABLES),
        events=[
            EventOption(
                value=event,
                label=EVENT_LABELS.get(event, event),
                family=_event_family(event),
            )
            for event in _ordered_events()
        ],
        warning=_readiness_warning(settings_obj),
    )


def _member_status(member: CommissionMember) -> str:
    if not normalize_phone(getattr(member, "telephone", None)):
        return "no_phone"
    if not bool(getattr(member, "notify_whatsapp", False)):
        return "opted_out"
    return "ready"


def _recipient_out(member: CommissionMember) -> RecipientOut:
    normalized = normalize_phone(getattr(member, "telephone", None)) or ""
    state = _member_status(member)
    return RecipientOut(
        id=member.id,
        full_name=member.full_name or "",
        function=_member_function_label(member),
        service_id=getattr(member, "service_id", None),
        email=getattr(member, "email", None),
        phone=normalized,
        phone_display=format_phone_display(normalized),
        notify_whatsapp=bool(getattr(member, "notify_whatsapp", False)),
        status=state,
        status_label=RECIPIENT_STATUS_LABELS.get(state, state),
    )


def _display_recipient(value: str | None, *, full: bool) -> str:
    """Numéro tel qu'il doit apparaître à cet utilisateur-ci.

    Une ligne `SKIPPED` porte parfois une saisie inexploitable (« (vide) »,
    un texte). Elle n'est montrée entière qu'à qui a droit à l'historique
    complet — c'est encore une donnée personnelle.
    """
    raw = value or ""
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw if full else "•••"
    if full:
        return format_phone_display(raw) or raw
    return mask_phone(raw)


def _log_out(row: NotificationLog, *, full: bool) -> NotificationLogOut:
    return NotificationLogOut(
        id=str(row.id),
        channel=row.channel,
        event_type=row.event_type,
        event_label=EVENT_LABELS.get(row.event_type, row.event_type),
        entity_type=row.entity_type or "",
        entity_id=row.entity_id or "",
        recipient=_display_recipient(row.recipient, full=full),
        recipient_name=row.recipient_name or "",
        recipient_role=row.recipient_role or "",
        message=row.message or "",
        status=row.status,
        status_label=STATUS_LABELS.get(row.status, row.status),
        provider=row.provider or "",
        provider_message_id=row.provider_message_id,
        error_message=row.error_message,
        attempts=int(row.attempts or 0),
        created_at=row.created_at,
        sent_at=row.sent_at,
    )


def _delivery_out(row: NotificationLog, *, full: bool) -> DeliveryOut:
    return DeliveryOut(
        log_id=str(row.id),
        recipient=_display_recipient(row.recipient, full=full),
        recipient_name=row.recipient_name or "",
        status=row.status,
        status_label=STATUS_LABELS.get(row.status, row.status),
        error_message=row.error_message,
    )


def _parse_datetime(value: str | None, end_of_day: bool = False) -> datetime | None:
    """Même tolérance que `audit_logs.py` : « 2026-08-23 » ou un ISO complet."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end_of_day and len(value) <= 10:
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


# ── Réglages ─────────────────────────────────────────────────────────────────


@router.get(
    "/settings",
    response_model=WhatsAppSettingsEnvelope,
    dependencies=[Depends(has_permission(PERM_READ))],
)
async def get_whatsapp_settings(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> WhatsAppSettingsEnvelope:
    """Réglages publics du tenant, plus tout ce qu'il faut pour les éditer."""
    return await _settings_envelope(db, tenant_id)


@router.put(
    "/settings",
    response_model=WhatsAppSettingsEnvelope,
    dependencies=[Depends(has_permission(PERM_UPDATE))],
)
async def update_whatsapp_settings(
    payload: WhatsAppSettingsUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> WhatsAppSettingsEnvelope:
    """Enregistre les réglages. La clé API est chiffrée avant d'atteindre la base.

    Sentinelle : `api_key` absente ou vide ne touche pas la clé en place. Sa
    suppression est un geste explicite (`clear_api_key`), pour qu'un formulaire
    qui renvoie un champ mot de passe vide n'efface pas une clé opérationnelle.
    """
    row = await _settings_row(db, tenant_id)
    data = payload.model_dump(exclude_unset=True)

    columns = {
        "enabled": "whatsapp_enabled",
        "notify_payments": "whatsapp_notify_payments",
        "notify_sorties": "whatsapp_notify_sorties",
        "provider": "whatsapp_provider",
        "api_url": "whatsapp_api_url",
        "sender": "whatsapp_sender",
        "phone_number_id": "whatsapp_phone_number_id",
        "business_account_id": "whatsapp_business_account_id",
    }
    booleans = {"enabled", "notify_payments", "notify_sorties"}

    touched: list[str] = []
    for field, column in columns.items():
        if field not in data or data[field] is None:
            continue
        value = bool(data[field]) if field in booleans else str(data[field]).strip()
        _assign(row, column, value)
        touched.append(field)

    # La clé, à part : c'est le seul champ dont l'absence a un sens.
    if payload.clear_api_key:
        _assign(row, "whatsapp_api_key_encrypted", "")
        # L'ancienne colonne en clair sert encore de repli à `resolve_api_key` :
        # la laisser garnie ressusciterait la clé qu'on vient de supprimer.
        _assign(row, "whatsapp_api_key", "")
        touched.append("api_key:cleared")
    elif (payload.api_key or "").strip():
        _assign(row, "whatsapp_api_key_encrypted", encrypt_secret(payload.api_key.strip()))
        # Reprise annoncée par `settings_loader` : après une sauvegarde, la clé
        # ne vit plus qu'en chiffré.
        _assign(row, "whatsapp_api_key", "")
        touched.append("api_key:set")

    row.updated_at = _utcnow()
    row.updated_by = getattr(current_user, "id", None)

    # Valeurs journalisées : jamais la clé, seulement le fait qu'elle a bougé.
    await log_action(
        db,
        user_id=current_user.id,
        action="WHATSAPP_SETTINGS_UPDATED",
        target_table="system_settings",
        target_id=str(row.id),
        new_value={"fields": touched},
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await consolidate_system_settings(db, tenant_id)

    # Relu après consolidation : celle-ci peut fusionner des lignes en double et
    # la réponse doit décrire la ligne qui fait désormais foi.
    return await _settings_envelope(db, tenant_id)


# ── Destinataires ────────────────────────────────────────────────────────────


@router.get(
    "/recipients",
    response_model=list[RecipientOut],
    dependencies=[Depends(has_permission(PERM_READ))],
)
async def list_whatsapp_recipients(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RecipientOut]:
    """Membres du Bureau du tenant, opt-in compris.

    `only_opted_in=False` : l'écran doit montrer aussi ceux qui ne reçoivent
    rien, sans quoi on ne peut pas les activer.
    """
    members = await load_bureau_members(db, tenant_id, only_opted_in=False)
    return [_recipient_out(member) for member in members]


@router.patch(
    "/recipients/{member_id}",
    response_model=RecipientOut,
    dependencies=[Depends(has_permission(PERM_UPDATE))],
)
async def update_whatsapp_recipient(
    member_id: int,
    payload: RecipientUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RecipientOut:
    """Modifie le numéro et l'opt-in d'un membre du Bureau.

    Le numéro est stocké normalisé (E.164 sans « + ») : `phone.py` est le point
    unique de vérité, et un numéro rangé sous deux formes se dé-duplique mal.
    """
    member = await _load_member(db, tenant_id, member_id)
    data = payload.model_dump(exclude_unset=True)

    before = {
        "telephone": getattr(member, "telephone", None),
        "notify_whatsapp": bool(getattr(member, "notify_whatsapp", False)),
    }

    if "telephone" in data:
        raw = (data.get("telephone") or "").strip()
        if not raw:
            _assign_member(member, "telephone", None)
        else:
            normalized = normalize_phone(raw)
            if not normalized:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Numéro inexploitable. Attendu : un numéro national "
                        "(0810123456) ou international (+243810123456)."
                    ),
                )
            _assign_member(member, "telephone", normalized)

    if data.get("notify_whatsapp") is not None:
        _assign_member(member, "notify_whatsapp", bool(data["notify_whatsapp"]))

    await log_action(
        db,
        user_id=current_user.id,
        action="WHATSAPP_RECIPIENT_UPDATED",
        target_table="commission_members",
        target_id=str(member.id),
        old_value=before,
        new_value={
            "telephone": getattr(member, "telephone", None),
            "notify_whatsapp": bool(getattr(member, "notify_whatsapp", False)),
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    # Pas de `refresh()` : la session est ouverte avec `expire_on_commit=False`,
    # l'objet porte déjà ses nouvelles valeurs. Un refresh expirerait au passage
    # la relation `function` chargée en `selectinload`, et sa relecture
    # paresseuse lèverait un `MissingGreenlet` en contexte asynchrone.
    return _recipient_out(member)


def _assign_member(member: CommissionMember, column: str, value) -> None:
    if not hasattr(type(member), column):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Colonne « {} » absente : la migration des notifications WhatsApp "
                "n'a pas été appliquée."
            ).format(column),
        )
    setattr(member, column, value)


# ── Gabarits ─────────────────────────────────────────────────────────────────


def _current_overrides(row: SystemSettings | None) -> dict[str, str]:
    raw = getattr(row, "whatsapp_templates", None)
    if not isinstance(raw, dict):
        return {}
    return {str(key): value for key, value in raw.items() if isinstance(value, str) and value.strip()}


@router.get(
    "/templates",
    response_model=TemplatesEnvelope,
    dependencies=[Depends(has_permission(PERM_READ))],
)
async def get_whatsapp_templates(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TemplatesEnvelope:
    """Gabarit effectif de chaque événement, avec son défaut pour comparaison."""
    row = await _settings_row(db, tenant_id)
    overrides = _current_overrides(row)

    return TemplatesEnvelope(
        items=[
            TemplateOut(
                event_type=event,
                label=EVENT_LABELS.get(event, event),
                family=_event_family(event),
                template=wa_templates.resolve(event, overrides),
                default_template=wa_templates.DEFAULT_TEMPLATES.get(event, ""),
                is_custom=event in overrides,
            )
            for event in _ordered_events()
        ],
        variables=dict(wa_templates.TEMPLATE_VARIABLES),
    )


@router.put(
    "/templates",
    response_model=TemplatesSaveResult,
    dependencies=[Depends(has_permission(PERM_UPDATE))],
)
async def update_whatsapp_templates(
    payload: TemplatesUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> TemplatesSaveResult:
    """Enregistre des surcharges de gabarits, une par événement.

    Une valeur vide retire la surcharge : l'événement repart sur le gabarit par
    défaut, sans qu'on ait à recopier le texte d'origine. Chaque gabarit passe
    par `validate_template` — un refus est bloquant, un avertissement (variable
    inconnue) ne l'est pas et remonte dans `warnings`.
    """
    row = await _settings_row(db, tenant_id)
    overrides = _current_overrides(row)

    updated: list[str] = []
    reset: list[str] = []
    warnings: dict[str, str] = {}

    for event_type, raw_value in payload.templates.items():
        if event_type not in ALL_EVENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Événement inconnu : « {event_type} ».",
            )
        text = (raw_value or "").strip()
        if not text:
            overrides.pop(event_type, None)
            reset.append(event_type)
            continue

        ok, message = wa_templates.validate_template(text)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{EVENT_LABELS.get(event_type, event_type)} : {message}",
            )
        if message:
            warnings[event_type] = message
        overrides[event_type] = text
        updated.append(event_type)

    # Réaffectation d'un dictionnaire neuf : une colonne JSONB simple n'est pas
    # observée en mutation, une modification en place passerait inaperçue.
    _assign(row, "whatsapp_templates", dict(overrides) if overrides else None)
    row.updated_at = _utcnow()
    row.updated_by = getattr(current_user, "id", None)

    await log_action(
        db,
        user_id=current_user.id,
        action="WHATSAPP_TEMPLATES_UPDATED",
        target_table="system_settings",
        target_id=str(row.id),
        new_value={"updated": updated, "reset": reset},
        ip_address=get_request_ip(request),
    )
    await db.commit()

    return TemplatesSaveResult(ok=True, updated=updated, reset=reset, warnings=warnings)


# ── Journal ──────────────────────────────────────────────────────────────────


@router.get(
    "/logs",
    response_model=NotificationLogPage,
    dependencies=[Depends(has_any_permission([PERM_READ, PERM_HISTORY]))],
)
async def list_whatsapp_logs(
    status_filter: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    date_debut: str | None = Query(default=None),
    date_fin: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> NotificationLogPage:
    """Historique paginé des envois du tenant.

    Le filtre d'organisation est une égalité stricte : une ligne sans
    organisation n'appartient à personne et n'a rien à faire ici.

    Les numéros sont masqués pour qui n'a pas `treso.notifications.history` — la
    permission de lecture ouvre l'écran, pas le carnet d'adresses.
    """
    conditions = [NotificationLog.organisation_id == tenant_id]

    if status_filter:
        wanted = status_filter.strip().upper()
        if wanted not in KNOWN_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Statut inconnu : « {status_filter} ». Attendu : {sorted(KNOWN_STATUSES)}.",
            )
        conditions.append(NotificationLog.status == wanted)

    if channel:
        conditions.append(NotificationLog.channel == channel.strip().upper())
    if event_type:
        conditions.append(NotificationLog.event_type == event_type.strip())
    if entity_type:
        conditions.append(NotificationLog.entity_type == entity_type.strip())
    if entity_id:
        conditions.append(NotificationLog.entity_id == str(entity_id).strip())

    start = _parse_datetime(date_debut)
    end = _parse_datetime(date_fin, end_of_day=True)
    if start:
        conditions.append(NotificationLog.created_at >= start)
    if end:
        conditions.append(NotificationLog.created_at <= end)

    total = (
        await db.execute(select(func.count()).select_from(NotificationLog).where(*conditions))
    ).scalar_one()

    rows = (
        (
            await db.execute(
                select(NotificationLog)
                .where(*conditions)
                .order_by(NotificationLog.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )

    full = await _has_permission_code(db, current_user, PERM_HISTORY)
    return NotificationLogPage(
        items=[_log_out(row, full=full) for row in rows],
        total=int(total or 0),
        limit=limit,
        offset=offset,
        masked=not full,
    )


# ── Envoi de vérification ────────────────────────────────────────────────────


@router.post(
    "/test",
    response_model=WhatsAppTestResult,
    dependencies=[Depends(has_permission(PERM_TEST))],
)
async def send_whatsapp_test(
    payload: WhatsAppTestRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> WhatsAppTestResult:
    """Envoie un message de vérification, à un numéro libre ou à un membre du Bureau.

    Deux choix assumés :

    * L'envoi passe par `notify_whatsapp` sans `BackgroundTasks`, donc il est
      **attendu dans la requête**. Un test dont on n'apprendrait le sort qu'en
      rafraîchissant l'historique ne testerait rien d'utile.
    * Le `nonce` garantit que deux tests consécutifs vers le même numéro partent
      tous les deux : la contrainte d'unicité sur `dedup_key` avalerait le
      second sans lui.
    """
    org_name = await _organisation_name(db, tenant_id)
    settings_obj = await load_whatsapp_settings(db, tenant_id, org_name)

    if not settings_obj.enabled:
        # Sans ce garde-fou, `queue_whatsapp` renvoie zéro ligne en silence et
        # l'écran ne saurait pas distinguer « désactivé » de « panne ».
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Activez le canal WhatsApp avant d'envoyer un message de test.",
        )

    if payload.member_id is not None:
        member = await _load_member(db, tenant_id, payload.member_id)
        normalized = normalize_phone(getattr(member, "telephone", None))
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{member.full_name or 'Ce membre'} n'a pas de numéro exploitable.",
            )
        recipient = Recipient(
            phone=normalized,
            name=member.full_name or "",
            role=_member_function_label(member),
        )
    else:
        normalized = normalize_phone(payload.phone)
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Numéro inexploitable. Attendu : un numéro national "
                    "(0810123456) ou international (+243810123456)."
                ),
            )
        recipient = Recipient(phone=normalized, name="", role="")

    # `entity_id` porte le nonce : il rend la lecture du résultat exacte, sans
    # avoir à deviner quelles lignes viennent de cet appel-ci.
    nonce = uuid.uuid4().hex
    queued = await notify_whatsapp(
        db,
        None,
        organisation_id=tenant_id,
        event_type=TEST_MESSAGE,
        entity_type=TEST_ENTITY_TYPE,
        entity_id=nonce,
        recipients=[recipient],
        variables={"date": _utcnow().strftime("%d/%m/%Y à %H:%M UTC")},
        settings=settings_obj,
        nonce=nonce,
    )

    rows = (
        (
            await db.execute(
                select(NotificationLog)
                .where(
                    NotificationLog.organisation_id == tenant_id,
                    NotificationLog.entity_type == TEST_ENTITY_TYPE,
                    NotificationLog.entity_id == nonce,
                )
                .order_by(NotificationLog.created_at.asc())
                # La remise a écrit son statut depuis sa propre session : sans
                # cela, l'identity map de la requête rendrait l'état d'avant.
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )

    full = await _has_permission_code(db, current_user, PERM_HISTORY)
    deliveries = [_delivery_out(row, full=full) for row in rows]
    sent = [item for item in deliveries if item.status == STATUS_SENT]

    await log_action(
        db,
        user_id=current_user.id,
        action="WHATSAPP_TEST_SENT",
        target_table="notification_logs",
        target_id=nonce,
        new_value={"queued": queued, "sent": len(sent)},
        ip_address=get_request_ip(request),
    )
    await db.commit()

    if sent:
        detail = "Message de test envoyé."
    elif deliveries:
        detail = deliveries[0].error_message or "L'envoi a échoué."
    else:
        detail = "Aucun message n'a été mis en file : vérifiez la configuration."

    return WhatsAppTestResult(
        ok=bool(sent),
        queued=queued,
        detail=detail,
        deliveries=deliveries,
    )


@router.post(
    "/logs/{log_id}/resend",
    response_model=ResendResult,
    dependencies=[Depends(has_permission(PERM_TEST))],
)
async def resend_whatsapp_log(
    log_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ResendResult:
    """Renvoie une ligne du journal restée en échec.

    On **recopie** la ligne d'origine plutôt que de la rejouer : le message
    d'origine est conservé mot pour mot (les variables qui l'ont produit ne sont
    pas stockées, un re-rendu laisserait des trous), la tentative ratée reste
    visible dans l'historique, et la nouvelle ligne porte un `nonce` qui la fait
    passer devant la contrainte d'unicité sur `dedup_key`.
    """
    try:
        source_id = uuid.UUID(str(log_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ligne de journal introuvable."
        )

    source = (
        await db.execute(
            select(NotificationLog).where(
                NotificationLog.id == source_id,
                NotificationLog.organisation_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ligne de journal introuvable."
        )

    if source.channel != CHANNEL_WHATSAPP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seuls les envois WhatsApp peuvent être renvoyés depuis cet écran.",
        )
    if source.status != STATUS_FAILED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Seule une ligne en échec peut être renvoyée "
                f"(statut actuel : {STATUS_LABELS.get(source.status, source.status)})."
            ),
        )

    settings_obj = await load_whatsapp_settings(db, tenant_id, await _organisation_name(db, tenant_id))
    if not settings_obj.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le canal WhatsApp est désactivé : réactivez-le avant de renvoyer.",
        )

    nonce = uuid.uuid4().hex
    clone = NotificationLog(
        organisation_id=tenant_id,
        channel=source.channel,
        event_type=source.event_type,
        entity_type=source.entity_type or "",
        entity_id=source.entity_id or "",
        recipient=source.recipient,
        recipient_name=source.recipient_name or "",
        recipient_role=source.recipient_role or "",
        message=source.message or "",
        status=STATUS_PENDING,
        provider=settings_obj.provider,
        dedup_key=build_dedup_key(
            organisation_id=tenant_id,
            event_type=source.event_type,
            entity_type=source.entity_type or "",
            entity_id=source.entity_id or "",
            channel=source.channel,
            recipient=source.recipient,
            nonce=nonce,
        ),
        created_at=_utcnow(),
    )
    db.add(clone)
    await db.flush()
    new_id = clone.id

    await log_action(
        db,
        user_id=current_user.id,
        action="WHATSAPP_LOG_RESENT",
        target_table="notification_logs",
        target_id=str(source_id),
        new_value={"new_log_id": str(new_id)},
        ip_address=get_request_ip(request),
    )
    await db.commit()

    # Remise attendue dans la requête, comme pour le test : l'utilisateur a
    # cliqué « Renvoyer », il attend un verdict, pas un accusé de dépôt.
    await deliver_pending([new_id], settings_obj, tenant_id)

    refreshed = (
        await db.execute(
            select(NotificationLog)
            .where(NotificationLog.id == new_id, NotificationLog.organisation_id == tenant_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()

    full = await _has_permission_code(db, current_user, PERM_HISTORY)
    delivery = _delivery_out(refreshed, full=full) if refreshed is not None else None
    ok = bool(delivery and delivery.status == STATUS_SENT)

    return ResendResult(
        ok=ok,
        detail=(
            "Message renvoyé."
            if ok
            else ((delivery.error_message if delivery else None) or "Le renvoi a échoué.")
        ),
        source_log_id=str(source_id),
        delivery=delivery,
    )
