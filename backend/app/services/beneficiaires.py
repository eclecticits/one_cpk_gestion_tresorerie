"""Bénéficiaires des sorties de fonds : qui reçoit l'argent, et comment le joindre.

Quatre sources, cherchées dans cet ordre :

1. les experts-comptables (`experts_comptables`) ;
2. le personnel administratif (`hr_employees`) ;
3. les utilisateurs de l'application (`users`) — beaucoup de bénéficiaires en
   sont, et leur e-mail est déjà connu ;
4. les personnes externes (`beneficiaires_externes`), répertoire que les
   formulaires alimentent eux-mêmes.

Les fiches d'experts et de personnel ne sont jamais modifiées d'ici : leur
module en est seul maître. Un contact saisi à la caisse pour un expert qui n'en
a pas vaut pour la sortie, pas pour la fiche. Le répertoire externe, lui,
n'appartient qu'à la caisse : un contact qui y manquait y est complété.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.beneficiaire_externe import BeneficiaireExterne
from app.models.expert_comptable import ExpertComptable
from app.models.hr import HREmployee
from app.models.user import User
from app.models.ordre_decaissement import normaliser_cle_beneficiaire
from app.services.notifications.phone import normalize_phone

TYPE_EXPERT = "EXPERT"
TYPE_PERSONNEL = "PERSONNEL"
TYPE_UTILISATEUR = "UTILISATEUR"
TYPE_EXTERNE = "EXTERNE"
TYPES_BENEFICIAIRE = frozenset({TYPE_EXPERT, TYPE_PERSONNEL, TYPE_UTILISATEUR, TYPE_EXTERNE})

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class BeneficiaireIdentifie:
    """Ce qu'une sortie retient de son bénéficiaire."""

    type: str
    nom: str
    expert_id: uuid.UUID | None = None
    employe_id: int | None = None
    externe_id: uuid.UUID | None = None
    utilisateur_id: uuid.UUID | None = None
    email: str | None = None
    telephone: str | None = None


def nettoyer_email(value: str | None) -> str | None:
    """E-mail exploitable ou None. Refuse ce qui ne peut pas être une adresse."""
    email = (value or "").strip()
    if not email:
        return None
    if not _EMAIL.match(email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Adresse e-mail du bénéficiaire invalide : {email}",
        )
    return email[:200]


def nettoyer_telephone(value: str | None) -> str | None:
    """Numéro au format E.164 (sans « + ») ou None. Refuse un numéro inexploitable.

    Mieux vaut un refus à la saisie qu'un WhatsApp qui échoue sans que personne
    le voie.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = normalize_phone(raw)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Numéro de téléphone du bénéficiaire invalide : {raw}",
        )
    return normalized


def nom_employe(employe: HREmployee) -> str:
    return " ".join(filter(None, [employe.nom, employe.post_nom, employe.prenom])).strip()


def nom_utilisateur(user: User) -> str:
    return " ".join(filter(None, [user.prenom, user.nom])).strip() or user.email


def _texte(value: str | None) -> str | None:
    return (value or "").strip() or None


async def rechercher(
    db: AsyncSession,
    organisation_id: int,
    q: str,
    *,
    limite: int = 8,
) -> list[dict]:
    """Suggestions pour le champ Bénéficiaire, experts d'abord, externes en dernier."""
    terme = (q or "").strip()
    if len(terme) < 2:
        return []
    motif = f"%{terme}%"
    resultats: list[dict] = []

    experts = (
        await db.execute(
            select(ExpertComptable)
            .where(
                # Inactifs compris, comme à l'encaissement : la liste nationale
                # crée ses experts inactifs tant que leur situation n'est pas
                # vérifiée, et ils doivent pouvoir être payés.
                or_(
                    ExpertComptable.nom_denomination.ilike(motif),
                    ExpertComptable.numero_ordre.ilike(motif),
                ),
            )
            .order_by(ExpertComptable.active.desc(), ExpertComptable.nom_denomination)
            .limit(limite)
        )
    ).scalars().all()
    for expert in experts:
        resultats.append(
            {
                "type": TYPE_EXPERT,
                "id": str(expert.id),
                "nom": expert.nom_denomination,
                "detail": f"N° d'ordre {expert.numero_ordre}",
                "email": _texte(expert.email),
                "telephone": _texte(expert.telephone),
            }
        )

    employes = (
        await db.execute(
            select(HREmployee)
            .where(
                HREmployee.tenant_id == organisation_id,
                func.concat(
                    HREmployee.nom, " ", HREmployee.post_nom, " ", HREmployee.prenom, " ", HREmployee.matricule
                ).ilike(motif),
            )
            .order_by(HREmployee.nom, HREmployee.prenom)
            .limit(limite)
        )
    ).scalars().all()
    for employe in employes:
        resultats.append(
            {
                "type": TYPE_PERSONNEL,
                "id": str(employe.id),
                "nom": nom_employe(employe),
                "detail": f"Matricule {employe.matricule}",
                "email": _texte(employe.email),
                "telephone": _texte(employe.telephone),
            }
        )

    utilisateurs = (
        await db.execute(
            select(User)
            .where(
                User.organisation_id == organisation_id,
                User.active.is_(True),
                or_(
                    func.concat(User.prenom, " ", User.nom).ilike(motif),
                    func.concat(User.nom, " ", User.prenom).ilike(motif),
                    User.email.ilike(motif),
                ),
            )
            .order_by(User.nom, User.prenom)
            .limit(limite)
        )
    ).scalars().all()
    for utilisateur in utilisateurs:
        resultats.append(
            {
                "type": TYPE_UTILISATEUR,
                "id": str(utilisateur.id),
                "nom": nom_utilisateur(utilisateur),
                "detail": "Utilisateur de l'application",
                "email": _texte(utilisateur.email),
                "telephone": None,
            }
        )

    externes = (
        await db.execute(
            select(BeneficiaireExterne)
            .where(
                BeneficiaireExterne.organisation_id == organisation_id,
                BeneficiaireExterne.active.is_(True),
                or_(
                    BeneficiaireExterne.nom.ilike(motif),
                    BeneficiaireExterne.structure.ilike(motif),
                ),
            )
            .order_by(BeneficiaireExterne.nom)
            .limit(limite)
        )
    ).scalars().all()
    for externe in externes:
        resultats.append(
            {
                "type": TYPE_EXTERNE,
                "id": str(externe.id),
                "nom": externe.nom,
                "detail": externe.structure or "Personne externe",
                "email": _texte(externe.email),
                "telephone": _texte(externe.telephone),
            }
        )

    return resultats


async def enregistrer_externe(
    db: AsyncSession,
    organisation_id: int,
    *,
    nom: str,
    email: str | None = None,
    telephone: str | None = None,
    structure: str | None = None,
    created_by: uuid.UUID | None = None,
) -> BeneficiaireExterne:
    """Fiche externe de ce nom, créée si besoin, contacts complétés s'ils manquaient.

    Un contact déjà présent n'est pas écrasé : la caisse corrige une fiche depuis
    le répertoire, pas au détour d'un paiement.
    """
    nom_propre = re.sub(r"\s+", " ", (nom or "")).strip()
    if not nom_propre:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nom du bénéficiaire requis")
    cle = normaliser_cle_beneficiaire(nom_propre)[:200]

    externe = (
        await db.execute(
            select(BeneficiaireExterne).where(
                BeneficiaireExterne.organisation_id == organisation_id,
                BeneficiaireExterne.nom_normalise == cle,
            )
        )
    ).scalar_one_or_none()

    if externe is None:
        externe = BeneficiaireExterne(
            organisation_id=organisation_id,
            nom=nom_propre[:200],
            nom_normalise=cle,
            email=email,
            telephone=telephone,
            structure=_texte(structure),
            created_by=created_by,
        )
        db.add(externe)
        await db.flush()
        return externe

    if email and not externe.email:
        externe.email = email
    if telephone and not externe.telephone:
        externe.telephone = telephone
    if structure and not externe.structure:
        externe.structure = _texte(structure)
    if not externe.active:
        externe.active = True
    return externe


async def identifier(
    db: AsyncSession,
    organisation_id: int,
    *,
    nom: str,
    type_beneficiaire: str | None,
    reference_id: str | None,
    email: str | None,
    telephone: str | None,
    created_by: uuid.UUID | None = None,
) -> BeneficiaireIdentifie | None:
    """Résout le bénéficiaire désigné à la caisse. None si la caisse n'a rien précisé.

    Le contact saisi prime sur celui de la fiche ; à défaut, celui de la fiche.
    `nom` est le nom figé de la sortie : pour une fiche existante, c'est celui de
    la fiche qui fait foi.
    """
    type_norm = (type_beneficiaire or "").strip().upper()
    if not type_norm:
        return None
    if type_norm not in TYPES_BENEFICIAIRE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Type de bénéficiaire inconnu")

    email_saisi = nettoyer_email(email)
    telephone_saisi = nettoyer_telephone(telephone)
    ref = (reference_id or "").strip()

    if type_norm == TYPE_EXPERT:
        try:
            expert_id = uuid.UUID(ref)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Expert-comptable bénéficiaire requis")
        expert = await db.get(ExpertComptable, expert_id)
        if expert is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Expert-comptable introuvable")
        return BeneficiaireIdentifie(
            type=TYPE_EXPERT,
            nom=expert.nom_denomination,
            expert_id=expert.id,
            email=email_saisi or _texte(expert.email),
            telephone=telephone_saisi or normalize_phone(expert.telephone),
        )

    if type_norm == TYPE_PERSONNEL:
        try:
            employe_id = int(ref)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Membre du personnel bénéficiaire requis")
        employe = (
            await db.execute(
                select(HREmployee).where(HREmployee.id == employe_id, HREmployee.tenant_id == organisation_id)
            )
        ).scalar_one_or_none()
        if employe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membre du personnel introuvable")
        return BeneficiaireIdentifie(
            type=TYPE_PERSONNEL,
            nom=nom_employe(employe),
            employe_id=employe.id,
            email=email_saisi or _texte(employe.email),
            telephone=telephone_saisi or normalize_phone(employe.telephone),
        )

    if type_norm == TYPE_UTILISATEUR:
        try:
            utilisateur_id = uuid.UUID(ref)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Utilisateur bénéficiaire requis")
        utilisateur = (
            await db.execute(
                select(User).where(User.id == utilisateur_id, User.organisation_id == organisation_id)
            )
        ).scalar_one_or_none()
        if utilisateur is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Utilisateur introuvable")
        return BeneficiaireIdentifie(
            type=TYPE_UTILISATEUR,
            nom=nom_utilisateur(utilisateur),
            utilisateur_id=utilisateur.id,
            email=email_saisi or _texte(utilisateur.email),
            telephone=telephone_saisi,
        )

    externe: BeneficiaireExterne | None = None
    if ref:
        try:
            externe_id = uuid.UUID(ref)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bénéficiaire externe invalide")
        externe = (
            await db.execute(
                select(BeneficiaireExterne).where(
                    BeneficiaireExterne.id == externe_id,
                    BeneficiaireExterne.organisation_id == organisation_id,
                )
            )
        ).scalar_one_or_none()
        if externe is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bénéficiaire externe introuvable")
        if email_saisi and not externe.email:
            externe.email = email_saisi
        if telephone_saisi and not externe.telephone:
            externe.telephone = telephone_saisi
    else:
        externe = await enregistrer_externe(
            db,
            organisation_id,
            nom=nom,
            email=email_saisi,
            telephone=telephone_saisi,
            created_by=created_by,
        )

    return BeneficiaireIdentifie(
        type=TYPE_EXTERNE,
        nom=externe.nom,
        externe_id=externe.id,
        email=email_saisi or _texte(externe.email),
        telephone=telephone_saisi or normalize_phone(externe.telephone),
    )


# ── Report d'une pièce à l'autre ─────────────────────────────────────────────
# La réquisition et l'ordre de décaissement désignent le bénéficiaire ; la
# sortie le reprend. Une seule liste de colonnes pour les trois tables.

COLONNES_IDENTIFICATION = (
    "beneficiaire_type",
    "beneficiaire_expert_id",
    "beneficiaire_employe_id",
    "beneficiaire_externe_id",
    "beneficiaire_utilisateur_id",
    "beneficiaire_email",
    "beneficiaire_telephone",
)

CHAMPS_SAISIE = ("beneficiaire_type", "beneficiaire_ref_id", "beneficiaire_email", "beneficiaire_telephone")


def appliquer(cible, identifie: BeneficiaireIdentifie | None) -> None:
    """Pose l'identification sur une pièce ; None l'efface."""
    cible.beneficiaire_type = identifie.type if identifie else None
    cible.beneficiaire_expert_id = identifie.expert_id if identifie else None
    cible.beneficiaire_employe_id = identifie.employe_id if identifie else None
    cible.beneficiaire_externe_id = identifie.externe_id if identifie else None
    cible.beneficiaire_utilisateur_id = identifie.utilisateur_id if identifie else None
    cible.beneficiaire_email = identifie.email if identifie else None
    cible.beneficiaire_telephone = identifie.telephone if identifie else None


def a_identification(source) -> bool:
    return bool(getattr(source, "beneficiaire_type", None))


def copier(source, cible) -> None:
    for colonne in COLONNES_IDENTIFICATION:
        setattr(cible, colonne, getattr(source, colonne, None))


def ref_id(source) -> str | None:
    for colonne in (
        "beneficiaire_expert_id",
        "beneficiaire_employe_id",
        "beneficiaire_utilisateur_id",
        "beneficiaire_externe_id",
    ):
        valeur = getattr(source, colonne, None)
        if valeur is not None:
            return str(valeur)
    return None


def champs_publics(source) -> dict:
    """Ce que l'API rend d'une pièce : de quoi réafficher la fiche et ses contacts."""
    return {
        "beneficiaire_type": getattr(source, "beneficiaire_type", None),
        "beneficiaire_ref_id": ref_id(source),
        "beneficiaire_email": getattr(source, "beneficiaire_email", None),
        "beneficiaire_telephone": getattr(source, "beneficiaire_telephone", None),
    }


def saisie_presente(payload) -> bool:
    """Le formulaire a-t-il envoyé une identification (même vide, pour l'effacer) ?"""
    envoyes = getattr(payload, "model_fields_set", set())
    return any(champ in envoyes for champ in CHAMPS_SAISIE)


async def identifier_payload(
    db: AsyncSession,
    organisation_id: int,
    payload,
    *,
    nom: str | None,
    created_by: uuid.UUID | None = None,
) -> BeneficiaireIdentifie | None:
    """Identification envoyée par un formulaire. Sans fiche mais avec un contact,
    la personne devient une fiche externe à ce nom."""
    type_beneficiaire = getattr(payload, "beneficiaire_type", None)
    email = getattr(payload, "beneficiaire_email", None)
    telephone = getattr(payload, "beneficiaire_telephone", None)
    if not type_beneficiaire and ((email or "").strip() or (telephone or "").strip()):
        type_beneficiaire = TYPE_EXTERNE
    if not type_beneficiaire or not (nom or "").strip():
        return None
    return await identifier(
        db,
        organisation_id,
        nom=nom or "",
        type_beneficiaire=type_beneficiaire,
        reference_id=getattr(payload, "beneficiaire_ref_id", None),
        email=email,
        telephone=telephone,
        created_by=created_by,
    )
