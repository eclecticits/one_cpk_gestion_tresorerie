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
"""Sortie de fonds enregistrée — l'argent a réellement quitté la caisse ou le compte.

C'est le seul événement de la chaîne de dépense qui notifie le Bureau. Le visa
final de la réquisition, lui, ne déplace aucun fonds : il annonce une décision,
pas un décaissement, et il est même absent des tenants configurés en workflow
« express ».
"""

REQUISITION_APPROVED = "REQUISITION_APPROVED"
"""Visa final d'une réquisition — information, pas mouvement de trésorerie.

Conservé parce qu'il existait déjà, mais requalifié : le message dit désormais
« en attente de paiement » pour qu'on ne le confonde pas avec une sortie.
"""

# ── Service ──────────────────────────────────────────────────────────────────

TEST_MESSAGE = "TEST_MESSAGE"
"""Envoi de vérification depuis l'écran de paramètres. Jamais dé-dupliqué."""


PAYMENT_EVENTS: frozenset[str] = frozenset(
    {PAYMENT_RECEIVED, PAYMENT_PROFORMA_CONVERTED, PAYMENT_COMPLEMENT, PAYMENT_REMINDER}
)

OUTFLOW_EVENTS: frozenset[str] = frozenset({FUND_OUTFLOW, REQUISITION_APPROVED})

ALL_EVENTS: frozenset[str] = PAYMENT_EVENTS | OUTFLOW_EVENTS | {TEST_MESSAGE}

#: Libellés pour l'écran d'historique.
EVENT_LABELS: dict[str, str] = {
    PAYMENT_RECEIVED: "Paiement reçu",
    PAYMENT_PROFORMA_CONVERTED: "Pro forma convertie",
    PAYMENT_COMPLEMENT: "Paiement complémentaire",
    PAYMENT_REMINDER: "Relance de paiement",
    FUND_OUTFLOW: "Sortie de fonds",
    REQUISITION_APPROVED: "Réquisition approuvée",
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
