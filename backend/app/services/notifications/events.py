"""Vocabulaire des événements de notification.

La liste est fermée et documentée : elle dit exactement quels moments métier
notifient, et — tout aussi important — lesquels ne notifient pas. Elle a été
établie en relevant, endpoint par endpoint, les envois d'e-mails existants ;
WhatsApp part aux mêmes moments, sauf pour les sorties de fonds où l'écart est
délibéré (voir FUND_OUTFLOW).
"""

from __future__ import annotations

# ── Paiements ────────────────────────────────────────────────────────────────
# Ces quatre-là, et seulement ces quatre-là, envoient déjà un e-mail via
# `schedule_client_payment_email`. WhatsApp s'y aligne.

PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
"""Note de débit créée avec un paiement immédiat (montant_paye > 0)."""

PAYMENT_PROFORMA_CONVERTED = "PAYMENT_PROFORMA_CONVERTED"
"""Pro forma convertie en note de débit payée."""

PAYMENT_COMPLEMENT = "PAYMENT_COMPLEMENT"
"""Paiement complémentaire sur un encaissement déjà partiellement réglé."""

PAYMENT_REMINDER = "PAYMENT_REMINDER"
"""Relance manuelle envoyée depuis l'interface."""

# ── Sorties de fonds ─────────────────────────────────────────────────────────

FUND_OUTFLOW = "FUND_OUTFLOW"
"""Ancien message au Bureau à chaque sortie de fonds — n'est plus émis.

Prévenir tout le Bureau à chaque décaissement était trop : le message part
désormais au bénéficiaire (FUND_OUTFLOW_BENEFICIARY), avec quelques adresses
choisies en copie. Le code reste au vocabulaire pour que l'historique des envois
passés garde son libellé.
"""

FUND_OUTFLOW_BENEFICIARY = "FUND_OUTFLOW_BENEFICIARY"
"""Sortie de fonds enregistrée — le bénéficiaire est prévenu, la « Copie au paiement » aussi.

Quand la sortie attend un justificatif, le message annonce le délai de 48 h.
"""

JUSTIFICATIF_RELANCE = "JUSTIFICATIF_RELANCE"
"""Justificatif non rapporté 7 jours après le décaissement — relance unique.

Part au bénéficiaire avec les « Autorités en relance » en copie. Une seule
relance par sortie : `sorties_fonds.justificatif_relance_le` en est le verrou.
"""

REQUISITION_APPROVED = "REQUISITION_APPROVED"
"""Visa final d'une réquisition — information, pas mouvement de trésorerie.

Conservé parce qu'il existait déjà, mais requalifié : le message dit désormais
« en attente de paiement » pour qu'on ne le confonde pas avec une sortie.
"""

# ── Rapports ─────────────────────────────────────────────────────────────────

REPORT_SENT = "REPORT_SENT"
"""Rapport transmis à des membres du Bureau depuis l'écran des rapports.

Envoi manuel, choisi destinataire par destinataire : comme le test, il ne
dépend que de l'activation générale du canal, pas d'une famille d'événements.
Le PDF part par e-mail ; WhatsApp porte le mot d'accompagnement et les chiffres.
"""

# ── Service ──────────────────────────────────────────────────────────────────

TEST_MESSAGE = "TEST_MESSAGE"
"""Envoi de vérification depuis l'écran de paramètres. Jamais dé-dupliqué."""


PAYMENT_EVENTS: frozenset[str] = frozenset(
    {PAYMENT_RECEIVED, PAYMENT_PROFORMA_CONVERTED, PAYMENT_COMPLEMENT, PAYMENT_REMINDER}
)

OUTFLOW_EVENTS: frozenset[str] = frozenset(
    {FUND_OUTFLOW, FUND_OUTFLOW_BENEFICIARY, JUSTIFICATIF_RELANCE, REQUISITION_APPROVED}
)

ALL_EVENTS: frozenset[str] = PAYMENT_EVENTS | OUTFLOW_EVENTS | {REPORT_SENT, TEST_MESSAGE}

#: Libellés pour l'écran d'historique.
EVENT_LABELS: dict[str, str] = {
    PAYMENT_RECEIVED: "Paiement reçu",
    PAYMENT_PROFORMA_CONVERTED: "Pro forma convertie",
    PAYMENT_COMPLEMENT: "Paiement complémentaire",
    PAYMENT_REMINDER: "Relance de paiement",
    FUND_OUTFLOW: "Sortie de fonds",
    FUND_OUTFLOW_BENEFICIARY: "Fonds remis au bénéficiaire",
    JUSTIFICATIF_RELANCE: "Relance de justificatif",
    REQUISITION_APPROVED: "Réquisition approuvée",
    REPORT_SENT: "Rapport transmis au Bureau",
    TEST_MESSAGE: "Message de test",
}


# ── Événements explicitement exclus ──────────────────────────────────────────
# Documenté pour que la question ne se repose pas à chaque revue :
#
#   Pro forma seule ............ aucun argent reçu, l'e-mail ne part pas non plus.
#   Annulation d'encaissement .. correction comptable ; prévenir le client
#                                d'une annulation technique crée plus de bruit
#                                que de valeur, et aucun e-mail ne part.
#   Corbeille / restauration ... écritures purement techniques.
#   PaymentLog ................. journal HTTP du flux d'abonnement SaaS,
#                                sans rapport avec les encaissements.
#   Régularisation d'écart ..... opération interne de caisse.
#   Webhook de paiement en ligne  n'envoie aucun e-mail aujourd'hui ; à trancher
#                                séparément avant de l'ajouter.
