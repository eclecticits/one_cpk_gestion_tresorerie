"""Sorties du Tableau : décès, démission, radiation, omission, cessation d'une société.

Une sortie n'est pas une catégorie : le membre garde la sienne (un expert
décédé reste « EC Cabinet »). Elle tient au membre — conseil et n° d'ordre —
et non à un import : un réimport ne la fait pas disparaître. Elle vaut pour
les exercices dont l'année est au moins celle de sa date d'effet ; les
exercices antérieurs gardent le membre tel qu'il était.

Effets : le membre sorti n'est plus jugé (pas de conclusion), il quitte la base
« en exercice », l'analyse et le rapport. Sa cotisation n'est plus due après la
date d'effet ; les arriérés antérieurs restent lisibles et le Bureau décide
s'il les abandonne.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.user import User

from .audit import record_tableau_audit
from .models import TableauSortieMembre

SITUATIONS_PP = {"DECEDE", "DEMISSIONNAIRE", "RADIE", "OMIS"}
SITUATIONS_PM = {"CESSE"}
MOTIFS_CESSATION = {"DISSOLUTION", "FUSION", "RADIATION"}

LIBELLES_SITUATION = {
    "DECEDE": "Décédé",
    "DEMISSIONNAIRE": "Démissionnaire",
    "RADIE": "Radié",
    "OMIS": "Omis",
    "CESSE": "A cessé d'exister",
}
LIBELLES_MOTIF = {
    "DISSOLUTION": "Dissolution-liquidation",
    "FUSION": "Fusion-absorption",
    "RADIATION": "Radiation",
}

PIECE_EXT = {".pdf", ".jpg", ".jpeg", ".png"}
PIECE_TYPES = {"application/pdf", "image/jpeg", "image/jpg", "image/png"}
PIECE_TAILLE_MAX = 5 * 1024 * 1024

_UPLOAD_PAR_DEFAUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads"))
UPLOAD_ROOT = os.path.abspath(settings.upload_dir) if settings.upload_dir else _UPLOAD_PAR_DEFAUT


def cle_numero(numero: str | None) -> str | None:
    """Comme `_norm_numero_ordre` du service : majuscules, sans aucun espace."""
    if not numero:
        return None
    compact = "".join(str(numero).strip().upper().split())
    return compact or None


def est_morale(categorie: str | None) -> bool:
    return categorie in ("Société", "SEC")


def _date_fr(valeur: date) -> str:
    return valeur.strftime("%d/%m/%Y")


def libelle_sortie(sortie: TableauSortieMembre) -> str:
    """« Décédé le 12/03/2026 à Kinshasa », « A cessé d'exister le … (fusion-absorption par X) »."""
    texte = f"{LIBELLES_SITUATION.get(sortie.situation, sortie.situation)} le {_date_fr(sortie.date_effet)}"
    if sortie.situation == "DECEDE" and sortie.lieu_deces:
        texte += f" à {sortie.lieu_deces}"
    if sortie.situation == "CESSE" and sortie.motif_cessation:
        motif = LIBELLES_MOTIF.get(sortie.motif_cessation, sortie.motif_cessation).lower()
        if sortie.motif_cessation == "FUSION" and sortie.societe_absorbante:
            motif += f" par {sortie.societe_absorbante}"
        texte += f" ({motif})"
    if sortie.situation in ("RADIE", "OMIS") and sortie.reference_decision:
        texte += f" — décision {sortie.reference_decision}"
    return texte


def sortie_payload(sortie: TableauSortieMembre | None) -> dict[str, Any] | None:
    if sortie is None:
        return None
    return {
        "id": sortie.id,
        "situation": sortie.situation,
        "libelle": libelle_sortie(sortie),
        "date_effet": sortie.date_effet,
        "lieu_deces": sortie.lieu_deces,
        "motif_cessation": sortie.motif_cessation,
        "societe_absorbante": sortie.societe_absorbante,
        "reference_decision": sortie.reference_decision,
        "observation": sortie.observation,
        "piece_path": sortie.piece_path,
        "piece_nom": sortie.piece_nom,
    }


def _texte(valeur: str | None, longueur: int) -> str | None:
    texte = (valeur or "").strip()
    return texte[:longueur] or None


def _refus(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


async def _enregistrer_piece(piece: UploadFile, tenant_uuid: str, numero: str) -> tuple[str, str]:
    nom = piece.filename or "piece"
    ext = os.path.splitext(nom)[1].lower()
    if ext not in PIECE_EXT:
        raise _refus("Pièce justificative : PDF, JPG ou PNG uniquement.")
    if piece.content_type and piece.content_type.lower() not in PIECE_TYPES:
        raise _refus("Pièce justificative : PDF, JPG ou PNG uniquement.")
    contenu = await piece.read()
    if len(contenu) > PIECE_TAILLE_MAX:
        raise _refus("Pièce justificative trop volumineuse (5 Mo au plus).")
    maintenant = datetime.now(timezone.utc)
    segment = f"tableau-sorties/{maintenant.year:04d}/{maintenant.month:02d}"
    dossier = os.path.join(UPLOAD_ROOT, "tenants", tenant_uuid, *segment.split("/"))
    os.makedirs(dossier, exist_ok=True)
    sur = "".join(c if c.isalnum() else "-" for c in numero).strip("-") or "membre"
    fichier = f"{sur}-{uuid.uuid4().hex}{ext}"
    with open(os.path.join(dossier, fichier), "wb") as sortie:
        sortie.write(contenu)
    return f"/uploads/tenants/{tenant_uuid}/{segment}/{fichier}", nom[:255]


async def declarer_sortie(
    db: AsyncSession,
    user: User,
    organisation_id: int,
    tenant_uuid: str,
    *,
    numero_ordre: str,
    nom: str,
    categorie: str | None,
    situation: str,
    date_effet: date,
    lieu_deces: str | None = None,
    motif_cessation: str | None = None,
    societe_absorbante: str | None = None,
    reference_decision: str | None = None,
    observation: str | None = None,
    piece: UploadFile | None = None,
) -> TableauSortieMembre:
    """Déclare ou met à jour la sortie d'un membre (une seule par membre)."""
    cle = cle_numero(numero_ordre)
    if not cle:
        raise _refus("Un membre sans n° d'ordre ne peut pas être déclaré sorti : corrigez d'abord son numéro.")
    morale = est_morale(categorie)
    permises = SITUATIONS_PM if morale else SITUATIONS_PP
    if situation not in permises:
        raise _refus(
            "Une société ne peut que « cesser d'exister »." if morale
            else "Situation inconnue pour une personne physique."
        )
    if date_effet > date.today():
        raise _refus("La date ne peut pas être dans le futur.")
    lieu = _texte(lieu_deces, 200)
    reference = _texte(reference_decision, 200)
    absorbante = _texte(societe_absorbante, 300)
    motif = (motif_cessation or "").strip().upper() or None
    if situation == "DECEDE" and not lieu:
        raise _refus("Le lieu du décès est obligatoire.")
    if situation in ("RADIE", "OMIS") and not reference:
        raise _refus("La référence de la décision est obligatoire.")
    if situation == "CESSE":
        if motif not in MOTIFS_CESSATION:
            raise _refus("Précisez le motif : dissolution-liquidation, fusion-absorption ou radiation.")
        if motif == "FUSION" and not absorbante:
            raise _refus("Indiquez la société absorbante.")

    sortie = (await db.execute(
        select(TableauSortieMembre).where(
            TableauSortieMembre.organisation_id == organisation_id,
            TableauSortieMembre.numero_ordre == cle,
        )
    )).scalar_one_or_none()
    nouvelle = sortie is None
    if nouvelle:
        sortie = TableauSortieMembre(organisation_id=organisation_id, numero_ordre=cle, created_by=user.id)
        db.add(sortie)
    sortie.nom = _texte(nom, 300) or cle
    sortie.personne = "PM" if morale else "PP"
    sortie.situation = situation
    sortie.date_effet = date_effet
    # Chaque champ ne vaut que pour sa situation : rien ne traîne d'une saisie précédente.
    sortie.lieu_deces = lieu if situation == "DECEDE" else None
    sortie.motif_cessation = motif if situation == "CESSE" else None
    sortie.societe_absorbante = absorbante if situation == "CESSE" and motif == "FUSION" else None
    sortie.reference_decision = reference if situation in ("RADIE", "OMIS") else None
    sortie.observation = _texte(observation, 2000)
    sortie.updated_by = user.id
    if piece is not None and piece.filename:
        sortie.piece_path, sortie.piece_nom = await _enregistrer_piece(piece, tenant_uuid, cle)
    await db.flush()
    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="sortie_declaree" if nouvelle else "sortie_modifiee",
        target_type="membre",
        target_id=cle,
        metadata_json={"situation": situation, "date_effet": date_effet, "piece": bool(sortie.piece_path)},
    )
    await db.commit()
    await db.refresh(sortie)
    return sortie


async def annuler_sortie(db: AsyncSession, user: User, organisation_id: int, sortie_id: int) -> None:
    """Réintègre le membre : la sortie avait été déclarée à tort."""
    sortie = (await db.execute(
        select(TableauSortieMembre).where(
            TableauSortieMembre.id == sortie_id,
            TableauSortieMembre.organisation_id == organisation_id,
        )
    )).scalar_one_or_none()
    if sortie is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sortie introuvable.")
    await record_tableau_audit(
        db,
        organisation_id=organisation_id,
        user_id=user.id,
        action="sortie_annulee",
        target_type="membre",
        target_id=sortie.numero_ordre,
        metadata_json={"situation": sortie.situation, "date_effet": sortie.date_effet},
    )
    await db.delete(sortie)
    await db.commit()
