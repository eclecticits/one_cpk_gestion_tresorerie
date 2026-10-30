from types import SimpleNamespace

import pytest

from app.api.v1.endpoints.envoi_rapports import _contact_whatsapp, _destinataire, _texte_email
from app.services.mailer import bureau_email_recipients
from app.services.notifications import events, templates


def _fiche(id_: int, nom: str, service: str, fonction: str, *, email=None, telephone=None, notify=False):
    return SimpleNamespace(
        id=id_,
        full_name=nom,
        service_id=id_,
        service=SimpleNamespace(libelle=service, code=""),
        function=SimpleNamespace(label=fonction),
        custom_title=None,
        role_type=None,
        email=email,
        telephone=telephone,
        notify_whatsapp=notify,
    )


def test_aucun_gabarit_par_defaut_ne_porte_d_emoji():
    assert [k for k, v in templates.DEFAULT_TEMPLATES.items() if templates.strip_emoji(v) != v] == []


def test_les_emoji_d_un_gabarit_personnalise_sont_retires_au_rendu():
    rendu = templates.render("*🧪 TEST* pour {{nom}} 🙏\nMerci ✅", {"nom": "Jean"})
    assert rendu == "*TEST* pour Jean\nMerci"
    # Les filets et puces de mise en forme ne sont pas des emoji.
    assert templates.render("━━━\n▸ *Motif :* x • y") == "━━━\n▸ *Motif :* x • y"


def test_le_gabarit_rapport_transmis_omet_les_lignes_vides():
    rendu = templates.render_event(
        events.REPORT_SENT,
        {
            "organisation": "ONEC",
            "reference": "Projet FORM-2026",
            "salutation": "Bonjour Jean,",
            "message": "",
            "periode": "du 01/01/2026 au 29/10/2026",
            "resume": "▸ Entrées : 1 200,00 USD",
            "piece_jointe": "",
            "auteur": "Christian",
        },
    )
    assert "RAPPORT TRANSMIS" in rendu
    assert "▸ Entrées : 1 200,00 USD" in rendu
    assert "\n\n\n" not in rendu
    assert events.REPORT_SENT in events.ALL_EVENTS


def test_destinataire_reunit_les_fiches_et_repere_le_bureau():
    fiches = [
        _fiche(1, "Jean MUKENDI", "Commission Tableau", "Membre"),
        _fiche(2, "Jean Mukendi", "BUREAU", "Président(e)", email="jean@onec.cd", telephone="0810123456"),
    ]
    d = _destinataire(fiches)
    assert d.id == 2
    assert d.fonction == "Président(e)"
    assert d.email == "jean@onec.cd"
    assert d.bureau is True
    # Un numéro sans opt-in ne rend pas la personne joignable par WhatsApp.
    assert d.whatsapp is False
    assert _destinataire([_fiche(3, "Marie", "Bureau", "Trésorier", telephone="0810123457", notify=True)]).whatsapp is True


def test_whatsapp_exige_numero_et_consentement_sur_la_meme_fiche():
    """Un opt-in vide ne doit pas autoriser le numéro d'une autre fonction."""
    fiches = [
        _fiche(10, "Jean", "Bureau", "Président(e)", telephone="0810123456", notify=False),
        _fiche(11, "Jean", "Commission", "Membre", telephone=None, notify=True),
    ]
    assert _contact_whatsapp(fiches) is None
    assert _destinataire(fiches).whatsapp is False

    fiches[1].telephone = "0810123457"
    contact = _contact_whatsapp(fiches)
    assert contact is not None
    assert contact[0].id == 11
    assert contact[1]
    assert _destinataire(fiches).whatsapp is True


def test_texte_email_adresse_au_bureau():
    texte = _texte_email(
        titre="Projet FORM-2026",
        periode="du 01/01/2026 au 29/10/2026",
        resume=["Entrées : 1 200,00 USD"],
        message="Pour la réunion de jeudi.",
        auteur="Christian",
        organisation="ONEC",
    )
    assert texte.startswith("Madame, Monsieur les membres du Bureau,\n\nPour la réunion de jeudi.")
    assert "ci-joint le rapport « Projet FORM-2026 », du 01/01/2026 au 29/10/2026." in texte
    assert "  - Entrées : 1 200,00 USD" in texte
    assert texte.endswith("ONEC")


def test_destinataires_email_comme_les_requisitions():
    # Président en « À », Bureau en « Cc », sans recopier le Président.
    assert bureau_email_recipients("pres@onec.cd", "a@onec.cd; PRES@onec.cd\nb@onec.cd") == (
        ["pres@onec.cd"],
        ["a@onec.cd", "b@onec.cd"],
    )
    # Sans Président, la première adresse du Bureau passe en destinataire.
    assert bureau_email_recipients("", "a@onec.cd, b@onec.cd") == (["a@onec.cd"], ["b@onec.cd"])
    assert bureau_email_recipients("", "") == ([], [])


@pytest.mark.asyncio(loop_scope="session")
async def test_envoi_whatsapp_sans_destinataire_refuse(app_client, admin_access_token):
    res = await app_client.post(
        "/api/v1/rapports-envoi",
        data={"titre": "Projet", "member_ids": "[]", "canaux": '["whatsapp"]'},
        headers={"Authorization": f"Bearer {admin_access_token}"},
    )
    assert res.status_code == 400
    assert "destinataire" in res.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_envoi_refuse_les_champs_json_qui_ne_sont_pas_des_listes(app_client, admin_access_token):
    res = await app_client.post(
        "/api/v1/rapports-envoi",
        data={"titre": "Projet", "member_ids": '"12"', "canaux": '["whatsapp"]'},
        headers={"Authorization": f"Bearer {admin_access_token}"},
    )
    assert res.status_code == 400
    assert "illisible" in res.json()["detail"]


@pytest.mark.asyncio(loop_scope="session")
async def test_envoi_email_un_seul_message_president_a_bureau_cc(app_client, admin_access_token, monkeypatch):
    """Bout en bout, sans réseau : le serveur SMTP est remplacé par une capture."""
    from app.api.v1.endpoints import envoi_rapports
    from app.services import mailer

    reglages = SimpleNamespace(
        email_president="president@exemple.cd",
        emails_bureau_cc="tresorier@exemple.cd; PRESIDENT@exemple.cd, rapporteur@exemple.cd",
        smtp_host="smtp.exemple.cd",
        smtp_port=465,
        email_expediteur="noreply@exemple.cd",
        smtp_password="secret",
    )

    async def faux_reglages(db, tenant_id):
        return reglages

    envoyes = []
    monkeypatch.setattr(envoi_rapports, "get_system_settings", faux_reglages)
    monkeypatch.setattr(mailer, "_send_email_message", lambda **kw: envoyes.append(kw["msg"]))
    monkeypatch.setattr(envoi_rapports, "resolve_smtp_config", lambda ns: SimpleNamespace(
        host="smtp.exemple.cd", port=465, user="noreply@exemple.cd", password="secret", sender="noreply@exemple.cd",
    ))

    res = await app_client.post(
        "/api/v1/rapports-envoi",
        data={
            "titre": "Projet FORM-2026 - Formation continue",
            "periode": "du 01/01/2026 au 29/10/2026",
            "resume": '["Entrées : 1 200,00 USD", "Solde : 900,00 USD"]',
            "message": "Pour la réunion de jeudi 🙏",
            "canaux": '["email"]',
        },
        files={"fichier": ("projet_FORM-2026.pdf", b"%PDF-1.4 test", "application/pdf")},
        headers={"Authorization": f"Bearer {admin_access_token}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["emails_envoyes"] == 3
    assert res.json()["echecs"] == []

    assert len(envoyes) == 1
    msg = envoyes[0]
    assert msg["To"] == "president@exemple.cd"
    assert msg["Cc"] == "tresorier@exemple.cd, rapporteur@exemple.cd"
    assert "Projet FORM-2026" in msg["Subject"]
    pieces = [p for p in msg.iter_attachments()]
    assert [p.get_filename() for p in pieces] == ["projet_FORM-2026.pdf"]
    corps = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Pour la réunion de jeudi" in corps and "🙏" not in corps
    assert "Solde : 900,00 USD" in corps


def test_un_mail_part_sans_emoji_et_ses_pieces_jointes_restent_intactes():
    from email.message import EmailMessage

    from app.services.mailer import retirer_emoji_du_message

    msg = EmailMessage()
    msg["Subject"] = "\U0001F4CA Rapport du jour"
    msg.set_content("Bonjour \U0001F44B\n▸ Solde : 10 USD")
    msg.add_alternative("<p>\u2705 Validé</p>", subtype="html")
    msg.add_attachment("brut \U0001F4CE".encode(), maintype="text", subtype="plain", filename="brut.txt")

    retirer_emoji_du_message(msg)

    assert msg["Subject"] == "Rapport du jour"
    assert msg.get_body(("plain",)).get_content().rstrip() == "Bonjour \n▸ Solde : 10 USD"
    assert msg.get_body(("html",)).get_content().rstrip() == "<p>Validé</p>"
    piece = next(msg.iter_attachments())
    assert piece.get_payload(decode=True) == "brut \U0001F4CE".encode()
