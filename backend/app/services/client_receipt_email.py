from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal

import anyio
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.schemas.client import TYPES_CLIENT_EXPERT
from app.services.email_config import resolve_smtp_config
from app.services.mailer import send_requisition_workflow_email
from app.services.system_settings_service import get_system_settings

logger = logging.getLogger("onec_cpk_api.client_receipt_email")


MODE_PAIEMENT_LABELS = {
    "cash": "Espèces",
    "mobile_money": "Mobile money",
    "virement": "Virement bancaire",
    "card": "Carte bancaire",
    "cheque": "Chèque",
}


def _fmt_usd(amount: float) -> str:
    # Usage français : espace pour les milliers, virgule décimale (1 250,00 $).
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " $"


def salutation_lignes(
    type_client: str | None,
    nom: str | None,
    *,
    sexe: str | None = None,
    associe_gerant: str | None = None,
) -> list[str]:
    """Formule d'appel d'un message au client, selon ce qu'il est.

    - SEC : « Madame, Monsieur, » puis l'associé gérant, qui la représente ;
    - personne morale : « Madame, Monsieur, » à l'attention de la société ;
    - personne (expert-comptable, personne physique…) : « Monsieur » si le
      sexe est M, « Madame » s'il est F, le nom seul s'il n'est pas renseigné.

    Partagée par l'email et WhatsApp : les deux canaux saluent de même.
    """
    nom = (nom or "").strip()
    if type_client == "sec":
        gerant = (associe_gerant or "").strip()
        if gerant and nom:
            return ["Madame, Monsieur,", f"À l'attention de {gerant}, associé gérant de {nom}."]
        return ["Madame, Monsieur,"] + ([f"À l'attention de {nom}."] if nom else [])
    if type_client == "personne_morale":
        return ["Madame, Monsieur,"] + ([f"À l'attention de {nom}."] if nom else [])
    if not nom:
        return ["Madame, Monsieur,"]
    civilite = {"M": "Monsieur ", "F": "Madame "}.get((sexe or "").strip().upper(), "")
    return [f"Bonjour {civilite}{nom},"]


def _copie_paiement(ns: object, destinataire: str) -> str | None:
    """Adresses en copie visible (CC) des emails de paiement, configurées dans
    Paramètres > Notifications > Email ; sans le payeur ni doublon.

    Copie visible : avec « Répondre à tous », la réponse du payeur leur parvient.
    """
    candidats = re.split(r"[,\n;]+", getattr(ns, "emails_paiement_cc", "") or "")
    vus = {destinataire.lower()}
    adresses: list[str] = []
    for adresse in (a.strip() for a in candidats):
        if adresse and adresse.lower() not in vus:
            vus.add(adresse.lower())
            adresses.append(adresse)
    return ", ".join(adresses) or None


def signature_ligne(organisation_name: str | None) -> str:
    return f"La Trésorerie – {organisation_name}" if organisation_name else "La Trésorerie"


async def schedule_client_payment_email(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    encaissement: Encaissement,
    tenant_id: int,
    *,
    relance: bool = False,
    send_now: bool = False,
    montant_recu: Decimal | float | None = None,
    mode_paiement_recu: str | None = None,
    date_recu: datetime | None = None,
) -> str | None:
    """Envoie au client (expert-comptable ou client externe) la confirmation
    de son paiement, avec le reste à payer s'il y en a un.

    `montant_recu`, `mode_paiement_recu`, `date_recu` décrivent le versement
    qui déclenche l'envoi : sans eux, un complément n'annoncerait que le cumul
    payé, et le client ne saurait pas ce qui vient d'être reçu.

    Avec relance=True, envoie un rappel de solde restant (recouvrement).
    Avec send_now=True, l'email est envoyé de façon synchrone : le résultat
    d'envoi est vérifié et l'adresse n'est retournée que si l'envoi a
    réellement réussi (M1 : la relance ne doit pas être comptée si l'email
    échoue). Sinon, l'envoi est programmé en tâche de fond (best effort).

    Retourne l'adresse email utilisée, ou None si aucun envoi n'a pu être
    programmé/réalisé. L'opération de caisse n'est jamais bloquée par l'email.
    """
    try:
        email: str | None = None
        client_name = (encaissement.client_nom or "").strip()
        sexe: str | None = None
        associe_gerant: str | None = None

        if encaissement.type_client in TYPES_CLIENT_EXPERT and encaissement.expert_comptable_id:
            res = await db.execute(
                select(ExpertComptable).where(ExpertComptable.id == encaissement.expert_comptable_id)
            )
            expert = res.scalar_one_or_none()
            if expert is not None:
                email = (expert.email or "").strip() or None
                client_name = expert.nom_denomination or client_name
                sexe = expert.sexe
                associe_gerant = expert.associe_gerant
        elif getattr(encaissement, "client_id", None):
            res = await db.execute(select(Client).where(Client.id == encaissement.client_id))
            client = res.scalar_one_or_none()
            if client is not None:
                email = (client.email or "").strip() or None
                client_name = client.nom or client_name
                sexe = client.sexe

        if not email:
            logger.info(
                "Pas d'email client pour l'encaissement %s : note de débit non envoyée",
                encaissement.id,
            )
            return None

        ns = await get_system_settings(db, tenant_id)
        smtp_cfg = resolve_smtp_config(ns)
        if smtp_cfg is None:
            logger.info("SMTP non configuré : note de débit client non envoyée (encaissement %s)", encaissement.id)
            return None

        org_res = await db.execute(
            select(Organisation.nom).where(Organisation.id == tenant_id).limit(1)
        )
        org_name = org_res.scalar_one_or_none()

        total = float(encaissement.montant_total or 0)
        paye = float(encaissement.montant_paye or 0)
        reste = round(total - paye, 2)
        numero = encaissement.numero_recu or encaissement.numero_proforma or "—"
        objet = (encaissement.libelle or "").strip()
        salutation = salutation_lignes(
            encaissement.type_client, client_name, sexe=sexe, associe_gerant=associe_gerant
        )
        signature = ["Merci de votre confiance.", signature_ligne(org_name)]

        if relance:
            title = "Rappel de solde restant"
            subject = f"Rappel - Note de débit {numero} : solde restant de {_fmt_usd(reste)}"
            body_lines = [
                *salutation,
                "",
                "Sauf erreur de notre part, un solde reste dû sur votre note de débit.",
                "",
                *([f"Objet : {objet}"] if objet else []),
                f"Note de débit N° : {numero}",
                f"Montant total : {_fmt_usd(total)}",
                f"Montant déjà payé : {_fmt_usd(paye)}",
                f"Reste à payer : {_fmt_usd(reste)}",
                "",
                "Nous vous invitons à passer à la caisse pour régulariser ce solde.",
                "Si vous avez déjà effectué ce paiement, merci de ne pas tenir compte de ce rappel.",
                "",
                *signature,
            ]
        else:
            date_paiement = date_recu or encaissement.date_paiement or encaissement.date_encaissement
            recu_ligne: list[str] = []
            if montant_recu is not None:
                mode = MODE_PAIEMENT_LABELS.get((mode_paiement_recu or "").strip().lower(), "")
                recu_ligne = [
                    f"Montant reçu : {_fmt_usd(float(montant_recu))}" + (f" ({mode.lower()})" if mode else "")
                ]
            body_lines = [
                *salutation,
                "",
                "Nous accusons réception de votre paiement"
                + (f" du {date_paiement.strftime('%d/%m/%Y')}." if date_paiement else "."),
                "",
                *([f"Objet : {objet}"] if objet else []),
                f"Note de débit N° : {numero}",
                *recu_ligne,
                f"Montant total de la note : {_fmt_usd(total)}",
                f"Total payé à ce jour : {_fmt_usd(paye)}",
            ]
            if reste > 0.009:
                title = "Paiement reçu — solde restant"
                subject = f"Paiement reçu – Note de débit {numero} – reste {_fmt_usd(reste)}"
                body_lines += [
                    f"Reste à payer : {_fmt_usd(reste)}",
                    "",
                    "Nous vous invitons à régler le solde à votre meilleure convenance.",
                ]
            else:
                title = "Paiement reçu — soldé"
                subject = f"Paiement reçu – Note de débit {numero} – soldée"
                body_lines += ["", "Votre note de débit est entièrement réglée."]
            body_lines += ["", *signature]

        email_kwargs = dict(
            smtp_host=smtp_cfg.host,
            smtp_port=smtp_cfg.port,
            smtp_user=smtp_cfg.user,
            smtp_password=smtp_cfg.password,
            sender=smtp_cfg.sender,
            recipient=email,
            cc_emails=_copie_paiement(ns, email),
            subject=subject,
            title=title,
            body_lines=body_lines,
            brand_name="ONEC",
            organisation_name=org_name,
        )

        if send_now:
            # Envoi synchrone : on retourne l'email seulement si l'envoi a réussi.
            sent = await anyio.to_thread.run_sync(
                lambda: send_requisition_workflow_email(**email_kwargs)
            )
            if not sent:
                logger.warning(
                    "Envoi synchrone échoué pour %s (encaissement %s)", email, encaissement.id
                )
                return None
            logger.info("Email client envoyé (sync) à %s (encaissement %s)", email, encaissement.id)
            return email

        background_tasks.add_task(send_requisition_workflow_email, **email_kwargs)
        logger.info("Note de débit client programmée pour %s (encaissement %s)", email, encaissement.id)
        return email
    except Exception:
        # L'email ne doit jamais faire échouer l'opération de caisse.
        logger.exception("Échec de préparation de la note de débit client (encaissement %s)", encaissement.id)
        return None
