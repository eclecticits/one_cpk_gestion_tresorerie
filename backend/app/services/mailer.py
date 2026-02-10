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

    for path in attachment_paths or []:
        if not path or not os.path.exists(path):
            logger.warning("Attachment path missing for requisition %s: %s", requisition_num, path)
            continue
        try:
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
                filename=os.path.basename(path),
            )
        except Exception:
            logger.exception("Failed to attach file for requisition %s: %s", requisition_num, path)

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        logger.info("Notification email sent for requisition %s", requisition_num)
    except Exception:
        logger.exception("Failed to send notification email for requisition %s", requisition_num)
