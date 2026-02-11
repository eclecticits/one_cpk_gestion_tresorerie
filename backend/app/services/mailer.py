from __future__ import annotations

import logging
import mimetypes
import os
import re
import smtplib
from email.message import EmailMessage


logger = logging.getLogger("onec_cpk_api.mailer")


def _split_emails(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,\n;]+", value)
    return [p.strip() for p in parts if p.strip()]


def _generer_corps_mail(
    *,
    requisition_num: str,
    objet: str,
    montant_total: float,
    created_by: str,
) -> str:
    montant_fmt = f"{montant_total:,.2f}"
    return (
        "Chers Membres du Bureau,\n"
        "\n"
        "Nous avons l'honneur de vous informer qu'une nouvelle réquisition a été créée et enregistrée "
        "dans l'application de gestion de la trésorerie.\n"
        "\n"
        "Les informations y afférentes se présentent comme suit :\n"
        f"- Numéro : {requisition_num}\n"
        f"- Objet : {objet}\n"
        f"- Montant : {montant_fmt} $\n"
        f"- Créée par : {created_by}\n"
        "\n"
        "Nous vous saurions gré de bien vouloir vous connecter à l'application afin de procéder à son examen "
        "et, le cas échéant, à sa validation.\n"
        "\n"
        "Nous vous prions d'agréer, Mesdames et Messieurs les Membres du Bureau, l'expression de notre haute "
        "considération.\n"
        "\n"
        "Cordialement,\n"
        "Système de gestion de la trésorerie\n"
        "ONEC-CPK"
    )


def _attach_file(msg: EmailMessage, path: str, filename: str | None = None) -> None:
    with open(path, "rb") as handle:
        file_data = handle.read()
    ctype, _ = mimetypes.guess_type(path)
    if not ctype:
        ctype = "application/octet-stream"
    maintype, subtype = ctype.split("/", 1)
    msg.add_attachment(
        file_data,
        maintype=maintype,
        subtype=subtype,
        filename=filename or os.path.basename(path),
    )


def _attach_paths(msg: EmailMessage, paths: list[str], *, context_label: str) -> None:
    for path in paths:
        if not path or not os.path.exists(path):
            logger.warning("Attachment path missing for %s: %s", context_label, path)
            continue
        try:
            _attach_file(msg, path)
        except Exception:
            logger.exception("Failed to attach file for %s: %s", context_label, path)


def send_requisition_notification(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    president_email: str,
    cc_emails: str | None,
    requisition_num: str,
    montant_total: float,
    objet: str,
    created_by: str,
    official_pdf_path: str | None = None,
    attachment_paths: list[str] | None = None,
) -> None:
    cc_list = _split_emails(cc_emails)

    msg = EmailMessage()
    msg["Subject"] = f"Nouvelle requisition {requisition_num}"
    msg["From"] = sender
    msg["To"] = president_email
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    msg.set_content(
        _generer_corps_mail(
            requisition_num=requisition_num,
            objet=objet,
            montant_total=montant_total,
            created_by=created_by,
        )
    )

    if official_pdf_path:
        if os.path.exists(official_pdf_path):
            try:
                with open(official_pdf_path, "rb") as handle:
                    pdf_data = handle.read()
                msg.add_attachment(
                    pdf_data,
                    maintype="application",
                    subtype="pdf",
                    filename=f"Bon_Officiel_{requisition_num}.pdf",
                )
            except Exception:
                logger.exception("Failed to attach official PDF for %s", requisition_num)
        else:
            logger.warning("Official PDF not found for requisition %s: %s", requisition_num, official_pdf_path)

    _attach_paths(msg, attachment_paths or [], context_label=f"requisition {requisition_num}")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Notification email sent for requisition %s", requisition_num)
    except Exception:
        logger.exception("Failed to send notification email for requisition %s", requisition_num)


def send_sortie_notification(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    tresorier_email: str,
    cc_emails: str | None,
    num_transaction: str,
    num_bon_requisition: str | None,
    montant: float,
    beneficiaire: str,
    caissier_nom: str,
    official_pdf_path: str | None = None,
    attachment_paths: list[str] | None = None,
) -> None:
    cc_list = _split_emails(cc_emails)

    msg = EmailMessage()
    msg["Subject"] = f"💸 Confirmation de Sortie de Fonds - {num_transaction}"
    msg["From"] = sender
    msg["To"] = tresorier_email
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    montant_fmt = f"{montant:,.2f}"
    msg.set_content(
        "Chers Membres du Bureau,\n"
        "\n"
        "Nous vous informons qu'une sortie de fonds a été effectuée avec succès.\n"
        "\n"
        "Détails de l'opération :\n"
        f"- Référence : {num_transaction}\n"
        f"- Réquisition associée : {num_bon_requisition or '-'}\n"
        f"- Montant décaissé : {montant_fmt} $\n"
        f"- Bénéficiaire : {beneficiaire}\n"
        f"- Caissier / Trésorier : {caissier_nom}\n"
        "\n"
        "Le Bon de Sortie officiel ainsi que les preuves de décharge sont joints à ce message.\n"
        "\n"
        "Cordialement,\n"
        "Système de gestion de la trésorerie\n"
        "ONEC-CPK"
    )

    if official_pdf_path:
        if os.path.exists(official_pdf_path):
            try:
                _attach_file(
                    msg,
                    official_pdf_path,
                    filename=f"Bon_Sortie_{num_transaction}.pdf",
                )
            except Exception:
                logger.exception("Failed to attach official sortie PDF for %s", num_transaction)
        else:
            logger.warning("Official sortie PDF not found for %s: %s", num_transaction, official_pdf_path)

    _attach_paths(msg, attachment_paths or [], context_label=f"sortie {num_transaction}")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Notification email sent for sortie %s", num_transaction)
    except Exception:
        logger.exception("Failed to send notification email for sortie %s", num_transaction)


def send_security_code(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipient: str,
    recipient_name: str,
    code: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = "🔐 Votre code de vérification ONEC-CPK"
    msg["From"] = sender
    msg["To"] = recipient

    msg.set_content(
        f"Bonjour {recipient_name},\n\n"
        "Pour sécuriser votre accès au système de trésorerie, veuillez utiliser le code de vérification suivant :\n\n"
        f"{code}\n\n"
        "Ce code est valable pendant 10 minutes. Si vous n'êtes pas à l'origine de cette demande, "
        "veuillez ignorer ce message.\n\n"
        "L'équipe technique ONEC-CPK"
    )

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">
          <div style="background-color: #1a365d; color: white; padding: 20px; text-align: center;">
            <h2 style="margin: 0;">Sécurité ONEC-CPK</h2>
          </div>
          <div style="padding: 20px;">
            <p>Bonjour {recipient_name},</p>
            <p>Vous avez initié une modification de sécurité sur votre compte. Pour confirmer votre identité et valider votre nouveau mot de passe, veuillez utiliser le code de vérification suivant :</p>
            <div style="text-align: center; margin: 30px 0;">
              <span style="display: inline-block; background-color: #f7fafc; border: 2px dashed #cbd5e0; padding: 15px 30px; font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #2d3748;">
                {code}
              </span>
            </div>
            <p style="font-size: 14px; color: #718096;">Ce code expirera dans 10 minutes. Si vous n'êtes pas à l'origine de cette demande, veuillez contacter l'administrateur immédiatement.</p>
          </div>
          <div style="background-color: #f7fafc; padding: 15px; text-align: center; font-size: 12px; color: #a0aec0;">
            &copy; 2026 ONEC-CPK - Système de Gestion de la Trésorerie
          </div>
        </div>
      </body>
    </html>
    """
    msg.add_alternative(html_content, subtype="html")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Security code email sent to %s", recipient)
    except Exception:
        logger.exception("Failed to send security code email to %s", recipient)
