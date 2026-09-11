from __future__ import annotations

import functools
import logging
import html
import hashlib
import mimetypes
import os
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Callable, TypeVar

import anyio

from app.core.config import settings


logger = logging.getLogger("onec_cpk_api.mailer")

T = TypeVar("T")


async def send_in_thread(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Exécute un envoi SMTP dans un thread.

    Toutes les fonctions `send_*` de ce module sont synchrones et bloquent sur
    le réseau, jusqu'à 20 s en cas de serveur SMTP lent (voir le `timeout=20`
    des connexions). Appelées directement depuis une coroutine, elles figent la
    boucle d'événements pendant toute cette durée : plus aucune requête n'avance
    sur le worker, alors même que le serveur n'a rien à calculer.

    Depuis un contexte async, envoyer via ce wrapper — ou, si la réponse n'a pas
    besoin d'attendre l'envoi, via `BackgroundTasks.add_task`.
    """
    return await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))


def _split_emails(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,\n;]+", value)
    return [p.strip() for p in parts if p.strip()]


def normalize_email_list(value: str | None) -> list[str]:
    return _split_emails(value)


def _format_brand_label(brand_name: str | None, organisation_name: str | None) -> str:
    base = (brand_name or "ONEC").strip()
    org = (organisation_name or "").strip()
    return f"{base}-{org}" if org else base


def _tenant_portal_url(organisation_slug: str | None) -> str | None:
    slug = (organisation_slug or "").strip().lower()
    base_domain = (settings.tenant_base_domain or "").strip().lower().strip(".")
    if not slug or not base_domain:
        return None
    return f"https://{slug}.{base_domain}/login"


def _format_currency(amount: float, currency: str = "USD") -> str:
    amount_fmt = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{amount_fmt} {currency}"


def _format_date_fr(value: datetime | None) -> str | None:
    """« 10 septembre 2026 ». `strftime("%B")` dépend de la locale du conteneur,
    qui est C : il rendrait « September »."""
    if value is None:
        return None
    mois = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    return f"{value.day} {mois[value.month - 1]} {value.year}"


def _notification_labels(type_requisition: str | None) -> dict[str, str]:
    is_transport = (type_requisition or "").strip().lower() == "remboursement_transport"
    if is_transport:
        return {
            "subject_prefix": "Remboursement transport",
            "request_label": "demande de remboursement de transport",
            "number_label": "Numéro de remboursement",
            "official_doc_label": "le bon de remboursement signé",
            "cta_label": "Valider ou rejeter le remboursement",
        }
    return {
        "subject_prefix": "Réquisition",
        "request_label": "réquisition",
        "number_label": "Numéro de réquisition",
        "official_doc_label": "le bon de réquisition signé",
        "cta_label": "Valider ou rejeter la réquisition",
    }


def _resume_pieces_jointes(
    *,
    official_attached: bool,
    annexes_count: int,
    official_doc_label: str,
) -> tuple[str, str]:
    """Annonce des pièces jointes : (ce qui est joint, ce qui manque).

    Un mail sans trombone visible ne se cherche pas : le Bureau doit lire ce
    qu'il a sous la main, et surtout savoir quand il valide sans le bon signé —
    cas courant, le bon vient d'un téléversement manuel.
    """
    annexes_label = ""
    if annexes_count == 1:
        annexes_label = "1 annexe"
    elif annexes_count > 1:
        annexes_label = f"{annexes_count} annexes"

    note = (
        f"{official_doc_label[0].upper()}{official_doc_label[1:]} n'est pas joint : "
        "il n'a pas encore été téléversé dans ONEC Smart."
    )

    if official_attached and annexes_label:
        return f"{official_doc_label} et {annexes_label}", ""
    if official_attached:
        return official_doc_label, ""
    if annexes_label:
        return annexes_label, note
    return "aucune", note


def _generer_corps_mail(
    *,
    requisition_num: str,
    objet: str,
    montant_total: float,
    created_by: str,
    examinateur: str | None = None,
    examine_le: str | None = None,
    service_name: str | None = None,
    devise: str = "USD",
    pieces_valeur: str = "aucune",
    pieces_note: str = "",
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
    organisation_slug: str | None = None,
    type_requisition: str | None = None,
) -> str:
    brand_label = _format_brand_label(brand_name, organisation_name)
    montant_fmt = _format_currency(montant_total, devise)
    labels = _notification_labels(type_requisition)
    tenant_url = _tenant_portal_url(organisation_slug)

    examinateur_valeur = None
    if examinateur:
        examinateur_valeur = f"{examinateur}, le {examine_le}" if examine_le else examinateur

    details: list[tuple[str, str]] = [
        (labels["number_label"], requisition_num),
        ("Objet", objet),
        ("Montant", montant_fmt),
    ]
    if service_name:
        details.append(("Service demandeur", service_name))
    details.append(("Émise par", created_by))
    if examinateur_valeur:
        details.append(("Examinée par", examinateur_valeur))
    largeur = max(len(label) for label, _ in details)

    lines = [
        "Chers Membres du Bureau,",
        "",
        f"La {labels['request_label']} ci-dessous a été examinée par le service technique",
        "et est soumise à votre appréciation : il vous revient de la valider ou",
        "de la rejeter.",
        "",
    ]
    lines.extend(f"{label.ljust(largeur)} : {valeur}" for label, valeur in details)
    lines.extend(["", f"Pièces jointes : {pieces_valeur}."])
    if pieces_note:
        lines.append(pieces_note)
    if tenant_url:
        lines.extend(["", f"Pour valider ou rejeter : {tenant_url}"])
    lines.extend(
        [
            "",
            "Nous vous prions d'agréer, Chers Membres du Bureau, l'expression de notre",
            "considération distinguée.",
            "",
            f"Le Secrétariat — {brand_label}",
            "",
            "Message automatique émis par ONEC Smart. Merci de ne pas y répondre.",
        ]
    )
    return "\n".join(lines)


def _generer_corps_mail_html(
    *,
    requisition_num: str,
    objet: str,
    montant_total: float,
    created_by: str,
    examinateur: str | None = None,
    examine_le: str | None = None,
    service_name: str | None = None,
    devise: str = "USD",
    pieces_valeur: str = "aucune",
    pieces_note: str = "",
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
    organisation_slug: str | None = None,
    type_requisition: str | None = None,
) -> str:
    brand_label = html.escape(_format_brand_label(brand_name, organisation_name))
    labels = _notification_labels(type_requisition)
    tenant_url = _tenant_portal_url(organisation_slug)

    def _row(label: str, valeur: str) -> str:
        return (
            f'<tr><td style="padding:6px 0;"><strong>{html.escape(label)} :</strong> '
            f"{html.escape(valeur)}</td></tr>"
        )

    rows = [
        _row(labels["number_label"], requisition_num),
        _row("Objet", objet),
        _row("Montant", _format_currency(montant_total, devise)),
    ]
    if service_name:
        rows.append(_row("Service demandeur", service_name))
    rows.append(_row("Émise par", created_by))
    if examinateur:
        rows.append(
            _row("Examinée par", f"{examinateur}, le {examine_le}" if examine_le else examinateur)
        )
    pieces_note_block = (
        f'<div style="margin-top:4px; font-size:12px; color:#8a5a1f;">{html.escape(pieces_note)}</div>'
        if pieces_note
        else ""
    )
    rows.append(
        f'<tr><td style="padding:6px 0;"><strong>Pièces jointes :</strong> '
        f"{html.escape(pieces_valeur)}{pieces_note_block}</td></tr>"
    )
    details_rows = "".join(rows)

    tenant_link_block = (
        f"""
        <div style="margin:18px 0 4px; padding:14px 16px; border:1px solid #d9eee7; border-radius:12px; background:#f2fbf8;">
          <div style="font-size:13px; color:#58736c; font-weight:700; margin-bottom:8px;">Accès au dossier</div>
          <a href="{html.escape(tenant_url)}" style="display:inline-block; padding:10px 16px; border-radius:10px; background:#0f7b62; color:#ffffff; text-decoration:none; font-weight:700;">
            {html.escape(labels['cta_label'])}
          </a>
          <div style="margin-top:8px; font-size:12px; color:#6b7f79;">{html.escape(tenant_url)}</div>
        </div>
        """
        if tenant_url
        else ""
    )
    return f"""
    <html>
      <body style="margin:0; padding:24px; background:#f6faf9; font-family: Arial, sans-serif; color: #1f2937; line-height: 1.65;">
        <div style="max-width:640px; margin:0 auto; border:1px solid #dfe9e6; border-radius:16px; overflow:hidden; background:#ffffff;">
          <div style="padding:22px 24px; background:#0f7b62; color:#ffffff;">
            <div style="font-size:12px; text-transform:uppercase; letter-spacing:.08em; opacity:.86;">ONEC Smart</div>
            <h2 style="margin:6px 0 0; font-size:21px; line-height:1.25;">Décision du Bureau requise</h2>
          </div>
          <div style="padding:22px 24px;">
            <p style="margin:0 0 14px;">Chers Membres du Bureau,</p>
            <p style="margin:0 0 18px;">
              La {html.escape(labels['request_label'])} ci-dessous a été examinée par le service technique et est soumise à votre appréciation : il vous revient de la valider ou de la rejeter.
            </p>
            <div style="padding:14px 16px; border:1px solid #e2ebe8; border-radius:12px; background:#fbfefd;">
              <div style="font-weight:800; color:#155d4c; margin-bottom:8px;">Détails de la demande</div>
              <table style="border-collapse: collapse; width:100%;">
                {details_rows}
              </table>
            </div>
            {tenant_link_block}
            <p style="margin:18px 0 0;">
              Nous vous prions d'agréer, Chers Membres du Bureau, l'expression de notre considération distinguée.
            </p>
            <p style="margin:14px 0 0; font-weight:700;">Le Secrétariat — {brand_label}</p>
          </div>
          <div style="padding:14px 24px; background:#f8fafc; color:#7b8d88; font-size:12px; text-align:center;">
            {brand_label} · ONEC Smart<br />
            Message automatique émis par ONEC Smart. Merci de ne pas y répondre.
          </div>
        </div>
      </body>
    </html>
    """.strip()


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


def _log_attachment_metadata(path: str, *, context_label: str) -> None:
    try:
        with open(path, "rb") as handle:
            file_data = handle.read()
        digest = hashlib.md5(file_data).hexdigest()
        logger.info(
            "Attaching file for %s: path=%s size=%s md5=%s",
            context_label,
            path,
            len(file_data),
            digest,
        )
    except Exception:
        logger.exception("Failed to inspect attachment metadata for %s: %s", context_label, path)


def _count_message_attachments(msg: EmailMessage) -> int:
    return sum(1 for part in msg.iter_attachments())


def _send_email_message(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    msg: EmailMessage,
) -> None:
    port = int(smtp_port)
    require_tls = bool(getattr(settings, "smtp_require_tls", True))
    context = ssl.create_default_context()
    if port == 465:
        # TLS implicite (SMTPS) avec vérification du certificat.
        with smtplib.SMTP_SSL(smtp_host, port, timeout=20, context=context) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
        return
    with smtplib.SMTP(smtp_host, port, timeout=20) as smtp:
        smtp.ehlo()
        if smtp.has_extn("starttls"):
            # STARTTLS avec vérification du certificat (empêche le MITM).
            smtp.starttls(context=context)
            smtp.ehlo()
        elif require_tls:
            # Fail-closed : ne jamais envoyer identifiants + message en clair.
            raise RuntimeError(
                "Le serveur SMTP n'annonce pas STARTTLS ; envoi refusé "
                "(mettez SMTP_REQUIRE_TLS=false uniquement en dev/local)."
            )
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)


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
    examen_le: datetime | None = None,
    service_name: str | None = None,
    devise: str = "USD",
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
    organisation_slug: str | None = None,
    type_requisition: str | None = None,
    official_pdf_path: str | None = None,
    attachment_paths: list[str] | None = None,
) -> None:
    # Le président est aussi membre du Bureau dans la plupart des antennes : son
    # adresse figure alors dans les deux réglages, et il recevait le même mail
    # deux fois, son adresse affichée deux fois dans l'en-tête.
    cc_list = [
        email
        for email in _split_emails(cc_emails)
        if email.strip().lower() != (president_email or "").strip().lower()
    ]
    labels = _notification_labels(type_requisition)

    # Les pièces sont annoncées dans le corps : il faut donc savoir avant de
    # l'écrire lesquelles seront réellement attachées plus bas.
    official_attached = bool(official_pdf_path and os.path.exists(official_pdf_path))
    annexes_count = sum(1 for path in (attachment_paths or []) if path and os.path.exists(path))
    pieces_valeur, pieces_note = _resume_pieces_jointes(
        official_attached=official_attached,
        annexes_count=annexes_count,
        official_doc_label=labels["official_doc_label"],
    )
    corps_kwargs = dict(
        requisition_num=requisition_num,
        objet=objet,
        montant_total=montant_total,
        created_by=created_by,
        examinateur=examinateur,
        examine_le=_format_date_fr(examen_le),
        service_name=service_name,
        devise=devise,
        pieces_valeur=pieces_valeur,
        pieces_note=pieces_note,
        brand_name=brand_name,
        organisation_name=organisation_name,
        organisation_slug=organisation_slug,
        type_requisition=type_requisition,
    )

    msg = EmailMessage()
    # Le Bureau trie sur l'objet : il doit y lire la référence, ce qu'on attend
    # de lui et le montant, sans ouvrir le message.
    msg["Subject"] = (
        f"{labels['subject_prefix']} {requisition_num} — décision du Bureau requise "
        f"({_format_currency(montant_total, devise)})"
    )
    msg["From"] = sender
    msg["To"] = president_email
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    msg.set_content(_generer_corps_mail(**corps_kwargs))
    msg.add_alternative(_generer_corps_mail_html(**corps_kwargs), subtype="html")

    if official_pdf_path:
        if os.path.exists(official_pdf_path):
            try:
                _log_attachment_metadata(official_pdf_path, context_label=f"requisition {requisition_num} official_pdf")
                _attach_file(
                    msg,
                    official_pdf_path,
                    filename=os.path.basename(official_pdf_path),
                )
            except Exception:
                logger.exception("Failed to attach official PDF for %s", requisition_num)
        else:
            logger.warning("Official PDF not found for requisition %s: %s", requisition_num, official_pdf_path)

    _attach_paths(msg, attachment_paths or [], context_label=f"requisition {requisition_num}")
    logger.info(
        "Email MIME prepared for requisition %s attachment_count=%s",
        requisition_num,
        _count_message_attachments(msg),
    )

    try:
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
    organisation_slug: str | None = None,
    attachment_paths: list[str] | None = None,
) -> None:
    cc_list = _split_emails(cc_emails)
    brand_label = _format_brand_label(brand_name, organisation_name)
    tenant_url = _tenant_portal_url(organisation_slug)

    msg = EmailMessage()
    msg["Subject"] = f"Groupe de réquisitions {dossier_reference}"
    msg["From"] = sender
    msg["To"] = president_email
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    lines = [
        "Chers Membres du Bureau,",
        "",
        f"Nous vous informons qu'un nouveau groupe de réquisitions (Dossier d'examen) a été constitué : {dossier_reference}",
        "",
        "Résumé du dossier :",
        f"- Nombre de documents : {len(requisition_nums)}",
        f"- Montant total : {montant_total:,.2f} $",
        f"- Créé par : {created_by}",
        "",
        "Liste des réquisitions incluses :",
    ]
    lines.extend([f"- {num}" for num in requisition_nums])
    if tenant_url:
        lines.extend(["", f"Lien de l'antenne émettrice : {tenant_url}"])
    lines.extend([
        "",
        "Merci de vous connecter à votre espace pour valider ce dossier.",
        "",
        "Cordialement,",
        "ONEC Smart",
        brand_label
    ])
    msg.set_content("\n".join(lines))
    req_items = "".join(f"<li>{html.escape(num)}</li>" for num in requisition_nums)
    tenant_link_block = (
        f"""
          <div style="margin:18px 0 2px; padding:14px 16px; border:1px solid #d9eee7; border-radius:12px; background:#f2fbf8;">
            <div style="font-size:13px; color:#58736c; font-weight:700; margin-bottom:8px;">Antenne émettrice</div>
            <a href="{html.escape(tenant_url)}" style="display:inline-block; padding:10px 16px; border-radius:10px; background:#0f7b62; color:#ffffff; text-decoration:none; font-weight:700;">
              Ouvrir l'espace ONEC Smart
            </a>
            <div style="margin-top:8px; font-size:12px; color:#6b7f79;">{html.escape(tenant_url)}</div>
          </div>
        """
        if tenant_url
        else ""
    )
    msg.add_alternative(
        f"""
        <html>
          <body style="margin:0; padding:24px; background:#f6faf9; font-family: Arial, sans-serif; color:#1f2937; line-height:1.6;">
            <div style="max-width:640px; margin:0 auto; border:1px solid #dfe9e6; border-radius:16px; overflow:hidden; background:#ffffff;">
              <div style="padding:22px 24px; background:#0f7b62; color:#ffffff;">
                <div style="font-size:12px; text-transform:uppercase; letter-spacing:.08em; opacity:.86;">ONEC Smart</div>
                <h2 style="margin:6px 0 0; font-size:21px; line-height:1.25;">Groupe de réquisitions à examiner</h2>
              </div>
              <div style="padding:22px 24px;">
                <p style="margin:0 0 14px;">Chers Membres du Bureau,</p>
                <p style="margin:0 0 18px;">Un nouveau groupe de réquisitions a été constitué.</p>
                <div style="padding:14px 16px; border:1px solid #e2ebe8; border-radius:12px; background:#fbfefd;">
                  <div style="font-weight:800; color:#155d4c; margin-bottom:8px;">Résumé du dossier</div>
                  <p style="margin:0 0 8px;"><strong>Groupe :</strong> {html.escape(dossier_reference)}</p>
                  <p style="margin:0 0 8px;"><strong>Nombre :</strong> {len(requisition_nums)}</p>
                  <p style="margin:0 0 8px;"><strong>Total :</strong> {html.escape(f"{montant_total:,.2f} $")}</p>
                  <p style="margin:0;"><strong>Créé par :</strong> {html.escape(created_by)}</p>
                </div>
                <div style="margin-top:16px;">
                  <div style="font-weight:800; color:#155d4c; margin-bottom:8px;">Réquisitions incluses</div>
                  <ul style="margin:0; padding-left:20px;">{req_items}</ul>
                </div>
                {tenant_link_block}
                <p style="margin:18px 0 0;">Merci de vous connecter à votre espace pour valider ce dossier.</p>
              </div>
              <div style="padding:14px 24px; background:#f8fafc; color:#7b8d88; font-size:12px; text-align:center;">
                {html.escape(brand_label)} · ONEC Smart
              </div>
            </div>
          </body>
        </html>
        """,
        subtype="html",
    )

    _attach_paths(msg, attachment_paths or [], context_label=f"dossier {dossier_reference}")

    try:
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
        "ONEC Smart\n"
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
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
            &copy; 2026 {brand_label} - ONEC Smart
          </div>
        </div>
      </body>
    </html>
    """
    msg.add_alternative(html_content, subtype="html")

    try:
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
    cc_emails: str | None = None,
    subject: str,
    title: str,
    body_lines: list[str],
    brand_name: str = "ONEC",
    organisation_name: str | None = None,
    organisation_slug: str | None = None,
    official_pdf_path: str | None = None,
    attachment_paths: list[str] | None = None,
) -> bool:
    """Envoie un email de workflow. Retourne True si l'envoi a réussi, False
    sinon (utile pour les envois synchrones, ex. relances, où l'appelant doit
    savoir si le message est réellement parti)."""
    brand_label = _format_brand_label(brand_name, organisation_name)
    tenant_url = _tenant_portal_url(organisation_slug)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    cc_list = _split_emails(cc_emails)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    plain_lines = list(body_lines)
    if tenant_url:
        plain_lines.extend(["", "Accès à l'antenne émettrice :", tenant_url])
    plain_body = "\n".join(plain_lines)
    msg.set_content(plain_body)

    html_body = "\n".join(
        f"<p style=\"margin:0 0 12px;\">{html.escape(line)}</p>" for line in body_lines if line.strip()
    )
    tenant_link_block = (
        f"""
            <div style="margin:18px 0 2px; padding:14px 16px; border:1px solid #d9eee7; border-radius:12px; background:#f2fbf8;">
              <div style="font-size:13px; color:#58736c; font-weight:700; margin-bottom:8px;">Antenne émettrice</div>
              <a href="{html.escape(tenant_url)}" style="display:inline-block; padding:10px 16px; border-radius:10px; background:#0f7b62; color:#ffffff; text-decoration:none; font-weight:700;">
                Ouvrir l'espace ONEC Smart
              </a>
              <div style="margin-top:8px; font-size:12px; color:#6b7f79;">{html.escape(tenant_url)}</div>
            </div>
        """
        if tenant_url
        else ""
    )
    html_content = f"""
    <html>
      <body style="margin:0; padding:24px; background:#f6faf9; font-family: Arial, sans-serif; color: #1f2937; line-height: 1.6;">
        <div style="max-width: 640px; margin: 0 auto; border: 1px solid #dfe9e6; border-radius: 16px; overflow: hidden; background:#ffffff;">
          <div style="background: linear-gradient(135deg, #0f7b62, #075a49); color: white; padding: 22px 24px;">
            <div style="font-size:12px; text-transform:uppercase; letter-spacing:.08em; opacity:.86;">ONEC Smart</div>
            <h2 style="margin: 6px 0 0; font-size: 21px; line-height:1.25;">{html.escape(title)}</h2>
          </div>
          <div style="padding: 22px 24px;">
            {html_body}
            {tenant_link_block}
          </div>
          <div style="background-color: #f8fafc; padding: 14px 24px; text-align: center; font-size: 12px; color: #7b8d88;">
            &copy; 2026 {html.escape(brand_label)} · ONEC Smart
          </div>
        </div>
      </body>
    </html>
    """
    msg.add_alternative(html_content, subtype="html")

    if official_pdf_path:
        if os.path.exists(official_pdf_path):
            try:
                _attach_file(
                    msg,
                    official_pdf_path,
                    filename=os.path.basename(official_pdf_path),
                )
            except Exception:
                logger.exception("Failed to attach workflow official PDF for %s", recipient)
        else:
            logger.warning("Workflow official PDF not found for %s: %s", recipient, official_pdf_path)

    _attach_paths(msg, attachment_paths or [], context_label=f"workflow {subject}")
    logger.info(
        "Workflow email MIME prepared subject=%s recipient=%s attachment_count=%s",
        subject,
        recipient,
        _count_message_attachments(msg),
    )

    try:
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
        logger.info("Workflow email sent to %s", recipient)
        return True
    except Exception:
        logger.exception("Failed to send workflow email to %s", recipient)
        return False


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
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
    msg["Subject"] = f"Note de débit SaaS {invoice_number}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    amount_fmt = f"{amount:,.2f} {currency}"
    lines = [
        f"Bonjour,",
        "",
        f"Votre paiement d'abonnement SaaS pour {organisation_name} a bien été reçu.",
        f"Note de débit : {invoice_number}",
        f"Montant payé : {amount_fmt}",
    ]
    if period_end:
        lines.append(f"Abonnement valide jusqu'au : {period_end}")
    lines.extend(["", "La note de débit est jointe à ce message.", "", "Cordialement,", "Plateforme SaaS ONE CPK"])
    msg.set_content("\n".join(lines))
    if attachment_path:
        _attach_paths(msg, [attachment_path], context_label=f"SaaS invoice {invoice_number}")

    try:
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
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
        _send_email_message(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            msg=msg,
        )
        logger.info("Subscription renewal alert sent to %s", ", ".join(recipients))
        return True
    except Exception:
        logger.exception("Failed to send subscription renewal alert")
        return False
