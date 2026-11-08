"""Compte SMTP et fournisseur WhatsApp : vus et modifiés par le super administrateur seulement.

Les réglages restent à leur place (Paramètres > Notifications, > WhatsApp) ; seul
le super administrateur voit le compte d'envoi et le fournisseur. L'hôte SMTP,
le port et l'URL du fournisseur en font partie : qui peut les changer fait
partir le mot de passe ou la clé enregistrés vers un serveur de son choix.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import admin as admin_endpoints
from app.api.v1.endpoints import whatsapp as whatsapp_endpoints
from app.schemas.whatsapp import WhatsAppSettingsUpdate

ADMIN = SimpleNamespace(id=None, role="admin")
SUPER_ADMIN = SimpleNamespace(id=None, role="super_admin")


def test_le_compte_smtp_est_masque_hors_super_admin():
    donnees = {
        "email_expediteur": "envoi@example.org", "smtp_password": "secret",
        "smtp_host": "smtp.example.org", "smtp_port": 587, "email_president": "president@example.org",
    }
    masque = admin_endpoints._sanitize_notification_settings(donnees, ADMIN)
    assert (masque["email_expediteur"], masque["smtp_password"], masque["smtp_host"], masque["smtp_port"]) == ("", "", "", None)
    assert masque["email_president"] == "president@example.org"
    assert admin_endpoints._sanitize_notification_settings(donnees, SUPER_ADMIN) == donnees


def test_l_hote_et_le_port_smtp_ne_s_ecrivent_pas_hors_super_admin():
    assert {"smtp_host", "smtp_port", "smtp_password", "email_expediteur"} <= admin_endpoints.NOTIFICATION_SENSITIVE_FIELDS


@pytest.mark.asyncio
async def test_le_fournisseur_whatsapp_est_masque_hors_super_admin(db_session, test_organisation):
    org = test_organisation.id
    ligne = await whatsapp_endpoints._settings_row(db_session, org)
    ligne.whatsapp_provider = "evolution"
    ligne.whatsapp_api_url = "https://wa.example.org/message/sendText/onec"
    ligne.whatsapp_sender = "243810000000"
    await db_session.commit()

    vue_admin = await whatsapp_endpoints._settings_envelope(db_session, org, ADMIN)
    s = vue_admin.settings
    assert (s.provider, s.provider_label, s.api_url, s.sender, s.has_api_key) == ("", "", "", "", False)
    assert vue_admin.providers == []
    assert "evolution" not in vue_admin.warning.casefold()

    vue_super = await whatsapp_endpoints._settings_envelope(db_session, org, SUPER_ADMIN)
    assert (vue_super.settings.provider, vue_super.settings.sender) == ("evolution", "243810000000")
    assert vue_super.providers


@pytest.mark.asyncio
@pytest.mark.parametrize("champ, valeur", [
    ("provider", "meta"), ("api_url", "https://ailleurs.example.org"), ("sender", "243999"), ("api_key", "cle"),
])
async def test_le_fournisseur_whatsapp_ne_se_modifie_pas_hors_super_admin(db_session, test_organisation, champ, valeur):
    with pytest.raises(HTTPException) as exc:
        await whatsapp_endpoints.update_whatsapp_settings(
            WhatsAppSettingsUpdate(**{champ: valeur}), request=None,
            current_user=ADMIN, tenant_id=test_organisation.id, db=db_session,
        )
    assert exc.value.status_code == 403
