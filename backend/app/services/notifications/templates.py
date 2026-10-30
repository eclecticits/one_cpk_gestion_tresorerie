"""Gabarits de messages WhatsApp.

Un gabarit est une chaîne à trous `{{variable}}`. Les valeurs par défaut vivent
ici ; un tenant peut les remplacer depuis l'écran de paramètres, et ses versions
sont stockées dans `system_settings.whatsapp_templates` (JSONB). Aucune
concaténation de message ne doit exister ailleurs dans le projet — c'est le
travers dont souffre déjà `mailer.py`, dont la coque HTML est recopiée quatre
fois.

Le rendu est volontairement sans moteur de template : pas de Jinja, pas
d'exécution de code dans une chaîne administrable. Un gabarit est du texte et
des trous, rien de plus. Une variable inconnue laisse une chaîne vide plutôt
que de faire échouer l'envoi — un message incomplet vaut mieux qu'un silence.
"""

from __future__ import annotations

import re

from . import events

_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
#: Emoji et pictogrammes, retirés de tout message : les e-mails n'en portent
#: pas, WhatsApp non plus — y compris dans un gabarit personnalisé par un tenant
#: ou dans le mot saisi par un utilisateur. Les filets (━) et puces (▸, •) de
#: mise en forme sont hors de ces plages et restent.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U0001FC00-\U0001FFFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\uFE0E\uFE0F\u200D\u20E3]+ ?"
)
#: Marques de mise en forme WhatsApp et puces, ignorées pour juger d'une ligne vide.
_FORMATTING = re.compile(r"[*_~`▸•]")

#: Variables acceptées, avec leur description — sert à l'aide en ligne de l'écran.
TEMPLATE_VARIABLES: dict[str, str] = {
    "organisation": "Nom de l'organisation",
    "nom": "Nom du destinataire",
    "salutation": "Formule d'appel : Monsieur / Madame selon le sexe, « Madame, Monsieur » pour une SEC ou une société",
    "fonction": "Fonction du destinataire (Président, Trésorier…)",
    "reference": "Référence de la pièce",
    "date": "Date de l'opération",
    "montant": "Montant formaté",
    "devise": "Devise",
    "motif": "Motif ou libellé",
    "beneficiaire": "Bénéficiaire",
    "poste_budgetaire": "Poste budgétaire",
    "canal": "Canal de décaissement (caisse, banque, mobile money)",
    "mode_paiement": "Mode de paiement détaillé",
    "auteur": "Personne ayant enregistré l'opération",
    "validateur": "Personne ayant validé l'opération",
    "solde_apres": "Solde après opération",
    "tranche": "Tranche N sur M, pour un décaissement progressif",
    "reste_a_payer": "Reste à payer",
    "total": "Montant total de la pièce",
    "echeance": "Date limite de dépôt du justificatif",
    "consigne_justificatif": "Phrase demandant le justificatif sous 48 h, vide si aucun n'est attendu",
    "periode": "Période couverte par un rapport transmis",
    "resume": "Chiffres clés d'un rapport transmis, une ligne par chiffre",
    "message": "Mot d'accompagnement saisi par l'expéditeur",
    "piece_jointe": "Phrase annonçant le PDF envoyé par e-mail, vide s'il n'est pas parti",
}


#: Même ossature que les e-mails (`mailer.py`) : un bandeau (organisation, titre,
#: référence), une phrase d'annonce, le montant mis en avant, le tableau des
#: détails, puis la formule de fin. Mise en forme WhatsApp : *gras*, _italique_.
_RULE = "━━━━━━━━━━━━━━"


def _header(titre: str) -> str:
    return f"*{{{{organisation}}}}* · ONEC Smart\n{_RULE}\n*{titre}*\n_{{{{reference}}}}_\n\n"


def _rows(*rows: tuple[str, str]) -> str:
    """Lignes « ▸ *Étiquette :* {{valeur}} » — le tableau des e-mails."""
    return "".join(f"▸ *{label} :* {value}\n" for label, value in rows)


DEFAULT_TEMPLATES: dict[str, str] = {
    events.FUND_OUTFLOW_BENEFICIARY: (
        _header("FONDS REMIS")
        + "{{salutation}}\n"
        "La somme ci-dessous vous a été remise le {{date}}.\n"
        "\n"
        "Montant : *{{montant}} {{devise}}*\n"
        "\n"
        + _rows(
            ("Référence", "{{reference}}"),
            ("Bénéficiaire", "{{beneficiaire}}"),
            ("Motif", "{{motif}}"),
            ("Canal", "{{canal}}"),
        )
        + "\n"
        "{{consigne_justificatif}}"
    ),
    events.JUSTIFICATIF_RELANCE: (
        _header("JUSTIFICATIF NON REÇU")
        + "{{salutation}}\n"
        "La pièce justificative des fonds qui vous ont été remis le {{date}} "
        "n'a toujours pas été déposée à la caisse.\n"
        "\n"
        "Montant : *{{montant}} {{devise}}*\n"
        "\n"
        + _rows(
            ("Référence", "{{reference}}"),
            ("Bénéficiaire", "{{beneficiaire}}"),
            ("Motif", "{{motif}}"),
            ("Délai annoncé", "{{echeance}}"),
        )
        + "\n"
        "Merci de la déposer sans attendre. Les autorités de l'organisation "
        "reçoivent ce message en copie."
    ),
    events.FUND_OUTFLOW: (
        _header("SORTIE DE FONDS")
        + "Une nouvelle sortie de fonds vient d'être enregistrée.\n"
        "\n"
        "Montant : *{{montant}} {{devise}}*\n"
        "\n"
        + _rows(
            ("Date", "{{date}}"),
            ("Bénéficiaire", "{{beneficiaire}}"),
            ("Motif", "{{motif}}"),
            ("Canal", "{{canal}}"),
            ("Poste budgétaire", "{{poste_budgetaire}}"),
        )
        + "{{tranche}}\n"
        "\n"
        "_Enregistrée par : {{auteur}}_"
    ),
    events.REQUISITION_APPROVED: (
        _header("RÉQUISITION APPROUVÉE")
        + "Une réquisition vient de recevoir son visa final. "
        "Elle est en attente de paiement — aucun fonds n'a encore été décaissé.\n"
        "\n"
        "Montant : *{{montant}} {{devise}}*\n"
        "\n"
        + _rows(
            ("Date", "{{date}}"),
            ("Bénéficiaire", "{{beneficiaire}}"),
            ("Motif", "{{motif}}"),
            ("Validée par", "{{validateur}}"),
        )
    ),
    events.PAYMENT_RECEIVED: (
        _header("PAIEMENT REÇU")
        + "{{salutation}}\n"
        "Nous accusons réception de votre paiement.\n"
        "\n"
        "Montant reçu : *{{montant}} {{devise}}*\n"
        "\n"
        + _rows(
            ("Date", "{{date}}"),
            ("Objet", "{{motif}}"),
        )
        + "\n"
        "Merci de votre confiance."
    ),
    events.PAYMENT_PROFORMA_CONVERTED: (
        _header("PRO FORMA CONVERTIE")
        + "{{salutation}}\n"
        "Votre pro forma a été convertie en note de débit après paiement.\n"
        "\n"
        "Montant reçu : *{{montant}} {{devise}}*\n"
        "\n"
        + _rows(
            ("Date", "{{date}}"),
            ("Objet", "{{motif}}"),
        )
        + "\n"
        "Merci de votre confiance."
    ),
    events.PAYMENT_COMPLEMENT: (
        _header("PAIEMENT COMPLÉMENTAIRE")
        + "{{salutation}}\n"
        "Nous accusons réception de votre paiement complémentaire.\n"
        "\n"
        "Montant reçu : *{{montant}} {{devise}}*\n"
        "\n"
        + _rows(
            ("Date", "{{date}}"),
            ("Total de la note", "{{total}} {{devise}}"),
            ("Reste à payer", "{{reste_a_payer}} {{devise}}"),
        )
        + "\n"
        "Merci de votre confiance."
    ),
    events.PAYMENT_REMINDER: (
        _header("RAPPEL DE RÈGLEMENT")
        + "{{salutation}}\n"
        "Nous vous rappelons qu'un règlement reste attendu.\n"
        "\n"
        "Reste à payer : *{{reste_a_payer}} {{devise}}*\n"
        "\n"
        + _rows(("Objet", "{{motif}}"),)
        + "\n"
        "_Si le règlement a déjà été effectué, merci d'ignorer ce message._"
    ),
    events.REPORT_SENT: (
        _header("RAPPORT TRANSMIS")
        + "{{salutation}}\n"
        "{{message}}\n"
        "\n"
        "*Période :* {{periode}}\n"
        "{{resume}}\n"
        "\n"
        "{{piece_jointe}}\n"
        "\n"
        "_Transmis par : {{auteur}}_"
    ),
    events.TEST_MESSAGE: (
        "*{{organisation}}* · ONEC Smart\n"
        f"{_RULE}\n"
        "*MESSAGE DE TEST*\n"
        "\n"
        "Ceci est un message de vérification envoyé depuis ONEC Smart.\n"
        "Si vous le recevez, la configuration WhatsApp est opérationnelle.\n"
        "\n"
        "_Envoyé le {{date}}._"
    ),
}


def render(template: str, variables: dict[str, object] | None = None) -> str:
    """Remplace les `{{trous}}` et nettoie le résultat.

    Une variable absente devient une chaîne vide, et les lignes qui n'auraient
    plus que leur étiquette (« Poste budgétaire : ») sont retirées : un message
    ne doit pas afficher un champ vide au Bureau.
    """
    values = {k: ("" if v is None else str(v)) for k, v in (variables or {}).items()}

    def _substitute(match: re.Match[str]) -> str:
        return values.get(match.group(1), "")

    rendered = _PLACEHOLDER.sub(_substitute, template or "")
    return _strip_empty_fields(strip_emoji(rendered))


def strip_emoji(text: str) -> str:
    """Retire les emoji avec l'espace qui les suit : « *🧪 TEST* » devient « *TEST* »."""
    return _EMOJI.sub("", text or "")


#: Mention ajoutée sous TOUT message WhatsApp, au rendu et non dans les gabarits :
#: un tenant qui personnalise son gabarit ne peut pas la retirer par mégarde.
#: Même texte que le pied de page des e-mails (`mailer.AUTOMATIC_MESSAGE_NOTICE`),
#: en italique WhatsApp.
AUTOMATIC_MESSAGE_NOTICE = "Message automatique émis par ONEC Smart. Merci de ne pas y répondre."


def with_automatic_notice(message: str) -> str:
    """Ajoute la mention « message automatique », sauf si le texte la porte déjà."""
    text = (message or "").rstrip()
    if not text or AUTOMATIC_MESSAGE_NOTICE in text:
        return text
    return f"{text}\n\n_{AUTOMATIC_MESSAGE_NOTICE}_"


def resolve(event_type: str, overrides: dict | None = None) -> str:
    """Gabarit du tenant s'il existe et n'est pas vide, sinon celui par défaut."""
    if overrides:
        custom = overrides.get(event_type)
        if isinstance(custom, str) and custom.strip():
            return custom
    return DEFAULT_TEMPLATES.get(event_type, "")


def render_event(event_type: str, variables: dict[str, object] | None = None,
                 overrides: dict | None = None) -> str:
    return render(resolve(event_type, overrides), variables)


def _strip_empty_fields(text: str) -> str:
    kept: list[str] = []
    for line in (text or "").splitlines():
        # Lue sans sa mise en forme (*gras*, _italique_, puce) : « ▸ *Motif :* »
        # est un champ vide au même titre que « Motif : ».
        bare = _FORMATTING.sub("", line).strip()
        if line.strip() and not bare:
            continue  # « __ » : une référence vide, entourée de son italique.
        # « Étiquette : » sans valeur — le trou n'a pas été rempli.
        if re.fullmatch(r"[^:]{1,40}:\s*", bare):
            continue
        # Valeur faite des seuls trous vides : « Reste à payer :  USD ».
        if re.fullmatch(r"[^:]{1,40}:\s*(USD|CDF|EUR)?\s*", bare):
            continue
        kept.append(line.rstrip())

    # Réduit les respirations multiples laissées par les lignes supprimées.
    out: list[str] = []
    blank = 0
    for line in kept:
        if line.strip():
            blank = 0
            out.append(line)
        else:
            blank += 1
            if blank <= 1:
                out.append("")
    return "\n".join(out).strip()


def validate_template(template: str) -> tuple[bool, str]:
    """Vérifie qu'un gabarit administrable est exploitable.

    Contrôles volontairement souples : on refuse ce qui casserait l'envoi, pas ce
    qui déplaît. Une variable inconnue est signalée mais n'invalide pas — elle
    rendra une chaîne vide.
    """
    if not template or not template.strip():
        return False, "Le gabarit est vide."
    if len(template) > 4000:
        return False, "Le gabarit dépasse 4 000 caractères."
    unknown = sorted({m.group(1) for m in _PLACEHOLDER.finditer(template)} - set(TEMPLATE_VARIABLES))
    if unknown:
        return True, "Variables inconnues, elles resteront vides : " + ", ".join(unknown)
    return True, ""
