"""Transmission d'un rapport aux membres du Bureau, par e-mail et WhatsApp.

Le rapport lui-même est construit dans le navigateur (le même PDF que le bouton
« PDF » télécharge) : il arrive ici déjà fait, avec ses chiffres clés en texte.
Ce routeur ne sait donc rien d'un rapport particulier — projets aujourd'hui,
n'importe quel onglet des rapports demain.

* **E-mail** : comme la notification de réquisition — un seul message, le
  Président en destinataire et le Bureau en copie, d'après Paramètres ›
  Notifications, le PDF en pièce jointe.
* **WhatsApp** : aux membres choisis, le mot d'accompagnement et les chiffres
  clés, par le gabarit
  `REPORT_SENT` — le canal ne transporte pas de pièce jointe. Il passe par
  `notify_whatsapp`, donc par le journal des envois, et respecte l'opt-in : un
  numéro dans l'annuaire n'est pas un consentement à recevoir des messages.
* **Aucun emoji**, ni dans l'e-mail ni dans WhatsApp, y compris dans le mot
  saisi par l'expéditeur.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_tenant_id, get_current_user
from app.api.v1.endpoints.whatsapp import _group_by_person, _member_function_label
from app.db.session import get_db
from app.models.commission_member import CommissionMember
from app.models.notification_log import STATUS_SENT, NotificationLog
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.user import User
from app.services.audit_service import get_request_ip, log_action
from app.services.email_config import resolve_smtp_config
from app.services.mailer import bureau_email_recipients, send_in_thread, send_rapport_bureau_email
from app.services.notifications import (
    REPORT_SENT,
    Recipient,
    load_bureau_members,
    load_whatsapp_settings,
    normalize_phone,
    notify_whatsapp,
)
from app.services.notifications.templates import strip_emoji
from app.services.system_settings_service import get_system_settings
from app.utils.hierarchie_fonctions import rang_fonction

router = APIRouter()
logger = logging.getLogger("onec_cpk_api.envoi_rapports")

ENTITY_TYPE = "rapport_transmis"
MAX_PDF_SIZE = 10 * 1024 * 1024
MAX_MESSAGE = 2000
MAX_RECIPIENTS = 500
MAX_SUMMARY_LINES = 50


class DestinataireRapport(BaseModel):
    """Une personne, toutes ses fiches de service réunies."""

    id: int = Field(description="Fiche principale : celle de la fonction la plus haute.")
    member_ids: list[int] = Field(default_factory=list)
    nom: str = ""
    fonction: str = ""
    services: list[str] = Field(default_factory=list)
    email: str | None = None
    whatsapp: bool = Field(default=False, description="Numéro exploitable et opt-in WhatsApp.")
    bureau: bool = Field(default=False, description="Siège dans un service intitulé « Bureau ».")


class DestinatairesRapport(BaseModel):
    """E-mail : les adresses fixes du Bureau. WhatsApp : les membres à choisir."""

    email_to: list[str] = Field(default_factory=list, description="Le Président (Paramètres › Notifications).")
    email_cc: list[str] = Field(default_factory=list, description="Les adresses du Bureau en copie.")
    membres: list[DestinataireRapport] = Field(default_factory=list)


class EchecEnvoi(BaseModel):
    nom: str
    canal: str
    raison: str


class ResultatEnvoi(BaseModel):
    emails_envoyes: int = 0
    whatsapp_envoyes: int = 0
    echecs: list[EchecEnvoi] = Field(default_factory=list)


def _libelle_service(member: CommissionMember) -> str:
    service = getattr(member, "service", None)
    if service is None:
        return ""
    return getattr(service, "libelle", "") or getattr(service, "code", "") or ""


def _contact_whatsapp(group: list[CommissionMember]) -> tuple[CommissionMember, str] | None:
    """Première fiche portant à la fois le consentement et un numéro valide.

    Une personne peut avoir plusieurs fiches de service. Il ne faut jamais
    prendre le numéro d'une fiche et l'opt-in d'une autre : ce croisement
    transformerait deux informations incomplètes en un consentement fictif.
    """
    for member in group:
        telephone = normalize_phone(getattr(member, "telephone", None))
        if telephone and bool(getattr(member, "notify_whatsapp", False)):
            return member, telephone
    return None


def _destinataire(group: list[CommissionMember]) -> DestinataireRapport:
    main = min(group, key=lambda m: (rang_fonction(_member_function_label(m)), m.id))
    services: list[str] = []
    for member in group:
        label = _libelle_service(member)
        if label and label not in services:
            services.append(label)
    return DestinataireRapport(
        id=main.id,
        member_ids=[m.id for m in group],
        nom=main.full_name or "",
        fonction=_member_function_label(main),
        services=services,
        email=next((m.email.strip() for m in group if (m.email or "").strip()), None),
        whatsapp=_contact_whatsapp(group) is not None,
        bureau=any("bureau" in label.casefold() for label in services),
    )


@router.get("/destinataires", response_model=DestinatairesRapport)
async def lister_destinataires(
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> DestinatairesRapport:
    """Adresses e-mail du Bureau, et membres des services (Bureau d'abord) pour WhatsApp."""
    ns = await get_system_settings(db, tenant_id)
    to, cc = bureau_email_recipients(getattr(ns, "email_president", ""), getattr(ns, "emails_bureau_cc", ""))
    members = await load_bureau_members(db, tenant_id, only_opted_in=False)
    out = [_destinataire(group) for group in _group_by_person(list(members))]
    return DestinatairesRapport(
        email_to=to,
        email_cc=cc,
        membres=sorted(out, key=lambda d: (not d.bureau, rang_fonction(d.fonction), d.nom)),
    )


def _texte_email(
    *, titre: str, periode: str, resume: list[str], message: str, auteur: str, organisation: str
) -> str:
    lignes = ["Madame, Monsieur les membres du Bureau,", ""]
    if message:
        lignes += [message, ""]
    lignes.append(f"Veuillez trouver ci-joint le rapport « {titre} »" + (f", {periode}." if periode else "."))
    if resume:
        lignes += ["", "Chiffres clés :"] + [f"  - {r}" for r in resume]
    lignes += ["", f"Transmis par : {auteur}" if auteur else "", "", organisation]
    return "\n".join(lignes).strip()


def _nom_fichier(nom: str | None, titre: str) -> str:
    """Le nom donné par le navigateur s'il est sain, sinon dérivé du titre."""
    base = (nom or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].removesuffix(".pdf") or titre
    sur = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base).strip().replace(" ", "_")
    return f"{sur[:120] or 'rapport'}.pdf"


@router.post("", response_model=ResultatEnvoi)
async def envoyer_rapport(
    request: Request,
    titre: str = Form(..., max_length=200),
    periode: str = Form("", max_length=200),
    resume: str = Form("[]", max_length=20_000, description="Liste JSON de lignes : « Entrées : 1 200,00 USD »."),
    message: str = Form("", max_length=MAX_MESSAGE),
    member_ids: str = Form("[]", max_length=20_000, description="Liste JSON des fiches choisies, pour WhatsApp."),
    canaux: str = Form('["email"]', max_length=100, description="Liste JSON : email, whatsapp."),
    fichier: UploadFile | None = File(default=None),
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ResultatEnvoi:
    try:
        ids_bruts = json.loads(member_ids)
        resume_brut = json.loads(resume or "[]")
        canaux_bruts = json.loads(canaux or "[]")
        if not isinstance(ids_bruts, list) or not isinstance(resume_brut, list) or not isinstance(canaux_bruts, list):
            raise TypeError
        if any(isinstance(i, bool) for i in ids_bruts):
            raise TypeError
        ids = {int(i) for i in ids_bruts if int(i) > 0}
        lignes = [strip_emoji(str(l)).strip() for l in resume_brut if str(l or "").strip()]
        voies = {str(c) for c in canaux_bruts} & {"email", "whatsapp"}
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Demande d'envoi illisible.")
    if len(ids) > MAX_RECIPIENTS or len(lignes) > MAX_SUMMARY_LINES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La demande d'envoi contient trop d'éléments.")
    if not voies:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choisissez l'e-mail, WhatsApp, ou les deux.")

    titre = strip_emoji(titre).strip() or "Rapport"
    periode = strip_emoji(periode).strip()
    message = strip_emoji(message).strip()

    pdf: bytes | None = None
    if fichier is not None:
        pdf = await fichier.read(MAX_PDF_SIZE + 1)
        if len(pdf) > MAX_PDF_SIZE:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Le PDF dépasse 10 Mo.")
        if not pdf.startswith(b"%PDF"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La pièce jointe n'est pas un PDF.")
    if "email" in voies and not pdf:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Le rapport PDF manque à l'envoi par e-mail.")

    if "whatsapp" in voies and not ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choisissez au moins un destinataire WhatsApp.")

    # Filtre tenant par la jointure sur Service : commission_members ne porte
    # pas d'organisation_id.
    members = [] if not ids else (
        await db.execute(
            select(CommissionMember)
            .join(Service, Service.id == CommissionMember.service_id)
            .where(CommissionMember.id.in_(ids), Service.organisation_id == tenant_id)
            .options(selectinload(CommissionMember.function), selectinload(CommissionMember.service))
        )
    ).scalars().all()
    if ids and not members:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Aucun des destinataires n'a été trouvé.")
    personnes = [_destinataire(g) for g in _group_by_person(list(members))]

    organisation = (
        await db.execute(select(Organisation.nom).where(Organisation.id == tenant_id).limit(1))
    ).scalar_one_or_none() or ""
    auteur = " ".join(x for x in (getattr(user, "prenom", ""), getattr(user, "nom", "")) if x).strip() or (user.email or "")

    resultat = ResultatEnvoi()

    email_to: list[str] = []
    email_cc: list[str] = []
    if "email" in voies:
        ns = await get_system_settings(db, tenant_id)
        email_to, email_cc = bureau_email_recipients(ns.email_president, ns.emails_bureau_cc)
        if not email_to:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Aucune adresse du Bureau : renseignez l'e-mail du Président dans Paramètres › Notifications.",
            )
        smtp_cfg = resolve_smtp_config(ns)
        if smtp_cfg is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="L'envoi d'e-mails n'est pas configuré (paramètres SMTP).",
            )
        texte = _texte_email(
            titre=titre, periode=periode, resume=lignes, message=message, auteur=auteur, organisation=organisation,
        )
        try:
            await send_in_thread(
                send_rapport_bureau_email,
                smtp_host=smtp_cfg.host,
                smtp_port=smtp_cfg.port,
                smtp_user=smtp_cfg.user,
                smtp_password=smtp_cfg.password,
                sender=smtp_cfg.sender,
                to_emails=email_to,
                cc_emails=email_cc,
                subject=f"Rapport transmis au Bureau : {titre}" + (f" ({periode})" if periode else ""),
                titre=titre,
                sous_titre=periode,
                texte=texte,
                brand_label=f"ONEC-{organisation}" if organisation else "ONEC",
                pdf=pdf,
                pdf_filename=_nom_fichier(fichier.filename if fichier else None, titre),
            )
            resultat.emails_envoyes = len(email_to) + len(email_cc)
        except Exception as exc:  # noqa: BLE001 — l'échec est rapporté, pas avalé
            logger.exception("rapport.email_failed")
            resultat.echecs.append(EchecEnvoi(nom="Bureau (e-mail)", canal="email", raison=str(exc) or exc.__class__.__name__))

    nonce = uuid.uuid4().hex
    if "whatsapp" in voies:
        settings_obj = await load_whatsapp_settings(db, tenant_id, organisation)
        joignables = [p for p in personnes if p.whatsapp]
        resultat.echecs += [
            EchecEnvoi(nom=p.nom, canal="whatsapp", raison="Pas de numéro WhatsApp, ou notifications non acceptées.")
            for p in personnes
            if not p.whatsapp
        ]
        if joignables and not settings_obj.enabled:
            resultat.echecs += [EchecEnvoi(nom=p.nom, canal="whatsapp", raison="Le canal WhatsApp est désactivé.") for p in joignables]
        elif joignables:
            recipients = []
            for p in joignables:
                contact = _contact_whatsapp([m for m in members if m.id in p.member_ids])
                # `joignables` est construit avec la même fonction. Cette garde
                # maintient néanmoins l'envoi sûr si les données changent entre
                # la construction de la réponse et celle des destinataires.
                if contact is None:
                    resultat.echecs.append(
                        EchecEnvoi(
                            nom=p.nom,
                            canal="whatsapp",
                            raison="Pas de numéro WhatsApp avec consentement actif.",
                        )
                    )
                    continue
                _, telephone = contact
                recipients.append(Recipient(phone=telephone, name=p.nom, role=p.fonction))
            # Attendu dans la requête, comme le test : l'écran dit tout de suite
            # ce qui est parti.
            await notify_whatsapp(
                db,
                None,
                organisation_id=tenant_id,
                event_type=REPORT_SENT,
                entity_type=ENTITY_TYPE,
                entity_id=nonce,
                recipients=recipients,
                variables={
                    "reference": titre,
                    "periode": periode,
                    "resume": "\n".join(f"▸ {l}" for l in lignes),
                    "message": message,
                    "auteur": auteur,
                    "piece_jointe": "Le rapport complet en PDF a été envoyé par e-mail au Bureau."
                    if resultat.emails_envoyes
                    else "",
                },
                settings=settings_obj,
                nonce=nonce,
            )
            logs = (
                await db.execute(
                    select(NotificationLog)
                    .where(
                        NotificationLog.organisation_id == tenant_id,
                        NotificationLog.entity_type == ENTITY_TYPE,
                        NotificationLog.entity_id == nonce,
                    )
                    .execution_options(populate_existing=True)
                )
            ).scalars().all()
            resultat.whatsapp_envoyes = sum(1 for l in logs if l.status == STATUS_SENT)
            resultat.echecs += [
                EchecEnvoi(nom=l.recipient_name or l.recipient, canal="whatsapp", raison=l.error_message or "Envoi non abouti.")
                for l in logs
                if l.status != STATUS_SENT
            ]

    await log_action(
        db,
        user_id=user.id,
        action="RAPPORT_TRANSMIS",
        target_table="rapports",
        target_id=nonce,
        new_value={
            "titre": titre,
            "periode": periode,
            "email_to": email_to,
            "email_cc": email_cc,
            "whatsapp": [p.nom for p in personnes],
            "canaux": sorted(voies),
            "emails_envoyes": resultat.emails_envoyes,
            "whatsapp_envoyes": resultat.whatsapp_envoyes,
        },
        ip_address=get_request_ip(request),
    )
    await db.commit()
    return resultat
