from __future__ import annotations

import logging

import anyio
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.encaissement import Encaissement
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.services.email_config import resolve_smtp_config
from app.services.mailer import send_requisition_workflow_email
from app.services.system_settings_service import get_system_settings

logger = logging.getLogger("onec_cpk_api.client_receipt_email")


def _fmt_usd(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", " ") + " $"


async def schedule_client_payment_email(
    db: AsyncSession,
    background_tasks: BackgroundTasks,
    encaissement: Encaissement,
    tenant_id: int,
    *,
    relance: bool = False,
    send_now: bool = False,
) -> str | None:
    """Envoie au client (expert-comptable ou client externe) la confirmation
    de son paiement, avec le reste à payer s'il y en a un.

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

        if encaissement.type_client == "expert_comptable" and encaissement.expert_comptable_id:
            res = await db.execute(
                select(ExpertComptable).where(ExpertComptable.id == encaissement.expert_comptable_id)
            )
            expert = res.scalar_one_or_none()
            if expert is not None:
                email = (expert.email or "").strip() or None
                client_name = expert.nom_denomination or client_name
        elif getattr(encaissement, "client_id", None):
            res = await db.execute(select(Client).where(Client.id == encaissement.client_id))
            client = res.scalar_one_or_none()
            if client is not None:
                email = (client.email or "").strip() or None
                client_name = client.nom or client_name

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

        if relance:
            title = "Rappel de solde restant"
            subject = f"Rappel - Note de débit {numero} : solde restant de {_fmt_usd(reste)}"
            body_lines = [
                f"Bonjour {client_name or 'cher client'},",
                f"Sauf erreur de notre part, un solde reste dû sur votre dossier — {encaissement.libelle or ''}.",
                f"Note de débit N° : {numero}",
                f"Montant total : {_fmt_usd(total)}",
                f"Montant déjà payé : {_fmt_usd(paye)}",
                f"Reste à payer : {_fmt_usd(reste)}",
                "Nous vous invitons à passer à la caisse pour régulariser ce solde.",
                "Si vous avez déjà effectué ce paiement, merci de ne pas tenir compte de ce rappel.",
            ]
        else:
            body_lines = [
                f"Bonjour {client_name or 'cher client'},",
                f"Nous confirmons la réception de votre paiement — {encaissement.libelle or ''}.",
                f"Note de débit N° : {numero}",
                f"Montant total : {_fmt_usd(total)}",
                f"Montant payé à ce jour : {_fmt_usd(paye)}",
            ]
            if reste > 0.009:
                title = "Paiement reçu — solde restant"
                subject = f"Note de débit {numero} : paiement reçu, reste à payer {_fmt_usd(reste)}"
                body_lines.append(f"Reste à payer : {_fmt_usd(reste)}")
                body_lines.append(
                    "Nous vous invitons à régulariser le solde à votre meilleure convenance."
                )
            else:
                title = "Paiement reçu — soldé"
                subject = f"Note de débit {numero} : paiement complet, merci"
                body_lines.append("Votre paiement est complet : aucun solde restant.")
        body_lines.append("Merci de votre confiance.")

        email_kwargs = dict(
            smtp_host=smtp_cfg.host,
            smtp_port=smtp_cfg.port,
            smtp_user=smtp_cfg.user,
            smtp_password=smtp_cfg.password,
            sender=smtp_cfg.sender,
            recipient=email,
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
