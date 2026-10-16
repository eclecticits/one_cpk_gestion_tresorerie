"""Justificatif attendu après une sortie de fonds, et messages au bénéficiaire.

Le parcours, tel que la caisse le vit :

1. **Décaissement.** Le bénéficiaire reçoit un message (WhatsApp et/ou e-mail),
   la liste « Copie au paiement » en copie. Si la sortie attend un
   justificatif, le message annonce un délai de 48 h.
2. **Dépôt.** Le bénéficiaire rapporte la pièce ; le caissier la scanne et la
   joint à la ligne de sortie. Le statut passe à RECU.
3. **J+7 sans pièce.** Le message est renvoyé, une seule fois, cette fois avec
   les « Autorités en relance » en copie.

Quelles sorties attendent un justificatif : celles imputées à un poste coché
dans les paramètres (`justificatif_postes_codes`), un code couvrant ses
sous-postes. Le caissier peut décider autrement sur chaque sortie.

Aucune de ces notifications ne peut faire échouer une sortie : tout est
encapsulé, au pire un envoi manque et le journal le dit.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.budget import BudgetPoste
from app.models.organisation import Organisation
from app.models.sortie_fonds import SortieFonds
from app.services.mailer import _format_brand_label, normalize_email_list, send_beneficiaire_sortie_email, send_in_thread
from app.services.notifications import events
from app.services.notifications import templates
from app.services.notifications.phone import normalize_phone, normalize_phone_list
from app.services.notifications.service import Recipient, notify_whatsapp
from app.services.notifications.settings_loader import load_whatsapp_settings

logger = logging.getLogger("onec_cpk_api.justificatifs")

STATUT_NON_REQUIS = "NON_REQUIS"
STATUT_ATTENDU = "ATTENDU"
STATUT_RECU = "RECU"
STATUT_DISPENSE = "DISPENSE"
#: Lu, jamais stocké : un ATTENDU dont l'échéance est passée.
STATUT_EN_RETARD = "EN_RETARD"

#: Délai annoncé au bénéficiaire dans le message du décaissement.
DELAI_DEPOT = timedelta(hours=48)
#: Délai au bout duquel le message est renvoyé, autorités en copie.
DELAI_RELANCE = timedelta(days=7)

ENTITY_SORTIE = "sortie_fonds"

#: Types de sortie qui ne paient personne : mouvements internes de trésorerie.
TYPES_SANS_BENEFICIAIRE = frozenset(
    {"versement_banque", "approvisionnement_caisse", "regularisation_caisse"}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fuseau() -> ZoneInfo:
    try:
        return ZoneInfo((app_settings.weekly_report_timezone or "UTC").strip() or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def _date_locale(value: datetime | None, *, heure: bool = False) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(_fuseau())
    return local.strftime("%d/%m/%Y à %Hh%M") if heure else local.strftime("%d/%m/%Y")


def _montant(value) -> str:
    try:
        return f"{float(value or 0):,.2f}".replace(",", " ")
    except (TypeError, ValueError):
        return "0.00"


# ── Quelles sorties attendent un justificatif ────────────────────────────────


def code_exige_justificatif(codes_exiges: Iterable[str] | None, code_poste: str | None) -> bool:
    """Le poste est-il coché, ou rangé sous un poste coché ?"""
    code = (code_poste or "").strip()
    if not code:
        return False
    for exige in codes_exiges or ():
        exige = (exige or "").strip()
        if exige and (code == exige or code.startswith(exige + ".")):
            return True
    return False


async def postes_exigent_justificatif(
    db: AsyncSession,
    organisation_id: int,
    codes_exiges: Iterable[str] | None,
    poste_ids: Iterable[int],
) -> bool:
    codes = [c for c in (codes_exiges or []) if (c or "").strip()]
    ids = sorted({int(i) for i in poste_ids if i is not None})
    if not codes or not ids:
        return False
    rows = (
        await db.execute(
            select(BudgetPoste.code).where(
                BudgetPoste.organisation_id == organisation_id,
                BudgetPoste.id.in_(ids),
            )
        )
    ).scalars().all()
    return any(code_exige_justificatif(codes, code) for code in rows)


def poser_attente(sortie: SortieFonds, requis: bool, *, depart: datetime | None = None) -> None:
    """Fixe l'attente du justificatif : 48 h à partir du décaissement.

    `depart` sert quand le caissier exige la pièce après coup : le délai court
    alors de sa décision, sans quoi un justificatif exigé au dixième jour
    serait relancé avant même que le bénéficiaire en ait été averti.
    """
    if requis:
        # Le délai court de l'instant du décaissement, pas de la date de
        # paiement : celle-ci est souvent saisie seule, à minuit, et une sortie
        # payée à 23 h n'aurait laissé qu'une nuit et un jour.
        depart = depart or _utcnow()
        sortie.justificatif_statut = STATUT_ATTENDU
        sortie.justificatif_echeance = depart + DELAI_DEPOT
        sortie.justificatif_relance_le = None
        sortie.justificatif_motif_dispense = None
    else:
        sortie.justificatif_statut = STATUT_NON_REQUIS
        sortie.justificatif_echeance = None


def statut_affiche(sortie: SortieFonds, now: datetime | None = None) -> str:
    statut = sortie.justificatif_statut or STATUT_NON_REQUIS
    if statut == STATUT_ATTENDU and sortie.justificatif_echeance is not None:
        if (now or _utcnow()) > sortie.justificatif_echeance:
            return STATUT_EN_RETARD
    return statut


def relance_prevue_le(sortie: SortieFonds) -> datetime | None:
    """J+7 après le point de départ du délai, lu de l'échéance (départ + 48 h)."""
    if (sortie.justificatif_statut or "") != STATUT_ATTENDU or sortie.justificatif_echeance is None:
        return None
    return sortie.justificatif_echeance - DELAI_DEPOT + DELAI_RELANCE


# ── Messages ─────────────────────────────────────────────────────────────────


def _variables(sortie: SortieFonds, *, canal: str = "") -> dict:
    attendu = (sortie.justificatif_statut or "") == STATUT_ATTENDU
    echeance = _date_locale(sortie.justificatif_echeance, heure=True)
    nom = (sortie.beneficiaire or "").strip()
    return {
        "salutation": f"Bonjour {nom}," if nom else "Madame, Monsieur,",
        "reference": sortie.reference_numero or sortie.reference or "",
        "date": _date_locale(sortie.date_paiement or sortie.created_at),
        "beneficiaire": nom,
        "motif": sortie.motif or "",
        "montant": _montant(sortie.montant_paye),
        "devise": sortie.devise or "USD",
        "canal": canal,
        "echeance": echeance if attendu else "",
        "consigne_justificatif": (
            "Merci de déposer la pièce justificative à la caisse dans les 48 heures, "
            f"au plus tard le {echeance}."
            if attendu and echeance
            else ""
        ),
    }


def _destinataires_whatsapp(sortie: SortieFonds, copies: str | None, role_copie: str) -> list[Recipient]:
    recipients: list[Recipient] = []
    vus: set[str] = set()
    # Un bénéficiaire identifié sans numéro laisse une trace « ignoré » au
    # journal : c'est ce qui distingue « pas de numéro » de « pas envoyé ».
    if sortie.beneficiaire_type:
        numero = normalize_phone(sortie.beneficiaire_telephone)
        if numero:
            vus.add(numero)
        recipients.append(
            Recipient(phone=numero or sortie.beneficiaire_telephone or "", name=sortie.beneficiaire or "", role="Bénéficiaire")
        )
    for numero in normalize_phone_list(copies):
        if numero in vus:
            continue
        vus.add(numero)
        recipients.append(Recipient(phone=numero, name="", role=role_copie))
    return recipients


async def _envoyer(
    db: AsyncSession,
    background_tasks,
    *,
    sortie: SortieFonds,
    organisation_id: int,
    event_type: str,
    copies_whatsapp: str | None,
    copies_emails: str | None,
    role_copie: str,
    sujet: str,
    titre: str,
    canal: str = "",
    smtp_cfg=None,
    nonce: str = "",
) -> None:
    org_name = (
        await db.execute(select(Organisation.nom).where(Organisation.id == organisation_id).limit(1))
    ).scalar_one_or_none() or ""
    variables = _variables(sortie, canal=canal)
    # Snapshot des scalaires AVANT toute écriture : `notify_whatsapp` commite,
    # et relire `sortie` ensuite déclencherait un chargement différé.
    email_beneficiaire = (sortie.beneficiaire_email or "").strip()
    reference = variables["reference"] or str(sortie.id)
    sortie_id = str(sortie.id)

    try:
        wa_settings = await load_whatsapp_settings(db, organisation_id, org_name)
        if wa_settings.accepts(event_type):
            recipients = _destinataires_whatsapp(sortie, copies_whatsapp, role_copie)
            if recipients:
                await notify_whatsapp(
                    db,
                    background_tasks,
                    organisation_id=organisation_id,
                    event_type=event_type,
                    entity_type=ENTITY_SORTIE,
                    entity_id=sortie_id,
                    recipients=recipients,
                    variables=variables,
                    settings=wa_settings,
                    # Une relance à la main est un nouvel envoi : sans nonce, la
                    # dé-duplication du journal la prendrait pour un doublon.
                    nonce=nonce,
                )
        texte_template = templates.resolve(event_type, wa_settings.templates)
    except Exception:
        logger.exception("justificatifs.whatsapp_failed sortie=%s event=%s", sortie_id, event_type)
        texte_template = templates.resolve(event_type, None)

    try:
        if smtp_cfg is None:
            return
        to = [email_beneficiaire] if email_beneficiaire else []
        cc = normalize_email_list(copies_emails)
        if not to and not cc:
            return
        texte = templates.render(texte_template, {**variables, "organisation": org_name})
        kwargs = dict(
            smtp_host=smtp_cfg.host,
            smtp_port=smtp_cfg.port,
            smtp_user=smtp_cfg.user,
            smtp_password=smtp_cfg.password,
            sender=smtp_cfg.sender,
            to_emails=to,
            cc_emails=cc,
            subject=f"{sujet} - {reference}",
            titre=titre,
            reference=reference,
            texte=texte,
            brand_label=_format_brand_label("ONEC", org_name),
        )
        if background_tasks is not None:
            background_tasks.add_task(send_beneficiaire_sortie_email, **kwargs)
        else:
            await send_in_thread(send_beneficiaire_sortie_email, **kwargs)
    except Exception:
        logger.exception("justificatifs.email_failed sortie=%s event=%s", sortie_id, event_type)


async def notifier_remise(
    db: AsyncSession,
    background_tasks,
    *,
    sortie: SortieFonds,
    organisation_id: int,
    canal: str = "",
) -> None:
    """Message du décaissement : au bénéficiaire, « Copie au paiement » en copie.

    À appeler après le `commit()` de la sortie. Ne lève jamais.
    """
    try:
        if (sortie.type_sortie or "").lower() in TYPES_SANS_BENEFICIAIRE:
            return
        from app.services.email_config import resolve_smtp_config
        from app.services.system_settings_service import get_system_settings

        ns = await get_system_settings(db, organisation_id)
        await _envoyer(
            db,
            background_tasks,
            sortie=sortie,
            organisation_id=organisation_id,
            event_type=events.FUND_OUTFLOW_BENEFICIARY,
            copies_whatsapp=getattr(ns, "sortie_copie_whatsapp", "") if ns else "",
            copies_emails=getattr(ns, "sortie_copie_emails", "") if ns else "",
            role_copie="Copie au paiement",
            sujet="Fonds remis",
            titre="Fonds remis",
            canal=canal,
            smtp_cfg=resolve_smtp_config(ns),
        )
    except Exception:
        logger.exception("justificatifs.remise_failed sortie=%s", getattr(sortie, "id", None))


async def relancer(db: AsyncSession, *, sortie_id, organisation_id: int, background_tasks=None) -> bool:
    """Relance unique d'un justificatif non rapporté. Renvoie True si elle part.

    Le verrou est la colonne elle-même : `justificatif_relance_le` est posée par
    un UPDATE conditionnel AVANT l'envoi. Deux passages concurrents ne peuvent
    pas l'obtenir tous les deux, et une relance qui échoue n'est pas retentée
    en boucle — elle reste visible à l'écran, le caissier peut appeler.
    """
    claimed = (
        await db.execute(
            update(SortieFonds)
            .where(
                SortieFonds.id == sortie_id,
                SortieFonds.organisation_id == organisation_id,
                SortieFonds.justificatif_statut == STATUT_ATTENDU,
                SortieFonds.justificatif_relance_le.is_(None),
                SortieFonds.statut != "ANNULEE",
            )
            .values(
                justificatif_relance_le=_utcnow(),
                justificatif_derniere_relance_le=_utcnow(),
                justificatif_nb_relances=SortieFonds.justificatif_nb_relances + 1,
            )
            .returning(SortieFonds.id)
        )
    ).scalar_one_or_none()
    await db.commit()
    if claimed is None:
        return False
    await _envoyer_relance(db, sortie_id=sortie_id, organisation_id=organisation_id, background_tasks=background_tasks)
    return True


#: Écart minimal entre deux relances à la main : protège d'un double clic, qui
#: enverrait deux e-mails coup sur coup.
ECART_RELANCE_MANUELLE = timedelta(minutes=1)


async def relancer_manuellement(
    db: AsyncSession, *, sortie_id, organisation_id: int, background_tasks=None
) -> bool:
    """Relance demandée par le caissier, à tout moment tant que la pièce est attendue.

    Même message et mêmes copies que la relance automatique. Elle ne remplace
    pas celle-ci : la relance de J+7 part quand même si elle n'est pas encore
    partie. Renvoie False si une relance vient d'être envoyée.
    """
    now = _utcnow()
    claimed = (
        await db.execute(
            update(SortieFonds)
            .where(
                SortieFonds.id == sortie_id,
                SortieFonds.organisation_id == organisation_id,
                SortieFonds.justificatif_statut == STATUT_ATTENDU,
                SortieFonds.statut != "ANNULEE",
                (SortieFonds.justificatif_derniere_relance_le.is_(None))
                | (SortieFonds.justificatif_derniere_relance_le < now - ECART_RELANCE_MANUELLE),
            )
            .values(
                justificatif_derniere_relance_le=now,
                justificatif_nb_relances=SortieFonds.justificatif_nb_relances + 1,
            )
            .returning(SortieFonds.id)
        )
    ).scalar_one_or_none()
    await db.commit()
    if claimed is None:
        return False
    await _envoyer_relance(
        db,
        sortie_id=sortie_id,
        organisation_id=organisation_id,
        background_tasks=background_tasks,
        nonce=f"manuelle-{now.isoformat()}",
    )
    return True


async def _envoyer_relance(db: AsyncSession, *, sortie_id, organisation_id: int, background_tasks=None, nonce: str = "") -> None:
    sortie = (
        await db.execute(select(SortieFonds).where(SortieFonds.id == sortie_id))
    ).scalar_one()
    from app.services.email_config import resolve_smtp_config
    from app.services.system_settings_service import get_system_settings

    ns = await get_system_settings(db, organisation_id)
    await _envoyer(
        db,
        background_tasks,
        sortie=sortie,
        organisation_id=organisation_id,
        event_type=events.JUSTIFICATIF_RELANCE,
        copies_whatsapp=getattr(ns, "justificatif_autorites_whatsapp", "") if ns else "",
        copies_emails=getattr(ns, "justificatif_autorites_emails", "") if ns else "",
        role_copie="Autorité",
        sujet="Justificatif non reçu",
        titre="Justificatif non reçu",
        smtp_cfg=resolve_smtp_config(ns),
        nonce=nonce,
    )


async def sorties_a_relancer(db: AsyncSession, organisation_id: int, now: datetime | None = None) -> list:
    # Relance à J+7 du départ, soit échéance (départ + 48 h) + 5 jours.
    limite = (now or _utcnow()) - (DELAI_RELANCE - DELAI_DEPOT)
    return list(
        (
            await db.execute(
                select(SortieFonds.id).where(
                    SortieFonds.organisation_id == organisation_id,
                    SortieFonds.justificatif_statut == STATUT_ATTENDU,
                    SortieFonds.justificatif_relance_le.is_(None),
                    SortieFonds.statut != "ANNULEE",
                    SortieFonds.justificatif_echeance <= limite,
                )
            )
        ).scalars().all()
    )


async def run_relances_justificatifs(session_factory=None) -> int:
    """Tâche planifiée : relance chaque justificatif attendu depuis 7 jours."""
    from app.core.tenant_context import set_current_tenant_id

    if session_factory is None:
        from app.db.session import SessionLocal

        session_factory = SessionLocal

    envoyees = 0
    async with session_factory() as db:
        locked = await db.scalar(text("SELECT pg_try_advisory_lock(hashtext('justificatifs_relance'))"))
        if not locked:
            logger.info("Relances de justificatifs : un autre processus tient le verrou.")
            return 0
        try:
            org_ids = (await db.execute(select(Organisation.id).order_by(Organisation.id))).scalars().all()
            for org_id in org_ids:
                try:
                    set_current_tenant_id(org_id)
                    for sortie_id in await sorties_a_relancer(db, org_id):
                        if await relancer(db, sortie_id=sortie_id, organisation_id=org_id):
                            envoyees += 1
                except Exception:
                    await db.rollback()
                    logger.exception("Relances de justificatifs en échec pour organisation_id=%s", org_id)
                finally:
                    set_current_tenant_id(None)
        finally:
            await db.execute(text("SELECT pg_advisory_unlock(hashtext('justificatifs_relance'))"))
            await db.commit()
    if envoyees:
        logger.info("Relances de justificatifs envoyées : %s", envoyees)
    return envoyees
