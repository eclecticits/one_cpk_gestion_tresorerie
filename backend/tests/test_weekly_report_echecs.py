"""Un rapport hebdomadaire qui ne part pas doit le dire.

Jusqu'ici, un destinataire ou des identifiants SMTP absents faisaient abandonner
l'envoi en silence : une ligne de journal, rien dans le statut, et le bouton
« Envoyer maintenant » répondait « Rapport hebdomadaire envoyé. ». Une erreur
SMTP était bien inscrite, mais sous un message générique, et le bouton
annonçait quand même un succès.
"""

from __future__ import annotations

import smtplib

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.tenant_context import set_current_tenant_id
from app.models.system_settings import SystemSettings
from app.services import weekly_report
from app.services.weekly_report import TreasuryReportNotSent, send_weekly_report

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(autouse=True)
def _sans_reglages_serveur(monkeypatch):
    # Les variables d'environnement priment sur l'écran Notifications : on les
    # neutralise pour que seuls les paramètres de l'organisation comptent.
    for nom in ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "weekly_report_to", "weekly_report_cc"):
        monkeypatch.setattr(settings, nom, None)


async def _parametres(db_session, organisation_id: int, **valeurs) -> None:
    set_current_tenant_id(organisation_id)
    db_session.add(SystemSettings(organisation_id=organisation_id, **valeurs))
    await db_session.commit()


async def _statut(db_session, organisation_id: int) -> SystemSettings:
    db_session.expire_all()
    return (
        await db_session.execute(select(SystemSettings).where(SystemSettings.organisation_id == organisation_id))
    ).scalar_one()


async def test_sans_destinataire_l_echec_est_leve_et_inscrit(db_session, admin_isole):
    org_id = admin_isole.organisation_id
    await _parametres(db_session, org_id, email_expediteur="cpk@example.com", smtp_password="secret")

    with pytest.raises(TreasuryReportNotSent, match="Aucun destinataire"):
        await send_weekly_report(db_session, tenant_id=org_id)

    ns = await _statut(db_session, org_id)
    assert ns.last_weekly_report_status == "failed"
    assert "Aucun destinataire" in ns.last_weekly_report_error
    assert ns.last_weekly_report_failure_at is not None


async def test_sans_identifiants_smtp_l_echec_est_leve(db_session, admin_isole):
    org_id = admin_isole.organisation_id
    await _parametres(db_session, org_id, email_president="se@example.com")

    with pytest.raises(TreasuryReportNotSent, match="Identifiants SMTP manquants"):
        await send_weekly_report(db_session, tenant_id=org_id)

    assert (await _statut(db_session, org_id)).last_weekly_report_status == "failed"


async def test_le_refus_du_serveur_smtp_remonte_en_clair(db_session, admin_isole, monkeypatch):
    org_id = admin_isole.organisation_id
    await _parametres(
        db_session, org_id,
        email_expediteur="cpk@example.com", smtp_password="secret", email_president="se@example.com",
    )

    def _refus(**_kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    monkeypatch.setattr(weekly_report, "send_weekly_report_email", _refus)

    with pytest.raises(TreasuryReportNotSent) as excinfo:
        await send_weekly_report(db_session, tenant_id=org_id)

    attendu = "Erreur SMTP : 535 5.7.8 Username and Password not accepted"
    assert str(excinfo.value) == attendu
    assert (await _statut(db_session, org_id)).last_weekly_report_error == attendu


async def test_un_envoi_reussi_est_inscrit(db_session, admin_isole, monkeypatch):
    org_id = admin_isole.organisation_id
    await _parametres(
        db_session, org_id,
        email_expediteur="cpk@example.com", smtp_password="secret", email_tresorier="tresorier@example.com",
    )
    envois: list[dict] = []
    monkeypatch.setattr(weekly_report, "send_weekly_report_email", lambda **kw: envois.append(kw))

    await send_weekly_report(db_session, tenant_id=org_id)

    # Le trésorier sert de destinataire quand le président n'est pas renseigné.
    assert [e["recipient"] for e in envois] == ["tresorier@example.com"]
    ns = await _statut(db_session, org_id)
    assert ns.last_weekly_report_status == "success"
    assert ns.last_weekly_report_error == ""


def test_le_mail_porte_le_lien_du_tenant(monkeypatch):
    """Le lien permet au destinataire de vérifier les chiffres sur l'espace du tenant."""
    from datetime import datetime

    monkeypatch.setattr(settings, "tenant_base_domain", "onec-rdc.org")
    url = weekly_report._tenant_portal_url("cpk")
    assert url == "https://cpk.onec-rdc.org/login"

    stats = {
        "period_start": datetime(2026, 9, 21), "period_end": datetime(2026, 9, 28),
        **{k: 0.0 for k in ("caisse_usd", "caisse_cdf", "banques_usd", "banques_cdf",
                            "entrees_usd", "entrees_cdf", "sorties_usd", "sorties_cdf")},
    }
    maintenant = datetime(2026, 9, 28, 7, 30)
    assert f'href="{url}"' in weekly_report._build_weekly_html(stats, maintenant, "CPK", url)
    assert f"Pour toute vérification : {url}" in weekly_report._build_weekly_text(stats, maintenant, "CPK", url)
    # Sans domaine configuré, pas de lien plutôt qu'un lien cassé.
    assert "Pour toute vérification" not in weekly_report._build_weekly_html(stats, maintenant, "CPK", None)


def test_la_periode_mensuelle_est_le_mois_ecoule():
    from datetime import datetime

    debut, fin = weekly_report._period_last_month(datetime(2026, 10, 1, 7, 30))
    assert (debut, fin) == (datetime(2026, 9, 1), datetime(2026, 10, 1))
    # Passage d'année.
    debut, fin = weekly_report._period_last_month(datetime(2027, 1, 1, 7, 30))
    assert (debut, fin) == (datetime(2026, 12, 1), datetime(2027, 1, 1))


async def test_le_mensuel_a_son_propre_statut(db_session, admin_isole, monkeypatch):
    """Un mensuel réussi ne doit pas masquer l'état de l'hebdo, ni l'inverse."""
    org_id = admin_isole.organisation_id
    await _parametres(
        db_session, org_id,
        email_expediteur="cpk@example.com", smtp_password="secret", email_president="se@example.com",
    )
    envois: list[dict] = []
    monkeypatch.setattr(weekly_report, "send_weekly_report_email", lambda **kw: envois.append(kw))

    await weekly_report.send_monthly_treasury_report(db_session, tenant_id=org_id)

    assert envois[0]["subject"].startswith("Rapport mensuel trésorerie - ")
    assert "Entrées du mois USD" in envois[0]["text_body"]
    ns = await _statut(db_session, org_id)
    assert ns.last_monthly_report_status == "success"
    assert ns.last_weekly_report_status == "never"


async def test_une_periode_deja_servie_n_est_pas_renvoyee(db_session, admin_isole, monkeypatch):
    """Garde contre un second déclenchement (worker en retard après le verrou rendu)."""
    org_id = admin_isole.organisation_id
    await _parametres(
        db_session, org_id,
        email_expediteur="cpk@example.com", smtp_password="secret", email_president="se@example.com",
    )
    monkeypatch.setattr(weekly_report, "send_weekly_report_email", lambda **kw: None)

    assert not await weekly_report._already_sent_for_period(db_session, org_id, weekly_report.WEEKLY)
    await send_weekly_report(db_session, tenant_id=org_id)
    assert await weekly_report._already_sent_for_period(db_session, org_id, weekly_report.WEEKLY)
    # Le mensuel, lui, n'a pas encore été servi.
    assert not await weekly_report._already_sent_for_period(db_session, org_id, weekly_report.MONTHLY)


def test_un_retard_ne_fait_pas_sauter_le_rapport():
    """APScheduler abandonne par défaut un déclenchement en retard d'une seconde."""
    from app.utils.scheduler import REPORT_MISFIRE_GRACE_SECONDS

    assert REPORT_MISFIRE_GRACE_SECONDS >= 600
