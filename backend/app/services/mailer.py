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


def _format_brand_label(brand_name: str | None, organisation_name: str | None) -> str:
    base = (brand_name or "ONEC").strip()
    org = (organisation_name or "").strip()
    return f"{base} - {org}" if org else base


def _generer_corps_mail(
    *,
    requisition_num: str,
    objet: str,
    montant_total: float,
    created_by: str,
    examinateur: str | None = None,
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
) -> str:
    brand_label = _format_brand_label(brand_name, organisation_name)
    montant_fmt = f"{montant_total:,.2f}"
    lines = [
        "Chers Membres du Bureau,",
        "",
        "Nous avons l'honneur de vous informer qu'une nouvelle réquisition a été créée et enregistrée "
        "dans l'application de gestion de la trésorerie.",
        "",
        "Les informations y afférentes se présentent comme suit :",
        f"- Numéro : {requisition_num}",
        f"- Objet : {objet}",
        f"- Montant : {montant_fmt} $",
        f"- Créée par : {created_by}",
    ]
    if examinateur:
        lines.append(f"- Examinée par : {examinateur}")
    lines.extend(
        [
            "",
            "Nous vous saurions gré de bien vouloir vous connecter à l'application afin de procéder à son examen "
            "et, le cas échéant, à sa validation.",
            "",
            "Nous vous prions d'agréer, Mesdames et Messieurs les Membres du Bureau, l'expression de notre haute "
            "considération.",
            "",
            "Cordialement,",
            "Système de gestion de la trésorerie",
            f"{brand_label}",
        ]
    )
    return "\n".join(lines)


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
    examinateur: str | None = None,
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
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
            examinateur=examinateur,
            brand_name=brand_name,
            organisation_name=organisation_name,
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


def send_dossier_notification(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    president_email: str,
    cc_emails: str | None,
    dossier_reference: str,
    requisition_nums: list[str],
    montant_total: float,
    created_by: str,
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
    attachment_paths: list[str] | None = None,
) -> None:
    cc_list = _split_emails(cc_emails)
    brand_label = _format_brand_label(brand_name, organisation_name)

    msg = EmailMessage()
    msg["Subject"] = f"Groupe de réquisitions {dossier_reference}"
    msg["From"] = sender
    msg["To"] = president_email
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    lines = [
        f"Un groupe de réquisitions a été créé : {dossier_reference}",
        "",
        f"Nombre de réquisitions : {len(requisition_nums)}",
        f"Total : {montant_total:,.2f} $",
        f"Créé par : {created_by}",
        "",
        "Réquisitions :",
    ]
    lines.extend([f"- {num}" for num in requisition_nums])
    lines.extend(["", "Cordialement,", "Système de gestion de la trésorerie", brand_label])
    msg.set_content("\n".join(lines))

    _attach_paths(msg, attachment_paths or [], context_label=f"dossier {dossier_reference}")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Notification email sent for dossier %s", dossier_reference)
    except Exception:
        logger.exception("Failed to send notification email for dossier %s", dossier_reference)


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
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
    official_pdf_path: str | None = None,
    attachment_paths: list[str] | None = None,
) -> None:
    cc_list = _split_emails(cc_emails)
    brand_label = _format_brand_label(brand_name, organisation_name)

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
        f"{brand_label}"
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
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
) -> None:
    brand_label = _format_brand_label(brand_name, organisation_name)
    msg = EmailMessage()
    msg["Subject"] = f"🔐 Votre code de vérification {brand_label}"
    msg["From"] = sender
    msg["To"] = recipient

    msg.set_content(
        f"Bonjour {recipient_name},\n\n"
        "Pour sécuriser votre accès au système de trésorerie, veuillez utiliser le code de vérification suivant :\n\n"
        f"{code}\n\n"
        "Ce code est valable pendant 2 minutes. Si vous n'êtes pas à l'origine de cette demande, "
        "veuillez ignorer ce message.\n\n"
        f"L'équipe technique {brand_label}"
    )

    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden;">
          <div style="background-color: #1a365d; color: white; padding: 20px; text-align: center;">
            <h2 style="margin: 0;">Sécurité {brand_label}</h2>
          </div>
          <div style="padding: 20px;">
            <p>Bonjour {recipient_name},</p>
            <p>Vous avez initié une modification de sécurité sur votre compte. Pour confirmer votre identité et valider votre nouveau mot de passe, veuillez utiliser le code de vérification suivant :</p>
            <div style="text-align: center; margin: 30px 0;">
              <span style="display: inline-block; background-color: #f7fafc; border: 2px dashed #cbd5e0; padding: 15px 30px; font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #2d3748;">
                {code}
              </span>
            </div>
            <p style="font-size: 14px; color: #718096;">Ce code expirera dans 2 minutes. Si vous n'êtes pas à l'origine de cette demande, veuillez contacter l'administrateur immédiatement.</p>
          </div>
          <div style="background-color: #f7fafc; padding: 15px; text-align: center; font-size: 12px; color: #a0aec0;">
            &copy; 2026 {brand_label} - Système de Gestion de la Trésorerie
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


def send_requisition_workflow_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipient: str,
    subject: str,
    title: str,
    body_lines: list[str],
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
) -> None:
    brand_label = _format_brand_label(brand_name, organisation_name)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    plain_body = "\n".join(body_lines)
    msg.set_content(plain_body)

    html_body = "\n".join(
        f"<p style=\"margin:0 0 12px;\">{line}</p>" for line in body_lines if line.strip()
    )
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #333; line-height: 1.6;">
        <div style="max-width: 600px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 8px; overflow: hidden;">
          <div style="background-color: #0f172a; color: white; padding: 20px; text-align: center;">
            <h2 style="margin: 0;">{title}</h2>
          </div>
          <div style="padding: 20px;">
            {html_body}
          </div>
          <div style="background-color: #f8fafc; padding: 14px; text-align: center; font-size: 12px; color: #94a3b8;">
            &copy; 2026 {brand_label} - Système de Gestion de la Trésorerie
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
        logger.info("Workflow email sent to %s", recipient)
    except Exception:
        logger.exception("Failed to send workflow email to %s", recipient)


def send_tenant_welcome(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipient: str,
    organisation_name: str,
    temp_password: str,
    login_url: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = f"Bienvenue sur IntelliOffice - Votre espace {organisation_name} est prêt !"
    msg["From"] = sender
    msg["To"] = recipient

    msg.set_content(
        f"Bonjour,\n\n"
        f"Félicitations ! Votre espace de gestion budgétaire pour le Conseil Provincial de {organisation_name} "
        "a été créé avec succès.\n\n"
        "Vos accès :\n"
        f"URL : {login_url}\n"
        f"Identifiant : {recipient}\n"
        f"Mot de passe temporaire : {temp_password}\n\n"
        "Note : Pour des raisons de sécurité, il vous sera demandé de modifier ce mot de passe lors de votre première connexion.\n\n"
        "Cordialement,\n"
        "Équipe IntelliOffice"
    )

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Tenant welcome email sent to %s", recipient)
    except Exception:
        logger.exception("Failed to send tenant welcome email to %s", recipient)


def send_weekly_report_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipient: str,
    cc_emails: str | None,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> None:
    cc_list = _split_emails(cc_emails)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    msg.set_content(text_body or "Rapport hebdomadaire trésorerie.")
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Weekly report email sent to %s", recipient)
        return True
    except Exception:
        logger.exception("Failed to send weekly report email to %s", recipient)


def send_monitoring_alert_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipient: str,
    cc_emails: str | None,
    subject: str,
    lines: list[str],
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    if cc_emails:
        msg["Cc"] = cc_emails

    msg.set_content("\n".join(lines))

    html_body = "\n".join(f'<p style="margin:0 0 10px;">{line}</p>' for line in lines if line.strip())
    msg.add_alternative(
        f"""
        <html>
          <body style="font-family: Arial, sans-serif; color: #111827; line-height: 1.5;">
            <div style="max-width: 640px; margin: 0 auto; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden;">
              <div style="background: #0b5d43; color: #fff; padding: 16px;">
                <strong>{subject}</strong>
              </div>
              <div style="padding: 16px;">
                {html_body}
              </div>
            </div>
          </body>
        </html>
        """,
        subtype="html",
    )

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Monitoring alert sent to %s", recipient)
    except Exception:
        logger.exception("Failed to send monitoring alert to %s", recipient)


def send_monthly_report_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipient: str,
    cc_emails: str | None,
    subject: str,
    body_lines: list[str],
    attachment_path: str | None,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    if cc_emails:
        msg["Cc"] = cc_emails

    msg.set_content("\n".join(body_lines))

    if attachment_path:
        _attach_paths(msg, [attachment_path], context_label="monthly report")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Monthly report email sent to %s", recipient)
    except Exception:
        logger.exception("Failed to send monthly report email to %s", recipient)


def send_saas_invoice_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipients: list[str],
    invoice_number: str,
    organisation_name: str,
    amount: float,
    currency: str,
    period_end: str | None,
    attachment_path: str | None,
) -> bool:
    if not recipients:
        return False

    msg = EmailMessage()
    msg["Subject"] = f"Facture SaaS {invoice_number}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    amount_fmt = f"{amount:,.2f} {currency}"
    lines = [
        f"Bonjour,",
        "",
        f"Votre paiement d'abonnement SaaS pour {organisation_name} a bien été reçu.",
        f"Facture : {invoice_number}",
        f"Montant payé : {amount_fmt}",
    ]
    if period_end:
        lines.append(f"Abonnement valide jusqu'au : {period_end}")
    lines.extend(["", "La facture est jointe à ce message.", "", "Cordialement,", "Plateforme SaaS ONE CPK"])
    msg.set_content("\n".join(lines))
    if attachment_path:
        _attach_paths(msg, [attachment_path], context_label=f"SaaS invoice {invoice_number}")

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("SaaS invoice %s sent to %s", invoice_number, ", ".join(recipients))
        return True
    except Exception:
        logger.exception("Failed to send SaaS invoice %s", invoice_number)
        return False


def send_subscription_renewal_alert_email(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    sender: str,
    recipients: list[str],
    organisation_name: str,
    plan_name: str | None,
    expires_at: str,
    days_left: int,
) -> bool:
    if not recipients:
        return False

    msg = EmailMessage()
    msg["Subject"] = f"Alerte abonnement SaaS - expiration dans {days_left} jours"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    lines = [
        "Bonjour,",
        "",
        f"L'abonnement SaaS de {organisation_name} arrive à expiration dans {days_left} jours.",
        f"Date d'expiration : {expires_at}",
    ]
    if plan_name:
        lines.append(f"Plan : {plan_name}")
    lines.extend(
        [
            "",
            "Si le renouvellement n'est pas payé avant cette date, certaines fonctionnalités peuvent être limitées ou suspendues selon les règles définies.",
            "",
            "Cordialement,",
            "Plateforme SaaS ONE CPK",
        ]
    )
    msg.set_content("\n".join(lines))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Subscription renewal alert sent to %s", ", ".join(recipients))
        return True
    except Exception:
        logger.exception("Failed to send subscription renewal alert")
        return False
