"""Convocation d'une réunion préparée en brouillon de remboursement.

Ce que ces tests tiennent :
- l'invitation .ics porte l'heure de Kinshasa convertie en UTC, ou la journée
  entière quand l'heure manque ;
- un message par destinataire, chacun avec l'invitation jointe ;
- l'adresse proposée vient de la dernière convocation, sinon de l'expert, sinon
  du membre du service portant ce nom ;
- seuls les envois réussis sont tracés, et l'enregistrement du formulaire
  n'efface pas cette trace ;
- sans SMTP, l'envoi est refusé au lieu d'échouer en silence ;
- la liste signée se dépose sur le brouillon, remplace la précédente, et
  devient une seule fois annexe de la réquisition ; un brouillon abandonné
  emporte son scan, un brouillon finalisé le laisse à l'annexe.
"""

from __future__ import annotations

import io
import os
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select

from app.api.v1.endpoints import remboursements_transport as rt
from app.models.commission_member import CommissionMember
from app.models.expert_comptable import ExpertComptable
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.requisition_annexe import RequisitionAnnexe
from app.models.service import Service
from app.models.user import User
from app.schemas.remboursement_transport import (
    ConvocationDestinataire,
    ConvocationEnvoi,
    PiecesReunionAnnexer,
    RemboursementTransportBrouillonSave,
)
from app.services import convocation_reunion as cr
from app.services.email_config import SMTPConfig

SMTP = SMTPConfig(host="smtp.test", port=465, user="bureau@onec.test", password="x", sender="bureau@onec.test")


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _reunion(**kw) -> cr.Reunion:
    base = dict(
        titre="Réunion du Bureau",
        nature="Session ordinaire",
        lieu="Siège, salle A",
        jour=date(2026, 11, 12),
        heure_debut=time(10, 0),
        heure_fin=time(12, 30),
        travaux=["Budget 2027", "Divers"],
        service="BUR - Bureau",
    )
    base.update(kw)
    return cr.Reunion(**base)


def test_ics_heure_de_kinshasa_en_utc():
    ics = cr.construire_ics(
        _reunion(),
        uid="u1@onec",
        organisateur="bureau@onec.test",
        sequence=2,
        destinataire=("Jean Mukendi", "jean@ex.com"),
        maintenant=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    assert "DTSTART:20261112T090000Z" in ics
    assert "DTEND:20261112T113000Z" in ics
    assert "LOCATION:Siège\\, salle A" in ics
    assert "METHOD:REQUEST" in ics and "SEQUENCE:2" in ics and "STATUS:CONFIRMED" in ics
    assert "RSVP=TRUE:mailto:jean@ex.com" in ics
    assert all(len(l.encode("utf-8")) <= 75 for l in ics.split("\r\n"))


def test_ics_sans_heure_est_sur_la_journee():
    ics = cr.construire_ics(_reunion(heure_debut=None, heure_fin=None), uid="u2@onec", organisateur="b@o.t")
    assert "DTSTART;VALUE=DATE:20261112" in ics
    assert "DTEND;VALUE=DATE:20261113" in ics


def test_un_horaire_invalide_est_refuse_plutot_que_transforme_en_journee():
    contenu = {
        "formData": {
            "date_reunion": "2026-11-12",
            "heure_debut": "25:00",
            "heure_fin": "09:00",
        }
    }
    with pytest.raises(ValueError, match="heure de début"):
        cr.reunion_depuis_brouillon(contenu, "Bureau")


def test_un_message_par_destinataire_avec_invitation(monkeypatch):
    envoyes = []
    monkeypatch.setattr(cr, "_send_email_message", lambda **kw: envoyes.append(kw["msg"]))
    echecs = cr.envoyer_convocations(
        _reunion(), [("Jean", "jean@ex.com"), ("Marie", "marie@ex.com")],
        smtp=SMTP, message="Merci d'être ponctuels.", organisation="ONEC",
    )
    assert echecs == []
    assert [m["To"] for m in envoyes] == ["jean@ex.com", "marie@ex.com"]
    for m in envoyes:
        pieces = list(m.iter_attachments())
        assert [p.get_filename() for p in pieces] == ["convocation.ics"]
        assert pieces[0].get_param("method") == "REQUEST"
    texte = envoyes[0].get_body(("plain",)).get_content()
    assert "Bonjour Jean" in texte and "1. Budget 2027" in texte and "ponctuels" in texte


async def _contexte(db):
    org = Organisation(nom="Convocations", slug=f"cv-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    service = Service(organisation_id=org.id, code=f"B{_suffix()[:6]}", libelle="Bureau")
    user = User(id=uuid.uuid4(), email=f"{_suffix()}@ex.com", role="user", organisation_id=org.id,
                prenom="Awa", nom="Secrétaire")
    db.add_all([service, user])
    await db.flush()
    expert = ExpertComptable(numero_ordre=f"EC{_suffix()}", nom_denomination="Cabinet Kasa", email="kasa@ex.com")
    membre = CommissionMember(service_id=service.id, full_name="Jean  Mukendi", email="jean@ex.com")
    db.add_all([expert, membre])
    await db.commit()
    return org, service, user, expert


@pytest.fixture
def acces(monkeypatch):
    async def oui(*_a, **_k):
        return True

    monkeypatch.setattr(rt, "can_view_all_services", oui)


def _contenu(expert_id):
    return {
        "formData": {"type_reunion": "bureau", "date_reunion": "2026-11-12", "heure_debut": "10:00", "lieu": "Siège"},
        "participants": [
            {"nom": "jean mukendi", "titre_fonction": "Président"},
            {"nom": "Cabinet Kasa", "titre_fonction": "Invité", "expert_comptable_id": str(expert_id)},
            {"nom": "Paul Inconnu", "titre_fonction": "Membre"},
        ],
        "assistants": [],
    }


@pytest.mark.asyncio
async def test_convocation_propose_envoie_et_trace(db_session, acces, monkeypatch):
    org, service, user, expert = await _contexte(db_session)
    brouillon = await rt.create_brouillon(
        payload=RemboursementTransportBrouillonSave(service_id=service.id, contenu=_contenu(expert.id)),
        user=user, tenant_id=org.id, db=db_session,
    )

    proposes = await rt.list_destinataires_convocation(
        brouillon_id=str(brouillon.id), user=user, tenant_id=org.id, db=db_session,
    )
    assert [(d.email, d.source) for d in proposes] == [
        ("jean@ex.com", "membre"), ("kasa@ex.com", "expert"), (None, None),
    ]

    appels = []

    def faux_envoi(reunion, destinataires, **kw):
        appels.append((reunion, destinataires, kw))
        return [("kasa@ex.com", "550 boîte pleine")]

    async def faux_settings(*_a, **_k):
        return None

    monkeypatch.setattr(rt, "envoyer_convocations", faux_envoi)
    monkeypatch.setattr(rt, "get_system_settings", faux_settings)
    monkeypatch.setattr(rt, "resolve_smtp_config", lambda _ns: SMTP)

    envoi = ConvocationEnvoi(destinataires=[*proposes[:2], ConvocationDestinataire(nom="Paul Inconnu", email="")])
    res = await rt.envoyer_convocation(
        brouillon_id=str(brouillon.id), payload=envoi, user=user, tenant_id=org.id, db=db_session,
    )
    assert res.envoyes == 1
    assert [e.email for e in res.echecs] == ["kasa@ex.com"]
    reunion, destinataires, kw = appels[0]
    assert reunion.jour == date(2026, 11, 12) and reunion.heure_debut == time(10, 0)
    assert destinataires == [("jean mukendi", "jean@ex.com"), ("Cabinet Kasa", "kasa@ex.com")]
    assert kw["uid"] == f"{brouillon.id}@onec"
    assert kw["sequence"] == 1
    trace = res.contenu["convocation"]
    assert [d["email"] for d in trace["destinataires"]] == ["jean@ex.com"]
    assert trace["envoyee_par"] == "Awa Secrétaire"
    assert trace["sequence"] == 1

    # Le formulaire réenregistré ne renvoie pas la trace : elle reste.
    contenu_falsifie = _contenu(expert.id)
    contenu_falsifie["convocation"] = {"uid": "injecte", "destinataires": []}
    contenu_falsifie["pieces"] = {"pv": {"file_path": "/uploads/../../etc/passwd"}}
    maj = await rt.update_brouillon(
        brouillon_id=str(brouillon.id),
        payload=RemboursementTransportBrouillonSave(service_id=service.id, contenu=contenu_falsifie),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert maj.contenu["convocation"]["destinataires"] == trace["destinataires"]
    assert maj.contenu["convocation"]["uid"] == f"{brouillon.id}@onec"
    assert "pieces" not in maj.contenu


@pytest.mark.asyncio
async def test_convocation_refusee_sans_smtp_ou_adresse_invalide(db_session, acces, monkeypatch):
    org, service, user, expert = await _contexte(db_session)
    brouillon = await rt.create_brouillon(
        payload=RemboursementTransportBrouillonSave(service_id=service.id, contenu=_contenu(expert.id)),
        user=user, tenant_id=org.id, db=db_session,
    )

    async def faux_settings(*_a, **_k):
        return None

    monkeypatch.setattr(rt, "get_system_settings", faux_settings)
    monkeypatch.setattr(rt, "resolve_smtp_config", lambda _ns: None)

    with pytest.raises(HTTPException) as exc:
        await rt.envoyer_convocation(
            brouillon_id=str(brouillon.id),
            payload=ConvocationEnvoi(destinataires=[ConvocationDestinataire(nom="jean mukendi", email="pas-une-adresse")]),
            user=user, tenant_id=org.id, db=db_session,
        )
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await rt.envoyer_convocation(
            brouillon_id=str(brouillon.id),
            payload=ConvocationEnvoi(destinataires=[ConvocationDestinataire(nom="jean mukendi", email="x@ex.com")]),
            user=user, tenant_id=org.id, db=db_session,
        )
    assert exc.value.status_code == 409

    # L'endpoint SMTP ne sert pas de relais vers une personne absente de la réunion.
    monkeypatch.setattr(rt, "resolve_smtp_config", lambda _ns: SMTP)
    with pytest.raises(HTTPException) as exc:
        await rt.envoyer_convocation(
            brouillon_id=str(brouillon.id),
            payload=ConvocationEnvoi(destinataires=[ConvocationDestinataire(nom="Personne injectée", email="x@ex.com")]),
            user=user, tenant_id=org.id, db=db_session,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_creation_brouillon_ignore_les_metadonnees_serveur(db_session, acces):
    org, service, user, expert = await _contexte(db_session)
    contenu = _contenu(expert.id)
    contenu["convocation"] = {"uid": "faux"}
    contenu["pieces"] = {"pv": {"file_path": "/uploads/../../etc/passwd"}}
    brouillon = await rt.create_brouillon(
        payload=RemboursementTransportBrouillonSave(service_id=service.id, contenu=contenu),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert "convocation" not in brouillon.contenu
    assert "pieces" not in brouillon.contenu


def test_un_chemin_upload_ne_peut_pas_sortir_du_stockage(tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "UPLOAD_ROOT", str(tmp_path))
    assert rt._remboursement_pdf_fs_path("/uploads/../../etc/passwd") == ""


# ---------------------------------------------------------------------------
# Liste de présence signée : imprimée, signée en séance, scannée, déposée sur
# le brouillon, puis annexée à la réquisition à la création du remboursement.
# ---------------------------------------------------------------------------


def _fichier(nom: str, contenu: bytes, content_type: str) -> UploadFile:
    return UploadFile(filename=nom, file=io.BytesIO(contenu), headers={"content-type": content_type})


@pytest.mark.asyncio
async def test_liste_signee_deposee_puis_annexee_une_seule_fois(db_session, acces, tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "UPLOAD_ROOT", str(tmp_path))
    org, service, user, expert = await _contexte(db_session)
    brouillon = await rt.create_brouillon(
        payload=RemboursementTransportBrouillonSave(service_id=service.id, contenu=_contenu(expert.id)),
        user=user, tenant_id=org.id, db=db_session,
    )
    tenant_uuid = str(uuid.uuid4())

    with pytest.raises(HTTPException) as exc:
        await rt.deposer_piece_reunion(
            brouillon_id=str(brouillon.id), kind="liste_presence",
            file=_fichier("liste.docx", b"x", "application/msword"),
            user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
        )
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        await rt.deposer_piece_reunion(
            brouillon_id=str(brouillon.id), kind="liste_presence",
            file=_fichier("faux.pdf", b"ceci n'est pas un PDF", "application/pdf"),
            user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
        )
    assert exc.value.status_code == 400

    premier = await rt.deposer_piece_reunion(
        brouillon_id=str(brouillon.id), kind="liste_presence",
        file=_fichier("scan001.pdf", b"%PDF-1 v1", "application/pdf"),
        user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
    )
    ancien = rt._remboursement_pdf_fs_path(premier.contenu["pieces"]["liste_presence"]["file_path"])
    # Un second scan remplace le premier, qui quitte le disque.
    depose = await rt.deposer_piece_reunion(
        brouillon_id=str(brouillon.id), kind="liste_presence",
        file=_fichier("scan002.pdf", b"%PDF-1 v2", "application/pdf"),
        user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
    )
    assert not os.path.exists(ancien)
    piece = depose.contenu["pieces"]["liste_presence"]
    chemin = rt._remboursement_pdf_fs_path(piece["file_path"])
    assert open(chemin, "rb").read() == b"%PDF-1 v2"
    assert "scan002" not in piece["file_path"]

    # Le formulaire réenregistré ne connaît pas les pièces : elles restent.
    maj = await rt.update_brouillon(
        brouillon_id=str(brouillon.id),
        payload=RemboursementTransportBrouillonSave(service_id=service.id, contenu=_contenu(expert.id)),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert maj.contenu["pieces"]["liste_presence"]["file_path"] == piece["file_path"]

    req = Requisition(
        organisation_id=org.id, service_id=service.id,
        numero_requisition=f"REQ-{_suffix()}", reference_numero=f"REF-{_suffix()}",
        objet="Transport", mode_paiement="cash", type_requisition="remboursement_transport",
        status="BROUILLON", montant_total=Decimal("40"), devise="USD",
    )
    db_session.add(req)
    await db_session.commit()

    annexes = await rt.annexer_pieces_reunion(
        brouillon_id=str(brouillon.id), payload=PiecesReunionAnnexer(requisition_id=req.id),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert [a.filename for a in annexes] == ["Liste de présence signée.pdf"]
    assert annexes[0].file_path == piece["file_path"]
    rejoue = await rt.annexer_pieces_reunion(
        brouillon_id=str(brouillon.id), payload=PiecesReunionAnnexer(requisition_id=req.id),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert rejoue == []
    total = await db_session.scalar(
        select(func.count()).select_from(RequisitionAnnexe).where(RequisitionAnnexe.requisition_id == req.id)
    )
    assert total == 1

    # Le brouillon disparaît à la création ; le fichier annexé, lui, reste.
    await rt.delete_brouillon(brouillon_id=str(brouillon.id), user=user, tenant_id=org.id, db=db_session)
    assert os.path.exists(chemin)


@pytest.mark.asyncio
async def test_brouillon_abandonne_emporte_son_scan(db_session, acces, tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "UPLOAD_ROOT", str(tmp_path))
    org, service, user, expert = await _contexte(db_session)
    brouillon = await rt.create_brouillon(
        payload=RemboursementTransportBrouillonSave(service_id=service.id, contenu=_contenu(expert.id)),
        user=user, tenant_id=org.id, db=db_session,
    )
    depose = await rt.deposer_piece_reunion(
        brouillon_id=str(brouillon.id), kind="pv",
        file=_fichier("pv.jpg", b"\xff\xd8\xffjpeg", "image/jpeg"),
        user=user, tenant_id=org.id, tenant_uuid=str(uuid.uuid4()), db=db_session,
    )
    chemin = rt._remboursement_pdf_fs_path(depose.contenu["pieces"]["pv"]["file_path"])
    assert os.path.exists(chemin)
    await rt.delete_brouillon(brouillon_id=str(brouillon.id), user=user, tenant_id=org.id, db=db_session)
    assert not os.path.exists(chemin)


@pytest.mark.asyncio
async def test_pv_et_liste_joints_a_un_remboursement_deja_paye(db_session, acces, tmp_path, monkeypatch):
    monkeypatch.setattr(rt, "UPLOAD_ROOT", str(tmp_path))
    org, service, user, _ = await _contexte(db_session)
    req = Requisition(
        organisation_id=org.id, service_id=service.id,
        numero_requisition=f"REQ-{_suffix()}", reference_numero=f"REF-{_suffix()}",
        objet="Transport", mode_paiement="cash", type_requisition="remboursement_transport",
        status="PAYEE", montant_total=Decimal("40"), devise="USD",
    )
    db_session.add(req)
    await db_session.flush()
    remboursement = rt.RemboursementTransport(
        organisation_id=org.id, numero_remboursement=f"REM-{_suffix()}", instance="ONEC",
        type_reunion="bureau", nature_reunion="Session", lieu="Siège",
        date_reunion=datetime(2026, 3, 5, tzinfo=timezone.utc), montant_total=Decimal("40"),
        requisition_id=req.id,
    )
    db_session.add(remboursement)
    db_session.add(RequisitionAnnexe(
        organisation_id=org.id, requisition_id=req.id, file_path="/uploads/x/facture.pdf",
        filename="facture.pdf", file_type="application/pdf", file_size=3,
    ))
    await db_session.commit()
    rid = str(remboursement.id)
    tenant_uuid = str(uuid.uuid4())

    vides = await rt.list_pieces_remboursement(remboursement_id=rid, user=user, tenant_id=org.id, db=db_session)
    assert vides == {"liste_presence": None, "pv": None}

    with pytest.raises(HTTPException) as exc:
        await rt.deposer_piece_remboursement(
            remboursement_id=rid, kind="pv", file=_fichier("pv.pdf", b"pas un PDF", "application/pdf"),
            user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
        )
    assert exc.value.status_code == 400

    premier = await rt.deposer_piece_remboursement(
        remboursement_id=rid, kind="pv", file=_fichier("scan.pdf", b"%PDF-1 v1", "application/pdf"),
        user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
    )
    assert premier["liste_presence"] is None
    assert premier["pv"]["filename"] == "Procès-verbal.pdf"
    assert premier["pv"]["version"] == 1
    assert premier["pv"]["content_sha256"]
    # Un PV remplacé reste au dossier : la réquisition est payée, rien n'en sort.
    second = await rt.deposer_piece_remboursement(
        remboursement_id=rid, kind="pv", file=_fichier("scan2.pdf", b"%PDF-1 v2", "application/pdf"),
        user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
    )
    assert second["pv"]["annexe_id"] != premier["pv"]["annexe_id"]
    assert second["pv"]["version"] == 2
    assert second["pv"]["supersedes_id"] == premier["pv"]["annexe_id"]
    assert second["pv"]["source"] == "REMBOURSEMENT_POSTERIEUR"
    assert os.path.exists(rt._remboursement_pdf_fs_path(premier["pv"]["file_path"]))
    await rt.deposer_piece_remboursement(
        remboursement_id=rid, kind="liste_presence", file=_fichier("liste.png", b"\x89PNG\r\n\x1a\nx", "image/png"),
        user=user, tenant_id=org.id, tenant_uuid=tenant_uuid, db=db_session,
    )

    noms = (await db_session.scalars(
        select(RequisitionAnnexe.filename).where(RequisitionAnnexe.requisition_id == req.id)
    )).all()
    assert sorted(noms) == ["Liste de présence signée.png", "Procès-verbal.pdf", "Procès-verbal.pdf", "facture.pdf"]
    await db_session.refresh(req)
    assert req.status == "PAYEE"

    reponse = await rt.voir_piece_remboursement(remboursement_id=rid, kind="pv", user=user, tenant_id=org.id, db=db_session)
    assert open(reponse.path, "rb").read() == b"%PDF-1 v2"

    with pytest.raises(HTTPException) as exc:
        await rt.list_pieces_remboursement(remboursement_id=str(uuid.uuid4()), user=user, tenant_id=org.id, db=db_session)
    assert exc.value.status_code == 404
