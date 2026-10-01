"""Tout e-mail émis par l'application se signale comme automatique."""

from __future__ import annotations

from email.message import EmailMessage

from app.services.mailer import AUTOMATIC_MESSAGE_NOTICE, mark_as_automatic_message


def _message(text: str = "Bonjour.", html: str | None = "<html><body><p>Bonjour.</p></body></html>") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Test"
    msg.set_content(text)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    return msg


def _corps(msg: EmailMessage, subtype: str) -> str:
    return msg.get_body(preferencelist=(subtype,)).get_content()


def test_texte_et_html_portent_la_mention():
    msg = _message()
    mark_as_automatic_message(msg)

    assert AUTOMATIC_MESSAGE_NOTICE in _corps(msg, "plain")
    corps_html = _corps(msg, "html")
    # Dans le corps, avant la fermeture : un client mail ignore ce qui suit </body>.
    assert corps_html.index(AUTOMATIC_MESSAGE_NOTICE) < corps_html.lower().index("</body>")
    assert "Envoyé le " in corps_html


def test_les_en_tetes_coupent_les_reponses_automatiques():
    msg = _message()
    mark_as_automatic_message(msg)
    assert msg["Auto-Submitted"] == "auto-generated"
    assert msg["X-Auto-Response-Suppress"] == "All"


def test_pas_de_doublon():
    """Ni si le modèle porte déjà la mention, ni si l'envoi est retenté."""
    msg = _message(text=f"Bonjour.\n\n{AUTOMATIC_MESSAGE_NOTICE}")
    mark_as_automatic_message(msg)
    mark_as_automatic_message(msg)

    assert _corps(msg, "plain").count(AUTOMATIC_MESSAGE_NOTICE) == 1
    assert _corps(msg, "html").count(AUTOMATIC_MESSAGE_NOTICE) == 1
    assert len(msg.get_all("Auto-Submitted")) == 1


def test_les_pieces_jointes_restent_intactes():
    msg = _message(html=None)
    msg.add_attachment(b"contenu", maintype="text", subtype="plain", filename="annexe.txt")
    mark_as_automatic_message(msg)

    (annexe,) = list(msg.iter_attachments())
    assert annexe.get_content() == "contenu"
    assert AUTOMATIC_MESSAGE_NOTICE in _corps(msg, "plain")


def test_whatsapp_porte_la_mention_une_seule_fois():
    from app.services.notifications import templates

    message = templates.with_automatic_notice("CPK — SORTIE DE FONDS\n\nMontant : 10 USD\n")
    assert message.endswith(f"\n\n_{AUTOMATIC_MESSAGE_NOTICE}_")
    # Gabarit personnalisé qui la porte déjà, ou rendu appliqué deux fois.
    assert templates.with_automatic_notice(message) == message
    assert templates.with_automatic_notice("") == ""


def test_la_mention_n_entre_pas_dans_les_gabarits_modifiables():
    """Elle est ajoutée à l'envoi : un tenant ne peut pas l'effacer en éditant son gabarit."""
    from app.services.notifications import templates

    assert all(AUTOMATIC_MESSAGE_NOTICE not in t for t in templates.DEFAULT_TEMPLATES.values())
