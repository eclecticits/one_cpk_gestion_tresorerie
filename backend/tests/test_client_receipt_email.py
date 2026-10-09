"""Message au client après paiement : formule d'appel et contenu."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.services import client_receipt_email as module
from app.services.client_receipt_email import salutation_lignes, schedule_client_payment_email
from app.services.notifications import events, templates


@pytest.mark.parametrize(
    ("type_client", "nom", "sexe", "gerant", "attendu"),
    [
        ("expert_comptable", "MUKENDI Pierre", "M", None, ["Bonjour Monsieur MUKENDI Pierre,"]),
        ("expert_comptable", "KALALA Marie", "F", None, ["Bonjour Madame KALALA Marie,"]),
        ("expert_comptable", "KALALA Marie", "f", None, ["Bonjour Madame KALALA Marie,"]),
        ("expert_comptable", "X Y", None, None, ["Bonjour X Y,"]),
        ("personne_physique", "Jeanne Kabeya", "F", None, ["Bonjour Madame Jeanne Kabeya,"]),
        (
            "sec",
            "Cabinet Beta SARL",
            None,
            "J. DUPONT",
            ["Madame, Monsieur,", "À l'attention de J. DUPONT, associé gérant de Cabinet Beta SARL."],
        ),
        ("sec", "Cabinet Beta SARL", None, None, ["Madame, Monsieur,", "À l'attention de Cabinet Beta SARL."]),
        ("personne_morale", "Société ABC", None, None, ["Madame, Monsieur,", "À l'attention de Société ABC."]),
        ("autre", "", None, None, ["Madame, Monsieur,"]),
    ],
)
def test_salutation_lignes(type_client, nom, sexe, gerant, attendu):
    assert salutation_lignes(type_client, nom, sexe=sexe, associe_gerant=gerant) == attendu


def test_gabarits_whatsapp_de_paiement_utilisent_la_salutation():
    for event in (events.PAYMENT_RECEIVED, events.PAYMENT_COMPLEMENT, events.PAYMENT_REMINDER):
        rendu = templates.render_event(event, {"salutation": "Madame, Monsieur,\nÀ l'attention de X."})
        assert "Madame, Monsieur,\nÀ l'attention de X." in rendu
        assert "Bonjour" not in rendu


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    """Rend l'expert, puis le nom de l'organisation, dans l'ordre des requêtes."""

    def __init__(self, *values):
        self._values = list(values)

    async def execute(self, _query):
        return _FakeResult(self._values.pop(0))


@pytest.mark.asyncio
async def test_complement_annonce_le_versement_du_jour_et_salue_la_sec(monkeypatch):
    async def fake_settings(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(module, "get_system_settings", fake_settings)
    monkeypatch.setattr(
        module,
        "resolve_smtp_config",
        lambda _ns: SimpleNamespace(host="h", port=25, user="u", password="p", sender="s@x.cd"),
    )
    expert = SimpleNamespace(
        email="contact@beta.cd", nom_denomination="Cabinet Beta SARL", sexe=None, associe_gerant="J. DUPONT"
    )
    encaissement = SimpleNamespace(
        id=uuid.uuid4(),
        type_client="sec",
        expert_comptable_id=uuid.uuid4(),
        client_nom=None,
        montant_total=Decimal("250"),
        montant_paye=Decimal("100"),
        numero_recu="REC-0142",
        numero_proforma=None,
        libelle="",
        date_paiement=None,
        date_encaissement=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    tasks = BackgroundTasks()
    email = await schedule_client_payment_email(
        _FakeDb(expert, "ONEC Kinshasa"),
        tasks,
        encaissement,
        1,
        montant_recu=Decimal("100"),
        mode_paiement_recu="cash",
        date_recu=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )

    assert email == "contact@beta.cd"
    kwargs = tasks.tasks[0].kwargs
    lignes = kwargs["body_lines"]
    assert kwargs["subject"] == "Paiement reçu – Note de débit REC-0142 – reste 150,00 $"
    assert lignes[:2] == ["Madame, Monsieur,", "À l'attention de J. DUPONT, associé gérant de Cabinet Beta SARL."]
    assert "Nous accusons réception de votre paiement du 30/09/2026." in lignes
    assert "Montant reçu : 100,00 $ (espèces)" in lignes
    assert "Reste à payer : 150,00 $" in lignes
    # Libellé vide : pas de ligne « Objet : » orpheline.
    assert not any(ligne.startswith("Objet") for ligne in lignes)
    assert lignes[-1] == "La Trésorerie – ONEC Kinshasa"


def test_montants_au_format_francais():
    assert module._fmt_usd(1250) == "1 250,00 $"


@pytest.mark.asyncio
async def test_copie_des_paiements_visible_et_sans_le_payeur(monkeypatch):
    async def fake_settings(*_args, **_kwargs):
        return SimpleNamespace(emails_paiement_cc="compta@onec.cd; CONTACT@beta.cd, tresorier@onec.cd")

    monkeypatch.setattr(module, "get_system_settings", fake_settings)
    monkeypatch.setattr(
        module,
        "resolve_smtp_config",
        lambda _ns: SimpleNamespace(host="h", port=25, user="u", password="p", sender="s@x.cd"),
    )
    expert = SimpleNamespace(email="contact@beta.cd", nom_denomination="Beta", sexe="M", associe_gerant=None)
    encaissement = SimpleNamespace(
        id=uuid.uuid4(),
        type_client="expert_comptable",
        expert_comptable_id=uuid.uuid4(),
        client_nom=None,
        montant_total=Decimal("100"),
        montant_paye=Decimal("100"),
        numero_recu="REC-0200",
        numero_proforma=None,
        libelle="",
        date_paiement=None,
        date_encaissement=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    tasks = BackgroundTasks()
    await schedule_client_payment_email(_FakeDb(expert, "ONEC"), tasks, encaissement, 1)

    kwargs = tasks.tasks[0].kwargs
    assert kwargs["recipient"] == "contact@beta.cd"
    # Le payeur n'est pas recopié en CC de son propre message.
    assert kwargs["cc_emails"] == "compta@onec.cd, tresorier@onec.cd"

