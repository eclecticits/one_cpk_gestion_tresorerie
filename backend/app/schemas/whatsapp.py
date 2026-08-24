"""Schémas de l'administration WhatsApp.

Une règle gouverne ce module : **aucun schéma de sortie ne porte de secret**.
La clé API entre par `WhatsAppSettingsUpdate.api_key` et ne ressort jamais.
Côté lecture, `WhatsAppSettingsOut.has_api_key` dit seulement qu'une clé est
posée — c'est le strict contrepoint de `describe_whatsapp_settings`, qui
construit exactement ce dictionnaire côté service. Ni la clé, ni une version
masquée de la clé : un `<input type="password">` pré-rempli d'astérisques a déjà
fait croire à un administrateur que sa clé était enregistrée alors qu'elle ne
l'était pas.

Convention « sentinelle » pour la clé, reprise de `schemas/ai_provider.py`
(`AIProviderConfigUpdate.api_key` : « Laisser vide pour ne pas modifier la
clé. ») : champ **absent ou vide = ne pas changer**. La suppression volontaire
passe par le drapeau explicite `clear_api_key` ; sans lui, un écran qui renvoie
`api_key: ""` à chaque enregistrement — ce que fait un formulaire dont le champ
mot de passe n'est jamais pré-rempli — effacerait la clé à la première
sauvegarde. C'est précisément l'accident que la sentinelle existe pour éviter.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Réglages ─────────────────────────────────────────────────────────────────


class ProviderOption(BaseModel):
    """Une entrée de la liste déroulante des fournisseurs."""

    value: str
    label: str


class WhatsAppSettingsOut(BaseModel):
    """Vue publique des réglages. Miroir exact de `describe_whatsapp_settings`."""

    enabled: bool = False
    notify_payments: bool = False
    notify_sorties: bool = False
    provider: str = ""
    provider_label: str = ""
    api_url: str = ""
    sender: str = ""
    phone_number_id: str = ""
    business_account_id: str = ""
    has_api_key: bool = Field(
        default=False,
        description="Indique qu'une clé API est configurée, sans la révéler.",
    )
    templates: dict[str, str] = Field(default_factory=dict)


class WhatsAppSettingsEnvelope(BaseModel):
    """Réponse de `GET /whatsapp/settings` : les réglages et de quoi les éditer.

    `warning` reprend le motif de `WhatsAppProvider.is_configured()` — « Clé API
    Evolution non renseignée. » plutôt qu'un silence dont l'administrateur ne
    déduit rien. Le motif ne contient jamais la clé, seulement son absence.
    """

    settings: WhatsAppSettingsOut
    providers: list[ProviderOption] = Field(default_factory=list)
    default_templates: dict[str, str] = Field(default_factory=dict)
    template_variables: dict[str, str] = Field(default_factory=dict)
    events: list["EventOption"] = Field(default_factory=list)
    warning: str = Field(
        default="",
        description="Motif pour lequel le canal ne pourrait pas émettre, ou vide.",
    )


class EventOption(BaseModel):
    """Un événement notifiable, avec sa famille d'activation."""

    value: str
    label: str
    family: str = Field(description="payments | sorties | service")


class WhatsAppSettingsUpdate(BaseModel):
    """Corps de `PUT /whatsapp/settings`. Tous les champs sont facultatifs.

    Seuls les champs réellement transmis sont appliqués (`exclude_unset`) : un
    écran qui n'édite que l'activation ne doit pas remettre à zéro l'URL.
    """

    enabled: bool | None = None
    notify_payments: bool | None = None
    notify_sorties: bool | None = None
    provider: str | None = Field(default=None, max_length=30)
    api_url: str | None = Field(default=None, max_length=255)
    sender: str | None = Field(default=None, max_length=40)
    phone_number_id: str | None = Field(default=None, max_length=64)
    business_account_id: str | None = Field(default=None, max_length=64)

    api_key: str | None = Field(
        default=None,
        description=(
            "Clé API en clair — chiffrée côté serveur avant stockage. "
            "Laisser absente ou vide pour ne pas modifier la clé existante."
        ),
    )
    clear_api_key: bool = Field(
        default=False,
        description="Supprime explicitement la clé enregistrée. Ignore `api_key`.",
    )

    @field_validator("provider")
    @classmethod
    def _validate_provider(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Import différé : le registre vit dans la couche service, on ne veut pas
        # que le module de schémas la charge au démarrage.
        from app.services.notifications import available_providers

        normalized = (value or "").strip().lower()
        valid = {option["value"] for option in available_providers()}
        if normalized not in valid:
            raise ValueError(
                f"Fournisseur inconnu : « {value} ». Valeurs acceptées : {sorted(valid)}."
            )
        return normalized


# ── Destinataires (membres du Bureau) ────────────────────────────────────────


class RecipientOut(BaseModel):
    """Un membre du Bureau vu depuis l'écran des notifications."""

    id: int
    full_name: str = ""
    function: str = Field(default="", description="Fonction : Président, Trésorier…")
    service_id: int | None = None
    email: str | None = None
    phone: str = Field(default="", description="Numéro normalisé (E.164 sans « + »).")
    phone_display: str = Field(default="", description="Numéro lisible : +243 810 123 456.")
    notify_whatsapp: bool = False
    status: str = Field(description="ready | no_phone | opted_out")
    status_label: str = ""


class RecipientUpdate(BaseModel):
    """Corps de `PATCH /whatsapp/recipients/{member_id}`.

    `telephone` à `""` retire le numéro ; absent, il n'est pas touché. Même
    logique de sentinelle que pour la clé API, sans le secret.
    """

    telephone: str | None = Field(default=None, max_length=50)
    notify_whatsapp: bool | None = None


# ── Gabarits ─────────────────────────────────────────────────────────────────


class TemplateOut(BaseModel):
    """Le gabarit effectif d'un événement, et de quoi le comparer au défaut."""

    event_type: str
    label: str = ""
    family: str = Field(default="", description="payments | sorties | service")
    template: str = Field(description="Gabarit appliqué : la surcharge si elle existe.")
    default_template: str = ""
    is_custom: bool = False


class TemplatesEnvelope(BaseModel):
    """Réponse de `GET /whatsapp/templates`."""

    items: list[TemplateOut] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)


class TemplatesUpdate(BaseModel):
    """Corps de `PUT /whatsapp/templates`.

    Une valeur vide (ou `null`) retire la surcharge et fait revenir l'événement
    au gabarit par défaut — c'est le seul moyen de « réinitialiser » sans avoir
    à recopier le texte d'origine.
    """

    templates: dict[str, str | None] = Field(default_factory=dict)

    @field_validator("templates")
    @classmethod
    def _not_empty(cls, value: dict[str, str | None]) -> dict[str, str | None]:
        if not value:
            raise ValueError("Aucun gabarit transmis.")
        return value


class TemplatesSaveResult(BaseModel):
    """Résultat d'un enregistrement de gabarits.

    `warnings` porte les avertissements non bloquants de `validate_template`
    (variable inconnue, par exemple) : l'enregistrement a bien eu lieu.
    """

    ok: bool = True
    updated: list[str] = Field(default_factory=list)
    reset: list[str] = Field(default_factory=list)
    warnings: dict[str, str] = Field(default_factory=dict)


# ── Journaux ─────────────────────────────────────────────────────────────────


class NotificationLogOut(BaseModel):
    """Une ligne du journal d'envoi.

    `recipient` est déjà mis en forme par l'endpoint : lisible pour qui a
    `treso.notifications.history`, masqué pour qui n'a que la lecture.
    """

    id: str
    channel: str
    event_type: str
    event_label: str = ""
    entity_type: str = ""
    entity_id: str = ""
    recipient: str = ""
    recipient_name: str = ""
    recipient_role: str = ""
    message: str = ""
    status: str
    status_label: str = ""
    provider: str = ""
    provider_message_id: str | None = None
    error_message: str | None = None
    attempts: int = 0
    created_at: datetime | None = None
    sent_at: datetime | None = None


class NotificationLogPage(BaseModel):
    """Page d'historique. `masked` dit à l'écran pourquoi les numéros sont voilés."""

    items: list[NotificationLogOut] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0
    masked: bool = False


# ── Test et renvoi ───────────────────────────────────────────────────────────


class WhatsAppTestRequest(BaseModel):
    """Corps de `POST /whatsapp/test` : un numéro libre **ou** un membre du Bureau."""

    phone: str | None = Field(default=None, max_length=50)
    member_id: int | None = None

    @model_validator(mode="after")
    def _exactly_one_target(self) -> "WhatsAppTestRequest":
        has_phone = bool((self.phone or "").strip())
        has_member = self.member_id is not None
        if has_phone == has_member:
            raise ValueError(
                "Indiquez soit un numéro (`phone`), soit un membre du Bureau "
                "(`member_id`), mais pas les deux."
            )
        return self


class DeliveryOut(BaseModel):
    """Le sort d'un message unitaire, tel qu'il figure au journal après envoi."""

    log_id: str | None = None
    recipient: str = ""
    recipient_name: str = ""
    status: str = ""
    status_label: str = ""
    error_message: str | None = None


class WhatsAppTestResult(BaseModel):
    """Résultat d'un envoi de vérification.

    L'envoi est fait dans la requête, sans tâche de fond : un test dont on
    n'apprend le sort qu'en rafraîchissant l'historique ne teste rien.
    """

    ok: bool = False
    queued: int = 0
    detail: str = ""
    deliveries: list[DeliveryOut] = Field(default_factory=list)


class ResendResult(BaseModel):
    """Résultat d'un renvoi manuel depuis le journal."""

    ok: bool = False
    detail: str = ""
    source_log_id: str = ""
    delivery: DeliveryOut | None = None


WhatsAppSettingsEnvelope.model_rebuild()
