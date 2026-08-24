"""Notifications WhatsApp — paiements, sorties de fonds, isolation multi-tenant.

Ces tests visent le comportement observable, pas l'implémentation : un paiement
notifie, un canal fermé n'appelle jamais le fournisseur, une panne laisse
l'opération métier intacte, seuls les membres du Bureau ayant donné leur accord
reçoivent les sorties, un double traitement n'envoie rien deux fois, et une
organisation ne peut pas atteindre les destinataires d'une autre.

Ils utilisent les fixtures de `conftest.py` (`db_session`, `test_organisation`,
`async_session`) et une vraie base PostgreSQL : la dé-duplication repose sur une
contrainte d'unicité et l'isolation tenant sur des jointures — deux choses qu'un
dépôt simulé en mémoire ne prouverait pas.

    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/onec_cpk_test \
        python -m pytest tests/test_whatsapp_notifications.py -v
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.models.commission_member import CommissionMember, CommissionRole
from app.models.notification_log import (
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SKIPPED,
    NotificationLog,
)
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.service_member_function import ServiceMemberFunction
from app.services.notifications import events
from app.services.notifications.providers.base import ProviderConfig, ProviderResult, WhatsAppProvider
from app.services.notifications.providers.registry import register_provider
from app.services.notifications.recipients import resolve_outflow_recipients
from app.services.notifications.service import Recipient, WhatsAppSettings, notify_whatsapp


# ── Fournisseur d'essai ──────────────────────────────────────────────────────


class RecordingProvider(WhatsAppProvider):
    """Enregistre les appels au lieu d'émettre. Programmable en échec."""

    name = "recording"
    calls: list[tuple[str, str]] = []
    fail_with: str | None = None
    unconfigured: bool = False

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.fail_with = None
        cls.unconfigured = False

    def is_configured(self) -> tuple[bool, str]:
        if type(self).unconfigured:
            return False, "Fournisseur non configuré (test)."
        return True, ""

    async def send_message(self, *, to: str, text: str) -> ProviderResult:
        type(self).calls.append((to, text))
        if type(self).fail_with:
            return ProviderResult.failure(type(self).fail_with)
        return ProviderResult.success(f"msg-{len(type(self).calls)}")


register_provider(RecordingProvider, "Fournisseur d'essai")


SORTIE_VARIABLES = {
    "reference": "SOR-2026-0142",
    "date": "23/08/2026",
    "beneficiaire": "Kabila Services SARL",
    "motif": "Fournitures de bureau",
    "montant": "1 500,00",
    "devise": "USD",
    "canal": "Banque",
    "poste_budgetaire": "Charges administratives",
    "auteur": "Christian KIDIKALA",
}

SERVICE_CODE = "WA-BUREAU"


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(autouse=True)
async def clean_state(db_session):
    """Les envois commitent : on nettoie explicitement avant chaque test."""
    RecordingProvider.reset()
    await _purge(db_session)
    yield
    await _purge(db_session)


async def _purge(db) -> None:
    await db.execute(delete(NotificationLog))
    services = (
        await db.execute(select(Service.id).where(Service.code.like(f"{SERVICE_CODE}%")))
    ).scalars().all()
    if services:
        await db.execute(delete(CommissionMember).where(CommissionMember.service_id.in_(services)))
        await db.execute(
            delete(ServiceMemberFunction).where(ServiceMemberFunction.service_id.in_(services))
        )
        await db.execute(delete(Service).where(Service.id.in_(services)))
    await db.commit()


@pytest.fixture
def settings_factory(async_session):
    """Réglages ouverts par défaut, visant la base de test."""

    def build(**overrides) -> WhatsAppSettings:
        base = dict(
            enabled=True,
            notify_payments=True,
            notify_sorties=True,
            provider="recording",
            provider_config=ProviderConfig(api_url="https://exemple.test", api_key="k"),
            organisation_name="ONEC CPK",
        )
        base.update(overrides)
        return WhatsAppSettings(**base)

    return build


@pytest.fixture
def send(async_session, settings_factory):
    """Raccourci : met en file et remet, en visant la base de test."""

    async def _send(db, *, organisation_id, event_type, entity_id, recipients,
                    variables=None, settings=None, entity_type="sortie_fonds", nonce=""):
        return await notify_whatsapp(
            db,
            None,
            organisation_id=organisation_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            recipients=recipients,
            variables=variables if variables is not None else SORTIE_VARIABLES,
            settings=settings or settings_factory(),
            nonce=nonce,
            session_factory=async_session,
        )

    return _send


async def make_org(db, nom: str, slug: str) -> Organisation:
    existing = (
        await db.execute(select(Organisation).where(Organisation.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    org = Organisation(nom=nom, slug=slug, is_active=True)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


async def make_bureau_member(db, organisation, *, nom, fonction, telephone, notify):
    """Crée au besoin le service « Bureau » du tenant, sa fonction, puis le membre."""
    code = f"{SERVICE_CODE}-{organisation.id}"
    service = (
        await db.execute(select(Service).where(Service.code == code))
    ).scalars().first()
    if service is None:
        service = Service(code=code, libelle="Bureau", organisation_id=organisation.id)
        db.add(service)
        await db.commit()
        await db.refresh(service)

    function = (
        await db.execute(
            select(ServiceMemberFunction).where(
                ServiceMemberFunction.service_id == service.id,
                ServiceMemberFunction.label == fonction,
            )
        )
    ).scalars().first()
    if function is None:
        function = ServiceMemberFunction(
            label=fonction, organisation_id=organisation.id, service_id=service.id
        )
        db.add(function)
        await db.commit()
        await db.refresh(function)

    member = CommissionMember(
        service_id=service.id,
        full_name=nom,
        function_id=function.id,
        role_type=CommissionRole.MEMBRE,
        telephone=telephone,
        notify_whatsapp=notify,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def logs(db, **filters) -> list[NotificationLog]:
    statement = select(NotificationLog).order_by(NotificationLog.created_at)
    for column, value in filters.items():
        statement = statement.where(getattr(NotificationLog, column) == value)
    return (await db.execute(statement)).scalars().all()


async def count_logs(db) -> int:
    return (await db.execute(select(func.count()).select_from(NotificationLog))).scalar_one()


# ── Paiements ────────────────────────────────────────────────────────────────


async def test_paiement_notifie_le_client(db_session, test_organisation, send):
    envoyes = await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.PAYMENT_RECEIVED,
        entity_type="encaissement",
        entity_id="ENC-1",
        recipients=[Recipient(phone="0810123456", name="Jean MUKENDI")],
        variables={"reference": "ND-2026-001", "montant": "250,00", "devise": "USD"},
    )

    assert envoyes == 1
    destinataire, message = RecordingProvider.calls[0]
    assert destinataire == "243810123456", "le numéro doit être normalisé en E.164"
    assert "Jean MUKENDI" in message and "250,00 USD" in message

    (ligne,) = await logs(db_session)
    assert ligne.status == STATUS_SENT
    assert ligne.sent_at is not None


async def test_canal_ferme_naucun_appel_fournisseur(
    db_session, test_organisation, send, settings_factory
):
    envoyes = await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.PAYMENT_RECEIVED,
        entity_type="encaissement",
        entity_id="ENC-1",
        recipients=[Recipient(phone="0810123456")],
        variables={},
        settings=settings_factory(enabled=False),
    )

    assert envoyes == 0
    assert RecordingProvider.calls == []
    assert await count_logs(db_session) == 0


async def test_famille_paiements_desactivee_seule(
    db_session, test_organisation, send, settings_factory
):
    ferme = settings_factory(notify_payments=False)

    assert 0 == await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.PAYMENT_RECEIVED,
        entity_type="encaissement",
        entity_id="ENC-1",
        recipients=[Recipient(phone="0810123456")],
        variables={},
        settings=ferme,
    )
    # …tandis que les sorties, elles, continuent de partir.
    assert 1 == await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.FUND_OUTFLOW,
        entity_id="SOR-1",
        recipients=[Recipient(phone="0810123456")],
        settings=ferme,
    )


async def test_panne_fournisseur_laisse_loperation_intacte(db_session, test_organisation, send):
    """Aucune exception ne remonte : la ligne porte FAILED et son motif."""
    RecordingProvider.fail_with = "HTTP 502 — instance déconnectée"

    envoyes = await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.PAYMENT_RECEIVED,
        entity_type="encaissement",
        entity_id="ENC-1",
        recipients=[Recipient(phone="0810123456", name="Jean MUKENDI")],
        variables={},
    )

    assert envoyes == 1
    (ligne,) = await logs(db_session)
    assert ligne.status == STATUS_FAILED
    assert "502" in (ligne.error_message or "")
    assert ligne.sent_at is None
    assert ligne.attempts == 1


async def test_fournisseur_non_configure_est_dit_dans_le_journal(
    db_session, test_organisation, send
):
    RecordingProvider.unconfigured = True

    await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.PAYMENT_RECEIVED,
        entity_type="encaissement",
        entity_id="ENC-1",
        recipients=[Recipient(phone="0810123456")],
        variables={},
    )

    (ligne,) = await logs(db_session)
    assert ligne.status == STATUS_FAILED
    assert "non configuré" in (ligne.error_message or "").lower()
    assert RecordingProvider.calls == [], "aucun appel réseau sans configuration"


# ── Sorties de fonds ─────────────────────────────────────────────────────────


async def test_trois_membres_actifs_trois_notifications(db_session, test_organisation, send):
    for nom, fonction, tel in [
        ("Christian KIDIKALA", "Président", "0810111111"),
        ("Marie NSIMBA", "Rapporteur", "0810222222"),
        ("Joseph ILUNGA", "Trésorier", "0810333333"),
    ]:
        await make_bureau_member(
            db_session, test_organisation, nom=nom, fonction=fonction, telephone=tel, notify=True
        )

    destinataires = await resolve_outflow_recipients(db_session, test_organisation.id)
    assert len(destinataires) == 3

    envoyes = await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.FUND_OUTFLOW,
        entity_id="SOR-2026-0142",
        recipients=destinataires,
    )

    assert envoyes == 3
    assert {numero for numero, _ in RecordingProvider.calls} == {
        "243810111111",
        "243810222222",
        "243810333333",
    }
    lignes = await logs(db_session)
    assert all(ligne.status == STATUS_SENT for ligne in lignes)
    assert {ligne.recipient_role for ligne in lignes} == {"Président", "Rapporteur", "Trésorier"}


async def test_membre_sans_accord_ne_recoit_rien(db_session, test_organisation):
    await make_bureau_member(
        db_session, test_organisation, nom="Président", fonction="Président",
        telephone="0810111111", notify=True,
    )
    await make_bureau_member(
        db_session, test_organisation, nom="Assistant", fonction="Assistant(e)",
        telephone="0810999999", notify=False,
    )

    destinataires = await resolve_outflow_recipients(db_session, test_organisation.id)

    assert [d.name for d in destinataires] == ["Président"]


async def test_membre_sans_numero_est_ignore_mais_trace(db_session, test_organisation, send):
    """Sans numéro on n'envoie pas — mais on écrit pourquoi.

    C'est ce qui distingue « ce membre n'a pas de téléphone » de « le fournisseur
    est en panne ». Sans cette trace, l'administrateur ne peut pas trancher.
    """
    envoyes = await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.FUND_OUTFLOW,
        entity_id="SOR-1",
        recipients=[
            Recipient(phone="0810111111", name="Président", role="Président"),
            Recipient(phone="", name="Rapporteur", role="Rapporteur"),
        ],
    )

    assert envoyes == 1
    ignorees = await logs(db_session, status=STATUS_SKIPPED)
    assert len(ignorees) == 1
    assert ignorees[0].recipient_name == "Rapporteur"
    assert "invalide" in (ignorees[0].error_message or "").lower()


async def test_double_traitement_nenvoie_pas_deux_fois(db_session, test_organisation, send):
    """Double clic ou rejeu HTTP : la contrainte d'unicité absorbe le second."""
    appel = dict(
        organisation_id=test_organisation.id,
        event_type=events.FUND_OUTFLOW,
        entity_id="SOR-2026-0142",
        recipients=[Recipient(phone="0810111111", name="Président", role="Président")],
    )

    assert await send(db_session, **appel) == 1
    assert await send(db_session, **appel) == 0
    assert await send(db_session, **appel) == 0

    assert len(RecordingProvider.calls) == 1, "un seul message, malgré trois traitements"
    assert await count_logs(db_session) == 1


async def test_deux_sorties_distinctes_notifient_chacune(db_session, test_organisation, send):
    """La dé-duplication ne doit pas avaler une seconde sortie légitime."""
    for reference in ("SOR-1", "SOR-2"):
        await send(
            db_session,
            organisation_id=test_organisation.id,
            event_type=events.FUND_OUTFLOW,
            entity_id=reference,
            recipients=[Recipient(phone="0810111111", name="Président")],
            variables={**SORTIE_VARIABLES, "reference": reference},
        )

    assert len(RecordingProvider.calls) == 2
    assert await count_logs(db_session) == 2


async def test_message_de_test_nest_jamais_dedupe(db_session, test_organisation, send):
    """On doit pouvoir retester une configuration autant de fois qu'on veut."""
    for essai in range(3):
        await send(
            db_session,
            organisation_id=test_organisation.id,
            event_type=events.TEST_MESSAGE,
            entity_type="test",
            entity_id="-",
            recipients=[Recipient(phone="0810111111")],
            variables={"date": "23/08/2026"},
            nonce=f"essai-{essai}",
        )

    assert len(RecordingProvider.calls) == 3


async def test_repli_sur_la_liste_dagents_si_le_bureau_est_vide(db_session, test_organisation):
    """Aucun membre renseigné : on retombe sur l'ancienne liste, jamais sur le silence."""
    destinataires = await resolve_outflow_recipients(
        db_session, test_organisation.id, fallback_numbers="0810111111, +243810222222"
    )

    assert [d.phone for d in destinataires] == ["243810111111", "243810222222"]
    assert all(d.role == "Liste des agents" for d in destinataires)


async def test_le_bureau_prime_sur_la_liste_dagents(db_session, test_organisation):
    await make_bureau_member(
        db_session, test_organisation, nom="Président", fonction="Président",
        telephone="0810111111", notify=True,
    )

    destinataires = await resolve_outflow_recipients(
        db_session, test_organisation.id, fallback_numbers="0899999999"
    )

    assert [d.phone for d in destinataires] == ["243810111111"]


# ── Multi-tenant ─────────────────────────────────────────────────────────────


async def test_une_sortie_ne_touche_que_les_membres_de_son_organisation(db_session, send):
    """Le cas qu'aucun bug ne doit jamais produire."""
    tenant_a = await make_org(db_session, "ONEC Kinshasa", "wa-tenant-a")
    tenant_b = await make_org(db_session, "ONEC Lubumbashi", "wa-tenant-b")

    await make_bureau_member(
        db_session, tenant_a, nom="Président A", fonction="Président",
        telephone="0810111111", notify=True,
    )
    await make_bureau_member(
        db_session, tenant_b, nom="Président B", fonction="Président",
        telephone="0820222222", notify=True,
    )

    destinataires_a = await resolve_outflow_recipients(db_session, tenant_a.id)
    destinataires_b = await resolve_outflow_recipients(db_session, tenant_b.id)

    assert [d.name for d in destinataires_a] == ["Président A"]
    assert [d.name for d in destinataires_b] == ["Président B"]

    await send(
        db_session,
        organisation_id=tenant_a.id,
        event_type=events.FUND_OUTFLOW,
        entity_id="SOR-A-1",
        recipients=destinataires_a,
    )

    assert [numero for numero, _ in RecordingProvider.calls] == ["243810111111"]
    lignes = await logs(db_session)
    assert len(lignes) == 1
    assert lignes[0].organisation_id == tenant_a.id


async def test_la_meme_reference_dans_deux_organisations_ne_se_dedupe_pas(db_session, send):
    """Deux tenants numérotent leurs sorties indépendamment : SOR-1 existe deux fois."""
    tenant_a = await make_org(db_session, "ONEC Kinshasa", "wa-tenant-a")
    tenant_b = await make_org(db_session, "ONEC Lubumbashi", "wa-tenant-b")

    for tenant in (tenant_a, tenant_b):
        await send(
            db_session,
            organisation_id=tenant.id,
            event_type=events.FUND_OUTFLOW,
            entity_id="SOR-1",
            recipients=[Recipient(phone="0810111111", name="Président")],
        )

    assert len(RecordingProvider.calls) == 2, "l'organisation entre dans la clé de dé-duplication"


# ── Gabarits ─────────────────────────────────────────────────────────────────


async def test_le_gabarit_du_tenant_prime_sur_celui_par_defaut(
    db_session, test_organisation, send, settings_factory
):
    await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.FUND_OUTFLOW,
        entity_id="SOR-1",
        recipients=[Recipient(phone="0810111111")],
        settings=settings_factory(
            templates={events.FUND_OUTFLOW: "Décaissement {{reference}} de {{montant}} {{devise}}."}
        ),
    )

    _, message = RecordingProvider.calls[0]
    assert message == "Décaissement SOR-2026-0142 de 1 500,00 USD."


async def test_un_champ_absent_ne_laisse_pas_de_ligne_orpheline(
    db_session, test_organisation, send
):
    """Poste budgétaire vide en dépense multi-postes : la ligne disparaît du message."""
    await send(
        db_session,
        organisation_id=test_organisation.id,
        event_type=events.FUND_OUTFLOW,
        entity_id="SOR-1",
        recipients=[Recipient(phone="0810111111")],
        variables={**SORTIE_VARIABLES, "poste_budgetaire": ""},
    )

    _, message = RecordingProvider.calls[0]
    assert "Poste budgétaire" not in message
    assert "SOR-2026-0142" in message
