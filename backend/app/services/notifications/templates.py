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

#: Variables acceptées, avec leur description — sert à l'aide en ligne de l'écran.
TEMPLATE_VARIABLES: dict[str, str] = {
    "organisation": "Nom de l'organisation",
    "nom": "Nom du destinataire",
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
}


DEFAULT_TEMPLATES: dict[str, str] = {
    events.FUND_OUTFLOW: (
        "{{organisation}} — SORTIE DE FONDS\n"
        "\n"
        "Une nouvelle sortie de fonds vient d'être enregistrée.\n"
        "\n"
        "Référence : {{reference}}\n"
        "Date : {{date}}\n"
        "Bénéficiaire : {{beneficiaire}}\n"
        "Motif : {{motif}}\n"
        "Montant : {{montant}} {{devise}}\n"
        "Canal : {{canal}}\n"
        "Poste budgétaire : {{poste_budgetaire}}\n"
        "{{tranche}}"
        "Enregistrée par : {{auteur}}\n"
        "\n"
        "Opération enregistrée dans ONEC Smart."
    ),
    events.REQUISITION_APPROVED: (
        "{{organisation}} — RÉQUISITION APPROUVÉE\n"
        "\n"
        "Une réquisition vient de recevoir son visa final. "
        "Elle est en attente de paiement — aucun fonds n'a encore été décaissé.\n"
        "\n"
        "Référence : {{reference}}\n"
        "Date : {{date}}\n"
        "Bénéficiaire : {{beneficiaire}}\n"
        "Motif : {{motif}}\n"
        "Montant : {{montant}} {{devise}}\n"
        "Validée par : {{validateur}}"
    ),
    events.PAYMENT_RECEIVED: (
        "{{organisation}}\n"
        "\n"
        "Bonjour {{nom}},\n"
        "Nous accusons réception de votre paiement.\n"
        "\n"
        "Référence : {{reference}}\n"
        "Date : {{date}}\n"
        "Montant reçu : {{montant}} {{devise}}\n"
        "Objet : {{motif}}\n"
        "\n"
        "Merci de votre confiance."
    ),
    events.PAYMENT_PROFORMA_CONVERTED: (
        "{{organisation}}\n"
        "\n"
        "Bonjour {{nom}},\n"
        "Votre pro forma a été convertie en note de débit après paiement.\n"
        "\n"
        "Référence : {{reference}}\n"
        "Date : {{date}}\n"
        "Montant reçu : {{montant}} {{devise}}\n"
        "Objet : {{motif}}\n"
        "\n"
        "Merci de votre confiance."
    ),
    events.PAYMENT_COMPLEMENT: (
        "{{organisation}}\n"
        "\n"
        "Bonjour {{nom}},\n"
        "Nous accusons réception de votre paiement complémentaire.\n"
        "\n"
        "Référence : {{reference}}\n"
        "Date : {{date}}\n"
        "Montant reçu : {{montant}} {{devise}}\n"
        "Montant total de la note : {{total}} {{devise}}\n"
        "Reste à payer : {{reste_a_payer}} {{devise}}\n"
        "\n"
        "Merci de votre confiance."
    ),
    events.PAYMENT_REMINDER: (
        "{{organisation}}\n"
        "\n"
        "Bonjour {{nom}},\n"
        "Nous vous rappelons qu'un règlement reste attendu.\n"
        "\n"
        "Référence : {{reference}}\n"
        "Objet : {{motif}}\n"
        "Reste à payer : {{reste_a_payer}} {{devise}}\n"
        "\n"
        "Si le règlement a déjà été effectué, merci d'ignorer ce message."
    ),
    events.TEST_MESSAGE: (
        "{{organisation}} — TEST\n"
        "\n"
        "Ceci est un message de vérification envoyé depuis ONEC Smart.\n"
        "Si vous le recevez, la configuration WhatsApp est opérationnelle.\n"
        "\n"
        "Envoyé le {{date}}."
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
    return _strip_empty_fields(rendered)


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
        stripped = line.strip()
        # « Étiquette : » sans valeur — le trou n'a pas été rempli.
        if re.fullmatch(r"[^:]{1,40}:\s*", stripped):
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
