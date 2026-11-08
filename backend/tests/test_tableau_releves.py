"""Relevé de situation au Tableau : texte, civilité, critères, blocages."""

from __future__ import annotations

import io
from datetime import date
from types import SimpleNamespace

import openpyxl
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.modules.tableau import releves as releves_module
from app.modules.tableau import verdict as verdict_engine
from app.modules.tableau.models import TableauImport, TableauReleve, TableauReleveLot
from app.modules.tableau.releves import (
    ESPACE_MEMBRE_URL,
    appel_confraternel,
    construire_releve,
    fonction_accordee,
    html_releve,
    libelle_organisation,
    variables_whatsapp,
)
from app.modules.tableau.service import import_source_snapshot
from app.services.notifications import TABLEAU_SITUATION
from app.services.notifications import templates

REGLAGES = verdict_engine.TableauReglages()


def _membre(**extra):
    base = {
        "numero_ordre": "EC/18.00245",
        "nom": "MUKENDI",
        "prenom": "Patrick",
        "sexe": "M",
        "email": "p.mukendi@example.org",
        "telephone": "+243810000000",
        "categorie": "EC Cabinet",
        "conclusion": "NON INSCRIT",
        "sortie": None,
        "cotisation_etat": "partielle",
        "nhv": 80.0,
        "formation_etat": "insuffisant",
        "assurance": None,
        "chiffre_affaires": None,
        "raison_sociale": None,
        "associe_gerant": None,
        "date_situation": date(2026, 11, 5),
    }
    base.update(extra)
    return base


def _releve(membre, fonction=None):
    return construire_releve(
        membre, exercice="2026", reglages=REGLAGES,
        organisation="Conseil Provincial de Kinshasa", fonction_bureau=fonction,
    )


def test_ec_cabinet_non_en_regle_sans_assurance_ni_montant():
    r = _releve(_membre())
    assert r.envoyable
    assert r.sujet == "Votre situation au Tableau de l'Ordre – exercice 2026"
    assert r.corps.startswith("Cher Expert-Comptable,\nMonsieur MUKENDI Patrick – N° d'ordre : EC/18.00245\n")
    assert "arrêtée au 05/11/2026 :" in r.corps
    assert "- Cotisation : non soldée" in r.corps
    assert "- Formation (NHV) : 80 h validées sur 120 h requises" in r.corps
    assert "Assurance" not in r.corps
    assert "USD" not in r.corps
    assert "Conclusion : NON EN RÈGLE" in r.corps
    assert ESPACE_MEMBRE_URL in r.corps
    assert "Si vous avez effectué un paiement ou suivi une formation et que cela n'apparaît pas ci-dessus" in r.corps
    assert "Veuillez agréer, Monsieur, l'expression de nos salutations distinguées." in r.corps
    assert r.corps.endswith("La Commission Tableau\nONEC-RDC – Conseil Provincial de Kinshasa")
    assert "sanction" not in r.corps


def test_membre_du_bureau_en_regle_appele_par_sa_fonction():
    membre = _membre(nom="KASONGO", prenom="Esther", sexe="F", conclusion="INSCRIT",
                     cotisation_etat="payee", nhv=132.0, formation_etat="atteint")
    r = _releve(membre, fonction=fonction_accordee("Trésorier", "F"))
    assert r.corps.startswith(
        "Chère Experte-Comptable,\nMadame KASONGO Esther, Trésorière du Bureau – N° d'ordre : EC/18.00245\n"
    )
    assert "Nous avons le plaisir de vous informer" in r.corps
    assert "- Cotisation : soldée" in r.corps
    assert "Conclusion : EN RÈGLE" in r.corps
    assert ESPACE_MEMBRE_URL not in r.corps
    assert "Veuillez agréer, Madame la Trésorière, l'expression de notre haute considération." in r.corps


def test_sexe_inconnu_madame_monsieur():
    r = _releve(_membre(sexe=None))
    assert r.corps.startswith("Cher(e) Expert(e)-Comptable,\nMUKENDI Patrick – N° d'ordre : EC/18.00245\n")
    assert "Veuillez agréer, Madame, Monsieur," in r.corps


def test_societe_a_l_attention_de_l_associe_gerant():
    membre = _membre(categorie="Société", numero_ordre="SEC/20.00031", nom="CABINET ILUNGA", prenom=None,
                     sexe=None, raison_sociale="CABINET ILUNGA & ASSOCIÉS SARL", associe_gerant="ILUNGA David",
                     cotisation_etat="payee", chiffre_affaires=False, assurance=False)
    r = _releve(membre)
    assert r.sujet.startswith("Situation de votre société")
    assert r.corps.startswith(
        "À l'attention de ILUNGA David, associé gérant\n"
        "Société : CABINET ILUNGA & ASSOCIÉS SARL – N° d'ordre : SEC/20.00031\n\nMadame, Monsieur,"
    )
    assert "- Chiffre d'affaires : non déclaré" in r.corps
    assert "- Assurance : non valide" in r.corps
    assert "Formation" not in r.corps
    assert ("Si votre société a effectué un paiement, souscrit une assurance ou déclaré son chiffre d'affaires "
            "et que cela n'apparaît pas ci-dessus") in r.corps


def test_rien_ne_part_pour_un_dossier_a_deliberer_un_sorti_ou_sans_contact():
    assert _releve(_membre(conclusion="À DÉLIBÉRER")).blocage == "a_deliberer"
    assert _releve(_membre(conclusion=None)).blocage == "sans_conclusion"
    assert _releve(_membre(sortie={"libelle": "Décédé"})).blocage == "sorti"
    sans_contact = _releve(_membre(email=None, telephone=None))
    assert not sans_contact.envoyable
    assert sans_contact.blocage == "sans_contact"
    assert "Ni e-mail ni téléphone" in sans_contact.raison


def test_empreinte_ignore_la_date_mais_suit_la_situation():
    a = _releve(_membre())
    b = _releve(_membre(date_situation=date(2026, 12, 1)))
    c = _releve(_membre(cotisation_etat="payee"))
    assert a.empreinte == b.empreinte
    assert a.empreinte != c.empreinte


def test_formation_suit_les_reglages_de_la_categorie():
    reglages = verdict_engine.TableauReglages.from_dict(
        {"definitions_par_categorie": {"EC Cabinet": {"heures_formation_min": 60}}}
    )
    r = construire_releve(_membre(), exercice="2026", reglages=reglages, organisation="")
    assert "80 h validées sur 60 h requises" in r.corps


def test_cotisation_inconnue_affiche_un_tiret_sans_bloquer():
    r = _releve(_membre(cotisation_etat=None))
    assert r.envoyable
    assert "- Cotisation : -\n" in r.corps
    texte = templates.render_event(TABLEAU_SITUATION, {**variables_whatsapp(r), "organisation": "CPK"})
    assert "▸ *Cotisation :* -" in texte


def test_cotisation_ignoree_par_les_reglages_ne_bloque_pas():
    reglages = verdict_engine.TableauReglages.from_dict(
        {"criteres_par_categorie": {"EC Cabinet": {"cotisation": "ignore"}}}
    )
    r = construire_releve(_membre(cotisation_etat=None), exercice="2026", reglages=reglages, organisation="")
    assert r.envoyable and "Cotisation" not in r.corps


def test_fonction_accordee():
    assert fonction_accordee("Président(e)", "F") == "Présidente"
    assert fonction_accordee("Président(e)", "M") == "Président"
    assert fonction_accordee("Trésorier(e) adjoint", "F") == "Trésorière adjointe"
    assert fonction_accordee("Vice-président(e)", "F") == "Vice-présidente"
    assert fonction_accordee("Membre", "M") is None
    assert fonction_accordee("Président", None) is None


def test_whatsapp_et_email_reprennent_la_mise_en_forme_existante():
    r = _releve(_membre())
    texte = templates.render_event(TABLEAU_SITUATION, variables_whatsapp(r))
    assert texte.startswith("*ONEC-RDC – Conseil Provincial de Kinshasa* · ONEC Smart\n━━━━━━━━━━━━━━\n*SITUATION AU TABLEAU*\n_Exercice 2026 · N° d'ordre EC/18.00245_")
    assert "Cher Expert-Comptable,\nMonsieur MUKENDI Patrick – N° d'ordre" in texte
    assert texte.endswith("_La Commission Tableau – ONEC-RDC – Conseil Provincial de Kinshasa_")
    assert "▸ *Cotisation :* non soldée" in texte
    assert "Conclusion : *NON EN RÈGLE*" in texte
    assert ESPACE_MEMBRE_URL in texte
    page = html_releve(r)
    assert "Accéder à mon espace membre" in page and "Conclusion : NON EN RÈGLE" in page
    assert "ONEC-RDC – Conseil Provincial de Kinshasa" in page


# ── Bout en bout : Base du Tableau → aperçu → envoi → doublon ────────────────


def _xlsx(headers, rows) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest_asyncio.fixture
async def base_releves(db_session, test_admin_user):
    org = test_admin_user.organisation_id
    pp = _xlsx(
        ["N° Ordre", "Nom", "Statut", "Sexe", "Email", "Actif"],
        [
            ["EC/32.96070", "TSHIBANDA Rose", "en cabinet", "F", "rose@example.org", "Oui"],
            ["EC/32.96071", "LUMBU Marc", "en cabinet", "M", None, "Oui"],
        ],
    )
    await import_source_snapshot(db_session, test_admin_user, org, "pp-2032.xlsx", pp, "personnes_physiques", "2032", date(2032, 6, 1))
    # Inscrits en 2032 : nouveaux, la formation ne leur est pas demandée ; la
    # cotisation est écartée par les réglages. La conclusion est donc tranchée
    # (En règle) sans notes de débit.
    for ligne in (await db_session.execute(
        select(TableauImport).where(TableauImport.organisation_id == org, TableauImport.exercice == "2032")
    )).scalars().all():
        ligne.metadata_json = {**(ligne.metadata_json or {}), "reglages": {"criteres_par_categorie": {"EC Cabinet": {"cotisation": "ignore"}}}}
    await db_session.flush()
    yield org
    await db_session.rollback()
    await db_session.execute(delete(TableauReleve).where(TableauReleve.numero_ordre.like("%.9607%")))
    await db_session.execute(delete(TableauReleveLot).where(TableauReleveLot.exercice == "2032"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_apercu_puis_envoi_puis_doublon(db_session, test_admin_user, base_releves, monkeypatch):
    envoyes = _faux_smtp(monkeypatch)

    apercu = await releves_module.apercu(db_session, base_releves, "2032", "ec/32.96070")
    assert apercu["numero_ordre"] == "EC/32.96070"
    assert apercu["envoyable"], apercu["raison"]
    assert apercu["corps"].startswith("Chère Experte-Comptable,\nMadame TSHIBANDA Rose – N° d'ordre")
    assert "Formation (NHV) : non requise (nouveau membre)" in apercu["corps"]
    assert "Cotisation" not in apercu["corps"]
    assert "Conclusion : EN RÈGLE" in apercu["corps"]
    assert apercu["emails"] == ["rose@example.org"]

    premier = await releves_module.envoyer(
        db_session, test_admin_user, base_releves, exercice="2032", numero_ordre="EC/32.96070", canaux=["email"],
    )
    assert [r["statut"] for r in premier["resultats"]] == ["envoye"]
    assert envoyes and envoyes[0]["to_emails"] == ["rose@example.org"]

    second = await releves_module.envoyer(
        db_session, test_admin_user, base_releves, exercice="2032", numero_ordre="EC/32.96070", canaux=["email"],
    )
    assert second["resultats"][0]["statut"] == "deja_envoye"
    assert len(envoyes) == 1

    derniers = await releves_module.derniers_envois(db_session, base_releves, "2032")
    assert derniers["EC/32.96070"]["canaux"] == ["email"]


@pytest.mark.asyncio
async def test_membre_inconnu(db_session, base_releves):
    with pytest.raises(HTTPException) as exc:
        await releves_module.apercu(db_session, base_releves, "2032", "EC/99.99999")
    assert exc.value.status_code == 404


def _faux_smtp(monkeypatch):
    envoyes: list[dict] = []

    async def faux_envoi(fn, /, **kwargs):
        envoyes.append(kwargs)

    monkeypatch.setattr(releves_module, "resolve_smtp_config", lambda ns: type("Cfg", (), {
        "host": "smtp", "port": 465, "user": "u", "password": "p", "sender": "tableau@example.org"})())
    monkeypatch.setattr(releves_module, "send_in_thread", faux_envoi)
    monkeypatch.setattr(releves_module, "PAUSE_ENTRE_MEMBRES_S", 0)
    return envoyes


@pytest.mark.asyncio
async def test_envoi_groupe_par_selection(db_session, async_session, test_admin_user, base_releves, monkeypatch):
    envoyes = _faux_smtp(monkeypatch)
    org = base_releves
    numeros = ["EC/32.96070", "EC/32.96071"]

    resume = await releves_module.preparer_selection(
        db_session, org, exercice="2032", numeros=numeros, filtres=None, canaux=["email"],
    )
    assert resume["total"] == 2
    assert resume["envoyables"] == 1
    assert resume["bloques"] == [{"code": "sans_contact", "libelle": "Ni e-mail ni téléphone", "nombre": 1}]
    assert resume["par_canal"]["email"] == {"joignables": 1, "deja_envoye": 0}

    lot = await releves_module.creer_lot(
        db_session, test_admin_user, org, exercice="2032", numeros=numeros, filtres=None, canaux=["email"], renvoyer=False,
    )
    assert lot.numeros == ["EC/32.96070"] and lot.total == 1
    await releves_module.traiter_lot(lot.id, org, session_factory=async_session)
    fini = releves_module.lot_payload(await releves_module.lire_lot(db_session, org, lot.id))
    assert (fini["statut"], fini["traites"], fini["envoyes"], fini["echecs"]) == ("termine", 1, 1, 0)
    assert len(envoyes) == 1

    # Relancé sur la même sélection : la situation n'a pas changé, rien ne repart.
    second = await releves_module.creer_lot(
        db_session, test_admin_user, org, exercice="2032", numeros=numeros, filtres=None, canaux=["email"], renvoyer=False,
    )
    await releves_module.traiter_lot(second.id, org, session_factory=async_session)
    refait = releves_module.lot_payload(await releves_module.lire_lot(db_session, org, second.id))
    assert (refait["envoyes"], refait["deja_envoyes"]) == (0, 1)
    assert len(envoyes) == 1


@pytest.mark.asyncio
async def test_envoi_groupe_par_filtre(db_session, test_admin_user, base_releves, monkeypatch):
    _faux_smtp(monkeypatch)
    resume = await releves_module.preparer_selection(
        db_session, base_releves, exercice="2032", numeros=None,
        filtres={"recherche": "96070", "situation": "en_exercice"}, canaux=["email"],
    )
    assert resume["total"] == 1 and resume["envoyables"] == 1, resume
    assert resume["exemple"]["corps"].startswith("Chère Experte-Comptable,")


@pytest.mark.asyncio
async def test_lot_sans_destinataire_refuse(db_session, test_admin_user, base_releves):
    with pytest.raises(HTTPException) as exc:
        await releves_module.creer_lot(
            db_session, test_admin_user, base_releves, exercice="2032", numeros=["EC/32.96071"],
            filtres=None, canaux=["email"], renvoyer=False,
        )
    assert exc.value.status_code == 409


def test_appel_confraternel_et_libelle_de_l_ordre():
    assert appel_confraternel("M", "EC Cabinet") == "Cher Expert-Comptable,"
    assert appel_confraternel("F", "EC Salarié") == "Chère Experte-Comptable,"
    assert appel_confraternel("F", "Stagiaire") == "Chère Experte-Comptable stagiaire,"
    assert appel_confraternel(None, "EC Cabinet") == "Cher(e) Expert(e)-Comptable,"
    assert libelle_organisation("Conseil Provincial de Kinshasa") == "ONEC-RDC – Conseil Provincial de Kinshasa"
    assert libelle_organisation("ONEC-RDC Kinshasa") == "ONEC-RDC Kinshasa"
    assert libelle_organisation("") == "ONEC-RDC"


def test_couleurs_de_l_email_selon_la_conclusion():
    non = html_releve(_releve(_membre()))
    assert "background:#7f1d2d" in non and "#1e40af" not in non.split("Votre situation")[0]
    assert "Conclusion : NON EN RÈGLE – Exercice 2026" in non  # texte d'aperçu de la boîte de réception
    oui = html_releve(_releve(_membre(conclusion="INSCRIT", cotisation_etat="payee", nhv=130.0, formation_etat="atteint")))
    assert "background:#1e40af" in oui and "#7f1d2d" not in oui
    assert "#0f7b62" not in non and "#0f7b62" not in oui


def test_conformite_de_chaque_critere():
    r = _releve(_membre(cotisation_etat=None))
    assert r.criteres == [("Cotisation", "-"), ("Formation (NHV)", "80 h validées sur 120 h requises")]
    assert r.conformites == [None, False]


@pytest.mark.asyncio
async def test_panne_whatsapp_garde_l_email_parti_au_journal(monkeypatch):
    """L'e-mail est parti, WhatsApp lève : l'entrée de l'e-mail reste, WhatsApp est en échec."""

    async def faux_envoi(fn, /, **kwargs):
        return None

    async def whatsapp_en_panne(*args, **kwargs):
        raise RuntimeError("passerelle injoignable")

    class FausseSession:
        annulations = 0

        async def rollback(self):
            self.annulations += 1

    monkeypatch.setattr(releves_module, "send_in_thread", faux_envoi)
    monkeypatch.setattr(releves_module, "notify_whatsapp", whatsapp_en_panne)
    db = FausseSession()
    moyens = releves_module.Moyens(smtp=SimpleNamespace(host="h", port=465, user="u", password="p", sender="s"),
                                   whatsapp=SimpleNamespace(enabled=True))
    resultats, journal = await releves_module._envoyer_releve(
        db, _releve(_membre()), ["email", "whatsapp"], deja={}, renvoyer=False, moyens=moyens,
        organisation_id=1, exercice="2026", user_id=None,
    )
    assert [(j.canal, j.statut) for j in journal] == [("email", "envoye"), ("whatsapp", "echec")]
    assert "passerelle injoignable" in journal[1].erreur
    assert [r["statut"] for r in resultats] == ["envoye", "echec"]
    assert db.annulations == 1
