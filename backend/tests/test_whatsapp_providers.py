"""Tests de l'abstraction fournisseur et de la logique sans base.

L'enjeu de ces tests est de prouver que changer de fournisseur est bien un
changement de réglage : les trois implémentations parlent des protocoles
franchement différents — JSON + en-tête `apikey`, JSON + jeton Bearer,
form-urlencoded + Basic — et pourtant rendent le même `ProviderResult`.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.notifications import templates
from app.services.notifications.phone import (
    format_phone_display,
    mask_phone,
    normalize_phone,
    normalize_phone_list,
)
from app.services.notifications.providers.base import ProviderConfig
from app.services.notifications.providers.evolution import EvolutionWhatsAppProvider
from app.services.notifications.providers.meta import MetaWhatsAppProvider
from app.services.notifications.providers.registry import (
    DEFAULT_PROVIDER,
    available_providers,
    get_provider,
)
from app.services.notifications.providers.twilio import TwilioWhatsAppProvider
from app.services.notifications.service import build_dedup_key


class _Capture:
    """Intercepte la requête HTTP sortante et rend une réponse programmée."""

    def __init__(self, status: int = 200, payload: dict | None = None):
        self.status = status
        self.payload = payload if payload is not None else {}
        self.request: httpx.Request | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.request = request
        return httpx.Response(self.status, json=self.payload)

    def install(self, monkeypatch):
        transport = httpx.MockTransport(self.handler)
        original = httpx.AsyncClient.__init__

        def patched(client_self, *args, **kwargs):
            kwargs["transport"] = transport
            return original(client_self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
        return self


# ── Evolution ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evolution_respecte_le_contrat_existant(monkeypatch):
    """Le format est celui déjà en production : en-tête `apikey`, corps number/text."""
    capture = _Capture(payload={"key": {"id": "BAE5F1"}}).install(monkeypatch)
    provider = EvolutionWhatsAppProvider(
        ProviderConfig(api_url="https://evo.test/message/sendText", api_key="secret")
    )

    result = await provider.send_message(to="243810123456", text="Bonjour")

    assert result.ok
    assert result.provider_message_id == "BAE5F1"
    assert capture.request is not None
    assert capture.request.headers["apikey"] == "secret"
    import json

    assert json.loads(capture.request.content) == {"number": "243810123456", "text": "Bonjour"}


@pytest.mark.asyncio
async def test_evolution_remonte_lerreur_au_lieu_de_lavaler(monkeypatch):
    """C'est toute la différence avec l'ancien `send_whatsapp_message`."""
    _Capture(status=502, payload={"message": "instance déconnectée"}).install(monkeypatch)
    provider = EvolutionWhatsAppProvider(
        ProviderConfig(api_url="https://evo.test/send", api_key="secret")
    )

    result = await provider.send_message(to="243810123456", text="Bonjour")

    assert not result.ok
    assert "502" in (result.error or "")
    assert "déconnectée" in (result.error or "")


@pytest.mark.asyncio
async def test_evolution_sans_cle_ne_tente_aucun_appel(monkeypatch):
    capture = _Capture().install(monkeypatch)
    provider = EvolutionWhatsAppProvider(ProviderConfig(api_url="https://evo.test/send"))

    result = await provider.send_message(to="243810123456", text="Bonjour")

    assert not result.ok
    assert "Clé API" in (result.error or "")
    assert capture.request is None


# ── Meta ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_meta_envoie_un_texte_libre_sans_gabarit(monkeypatch):
    capture = _Capture(payload={"messages": [{"id": "wamid.XX"}]}).install(monkeypatch)
    provider = MetaWhatsAppProvider(
        ProviderConfig(api_key="EAAG...", phone_number_id="123456")
    )

    result = await provider.send_message(to="243810123456", text="Bonjour")

    assert result.ok
    assert result.provider_message_id == "wamid.XX"
    assert "123456/messages" in str(capture.request.url)
    assert capture.request.headers["authorization"] == "Bearer EAAG..."
    import json

    body = json.loads(capture.request.content)
    assert body["type"] == "text"
    assert body["text"]["body"] == "Bonjour"


@pytest.mark.asyncio
async def test_meta_bascule_en_gabarit_approuve_quand_il_est_configure(monkeypatch):
    """Hors fenêtre de 24 h, Meta n'accepte qu'un template : le provider le sait."""
    capture = _Capture(payload={"messages": [{"id": "wamid.YY"}]}).install(monkeypatch)
    provider = MetaWhatsAppProvider(
        ProviderConfig(
            api_key="EAAG...",
            phone_number_id="123456",
            extra={"template_name": "sortie_fonds", "language": "fr"},
        )
    )

    await provider.send_message(to="243810123456", text="Corps du message")

    import json

    body = json.loads(capture.request.content)
    assert body["type"] == "template"
    assert body["template"]["name"] == "sortie_fonds"
    assert body["template"]["components"][0]["parameters"][0]["text"] == "Corps du message"


@pytest.mark.asyncio
async def test_meta_sans_numero_emetteur_est_explicite():
    provider = MetaWhatsAppProvider(ProviderConfig(api_key="EAAG..."))
    ok, raison = provider.is_configured()
    assert not ok
    assert "phone_number_id" in raison


# ── Twilio ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_twilio_utilise_form_urlencoded_et_le_prefixe_whatsapp(monkeypatch):
    capture = _Capture(payload={"sid": "SM123"}).install(monkeypatch)
    provider = TwilioWhatsAppProvider(
        ProviderConfig(
            api_key="token", sender="14155238886", extra={"account_sid": "AC123"}
        )
    )

    result = await provider.send_message(to="243810123456", text="Bonjour")

    assert result.ok
    assert result.provider_message_id == "SM123"
    corps = capture.request.content.decode()
    assert "From=whatsapp%3A%2B14155238886" in corps
    assert "To=whatsapp%3A%2B243810123456" in corps
    assert capture.request.headers.get("authorization", "").startswith("Basic ")


# ── Fabrique ─────────────────────────────────────────────────────────────────


def test_un_nom_inconnu_retombe_sur_le_defaut_sans_lever():
    """Une faute de frappe dans un réglage ne doit pas couper toutes les notifications."""
    provider = get_provider("fournisseur-inexistant", ProviderConfig())
    assert provider.name == DEFAULT_PROVIDER


def test_les_trois_fournisseurs_sont_proposes():
    valeurs = {p["value"] for p in available_providers()}
    assert {"evolution", "meta", "twilio"} <= valeurs


def test_aucun_fournisseur_ne_leve_sur_une_configuration_vide():
    for nom in ("evolution", "meta", "twilio"):
        ok, raison = get_provider(nom, ProviderConfig()).is_configured()
        assert not ok
        assert raison, f"{nom} doit dire pourquoi il ne peut pas émettre"


# ── Numéros ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "saisie,attendu",
    [
        ("0810 123 456", "243810123456"),
        ("+243810123456", "243810123456"),
        ("00243810123456", "243810123456"),
        ("810123456", "243810123456"),
        ("243810123456", "243810123456"),
        ("+33 6 12 34 56 78", "33612345678"),
        ("12", None),
        ("", None),
        (None, None),
        ("pas un numéro", None),
    ],
)
def test_normalisation_des_numeros(saisie, attendu):
    assert normalize_phone(saisie) == attendu


def test_la_liste_dedoublonne_apres_normalisation():
    """« 0810… » et « +243810… » sont le même destinataire : un seul envoi."""
    assert normalize_phone_list("0810123456, +243810123456\n0999888777;") == [
        "243810123456",
        "243999888777",
    ]


def test_affichage_et_masquage():
    assert format_phone_display("243810123456") == "+243 810 123 456"
    assert mask_phone("243810123456") == "+243 ••• ••• 456"
    assert "123456" not in mask_phone("243810123456")


# ── Dé-duplication ───────────────────────────────────────────────────────────


def test_la_cle_de_dedup_separe_ce_qui_doit_letre():
    base = dict(
        organisation_id=1,
        event_type="FUND_OUTFLOW",
        entity_type="sortie_fonds",
        entity_id="SOR-1",
        channel="WHATSAPP",
        recipient="243810111111",
    )
    reference = build_dedup_key(**base)

    assert build_dedup_key(**base) == reference, "stable pour un même événement"
    assert build_dedup_key(**{**base, "organisation_id": 2}) != reference
    assert build_dedup_key(**{**base, "entity_id": "SOR-2"}) != reference
    assert build_dedup_key(**{**base, "recipient": "243810222222"}) != reference
    assert build_dedup_key(**{**base, "channel": "EMAIL"}) != reference
    assert build_dedup_key(**base, nonce="renvoi-1") != reference, "le renvoi doit passer"


# ── Gabarits ─────────────────────────────────────────────────────────────────


def test_le_gabarit_de_sortie_rend_le_message_attendu():
    message = templates.render_event(
        "FUND_OUTFLOW",
        {
            "organisation": "ONEC CPK",
            "reference": "SOR-2026-0142",
            "date": "23/08/2026",
            "beneficiaire": "Kabila Services SARL",
            "motif": "Fournitures de bureau",
            "montant": "1 500,00",
            "devise": "USD",
            "canal": "Banque",
            "poste_budgetaire": "Charges administratives",
            "auteur": "Christian KIDIKALA",
        },
    )
    for attendu in [
        "ONEC CPK — SORTIE DE FONDS",
        "Référence : SOR-2026-0142",
        "Montant : 1 500,00 USD",
        "Canal : Banque",
        "Poste budgétaire : Charges administratives",
    ]:
        assert attendu in message


def test_une_variable_inconnue_ne_fait_pas_echouer_lenvoi():
    assert templates.render("Bonjour {{inexistante}}.", {}) == "Bonjour ."


def test_validation_de_gabarit():
    assert templates.validate_template("")[0] is False
    assert templates.validate_template("x" * 4001)[0] is False
    ok, message = templates.validate_template("Bonjour {{fantaisie}}")
    assert ok and "fantaisie" in message
