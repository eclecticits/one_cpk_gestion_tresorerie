"""Transactional service for the additive internal-transfer flow.

This service deliberately does not read or write ``sorties_fonds``.  Legacy
transfers remain in that table until a later reporting-transition phase.

Correcting a transfer is **additive**.  A mistaken transfer is never rewritten,
never erased and never re-dated: it is compensated by an opposite transfer
dated the day the correction is decided, linked to it through
``transfert_origine_id``.  The original keeps its amount, its date, its
reference and its accounting entry.

The invariant that holds the three layers together::

    la date d'une opération détermine sa période de clôture ET la date de son
    écriture comptable — les trois désignent toujours la même période.

Which is precisely why the reversal is dated today rather than backdated to the
original: a closed cash period and a booked accounting entry both belong to the
past and must stay untouched, while the money really does move today.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.caisse_centrale import CaisseCentrale
from app.models.cloture_caisse import ClotureCaisse
from app.models.compte_bancaire import CompteBancaire
from app.models.transfert_interne import (
    STATUT_CONTREPASSE,
    STATUT_EXECUTE,
    TransfertInterne,
)
from app.models.user import User
from app.modules.comptabilite.services.generation_service import generer_ecriture_transfert_interne
from app.modules.comptabilite.services.integration_mode import is_accounting_automatic
from app.services.audit_service import log_action
from app.services.document_sequences import generate_document_number
from app.services.report_cache import invalidate_report_summary_cache


#: Types de `sorties_fonds` dont l'écriture est déléguée à ce service.
#:
#: Lu à chaque appel, jamais mis en cache : ouvrir ou fermer le drapeau doit
#: prendre effet au redémarrage du processus, pas à l'expiration d'un cache que
#: personne ne sait purger sous incident.
def types_delegues() -> frozenset[str]:
    brut = (settings.transferts_engine_types or "").strip()
    return frozenset(part.strip().lower() for part in brut.split(",") if part.strip())


def _tenants_delegues() -> frozenset[int]:
    brut = (settings.transferts_engine_tenants or "").strip()
    tenants = set()
    for part in brut.split(","):
        part = part.strip()
        if part.isdigit():
            tenants.add(int(part))
    return frozenset(tenants)


def delegue_au_moteur(type_sortie: str | None, tenant_id: int) -> bool:
    """Ce type, pour cette organisation, passe-t-il par le moteur dédié ?

    Deux verrous : le type doit être nommé, et — si une liste d'organisations
    est fournie — l'organisation aussi. Une liste vide vaut « toutes celles dont
    le type est ouvert », ce qui permet d'ouvrir un tenant pilote d'abord.
    """
    if (type_sortie or "").lower() not in types_delegues():
        return False
    tenants = _tenants_delegues()
    return not tenants or tenant_id in tenants


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _payload_hash(payload, *, idempotency_key: str | None) -> str:
    data = payload.model_dump(mode="json")
    data["idempotency_key"] = idempotency_key
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cohérence transfert / période de clôture / écriture comptable
# ---------------------------------------------------------------------------


async def _last_cloture_date(db: AsyncSession, tenant_id: int) -> datetime | None:
    """Borne haute des périodes déjà arrêtées.

    Une clôture fige les totaux d'une période : plus aucun mouvement ne peut y
    entrer, sous peine de rendre faux un document déjà signé et imprimé.
    """
    last = await db.scalar(
        select(ClotureCaisse.date_cloture)
        .where(ClotureCaisse.organisation_id == tenant_id, ClotureCaisse.statut == "VALIDEE")
        .order_by(ClotureCaisse.date_cloture.desc())
        .limit(1)
    )
    return _as_utc(last) if last is not None else None


async def _ensure_periode_ouverte(
    db: AsyncSession,
    tenant_id: int,
    moment: datetime,
    *,
    operation: str,
    types: tuple[str, str],
) -> None:
    """Refuse un mouvement daté dans une période de caisse déjà arrêtée.

    Borné aux transferts dont une jambe est la CAISSE : une clôture arrête la
    caisse, et `clotures._transf_sum` ne compte que ces jambes-là. Un virement
    banque → banque n'entre dans aucun total de clôture, donc rien ne justifie
    de le refuser.
    """
    if "CAISSE" not in types:
        return
    borne = await _last_cloture_date(db, tenant_id)
    if borne is not None and _as_utc(moment) <= borne:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{operation} : la période est clôturée depuis le "
                f"{borne.date().isoformat()}. Une opération datée du jour est nécessaire."
            ),
        )


# ---------------------------------------------------------------------------
# Verrouillage des comptes
# ---------------------------------------------------------------------------


async def _get_or_create_caisse(db: AsyncSession, tenant_id: int) -> CaisseCentrale:
    caisse = await db.scalar(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
    if caisse is None:
        # ON CONFLICT DO NOTHING : deux premières opérations concurrentes d'un
        # tenant neuf se disputent `uq_caisse_centrale_organisation_id`, un
        # simple add()+flush() ferait remonter une IntegrityError en 500.
        await db.execute(
            pg_insert(CaisseCentrale)
            .values(organisation_id=tenant_id, solde_usd=0, solde_cdf=0)
            .on_conflict_do_nothing(index_elements=["organisation_id"])
        )
        caisse = await db.scalar(select(CaisseCentrale).where(CaisseCentrale.organisation_id == tenant_id).limit(1))
    return caisse


async def _lock_account(db: AsyncSession, tenant_id: int, kind: str, account_id: int | None):
    if kind == "CAISSE":
        caisse = await _get_or_create_caisse(db, tenant_id)
        return await db.scalar(
            select(CaisseCentrale)
            .where(CaisseCentrale.id == caisse.id, CaisseCentrale.organisation_id == tenant_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    if account_id is None:
        raise HTTPException(status_code=400, detail="source_id/destination_id requis pour une banque")
    account = await db.scalar(
        select(CompteBancaire)
        .where(CompteBancaire.id == account_id, CompteBancaire.organisation_id == tenant_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if account is None or not account.is_active or (account.account_type or "BANK").upper() != "BANK":
        raise HTTPException(status_code=404, detail="Compte bancaire introuvable dans ce tenant")
    return account


async def _lock_pair(db: AsyncSession, tenant_id: int, source_type: str, source_id: int | None, destination_type: str, destination_id: int | None):
    """Verrouille les deux comptes dans un ordre canonique.

    L'ordre BANQUE puis CAISSE est celui du chemin `sorties_fonds` (compte de
    destination verrouillé avant la caisse) : deux transferts croisés, ou un
    transfert et un versement legacy, ne peuvent pas se bloquer mutuellement.
    """
    refs = [(source_type, source_id), (destination_type, destination_id)]
    if refs[0] == refs[1]:
        raise HTTPException(status_code=400, detail="source et destination identiques")
    locked = {}
    for kind, account_id in sorted(refs, key=lambda item: (item[0], item[1] or 0)):
        locked[(kind, account_id)] = await _lock_account(db, tenant_id, kind, account_id)
    return locked[(source_type, source_id)], locked[(destination_type, destination_id)]


def _ensure_caisse_ouverte(account, kind: str, *, operation: str) -> None:
    """Une caisse fermée ne bouge pas.

    Même règle que toutes les autres routes qui déplacent des espèces
    (`sorties_fonds`, `retours_caisse`, `encaissement_payments`) : sans elle, le
    module Transferts serait le seul moyen de vider le tiroir hors session.
    """
    if kind == "CAISSE" and not account.est_ouverte:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caisse fermée : ouvrez la caisse avant {operation}.",
        )


def _balance(account, kind: str, devise: str) -> Decimal:
    if kind == "CAISSE":
        return Decimal(str(account.solde_usd if devise == "USD" else account.solde_cdf))
    return Decimal(str(account.solde_actuel or 0))


def _change(account, kind: str, devise: str, amount: Decimal) -> None:
    if kind == "CAISSE":
        if devise == "USD":
            account.solde_usd = Decimal(str(account.solde_usd or 0)) + amount
        else:
            account.solde_cdf = Decimal(str(account.solde_cdf or 0)) + amount
        account.derniere_maj = _utcnow()
    else:
        account.solde_actuel = Decimal(str(account.solde_actuel or 0)) + amount


def _ensure_bank_currency(account, devise: str) -> None:
    if (account.devise or "").upper() != devise:
        raise HTTPException(status_code=400, detail="devise incompatible avec le compte")


def _integrity_to_http(exc: IntegrityError) -> HTTPException | None:
    message = str(getattr(exc, "orig", exc))
    if "uq_transferts_internes_org_reference" in message:
        return HTTPException(status_code=409, detail="Référence de transfert déjà utilisée pour cette organisation")
    if "uq_transferts_internes_org_idempotency" in message:
        return HTTPException(status_code=409, detail="Conflit d'idempotence sur ce transfert")
    if "uq_transferts_internes_origine" in message:
        return HTTPException(status_code=409, detail="Ce transfert a déjà été contre-passé")
    return None


# ---------------------------------------------------------------------------
# Création
# ---------------------------------------------------------------------------


async def create_transfer(
    db: AsyncSession,
    *,
    payload,
    tenant_id: int,
    user: User,
    idempotency_key: str | None = None,
    #: Identité documentaire annoncée par le chemin `sorties-fonds`. L'écran
    #: adresse une opération par UUID, la clé primaire d'un transfert est un
    #: entier : c'est cet UUID qui permet de retrouver le transfert pour lui
    #: attacher son bon ou le contre-passer. Absent pour un transfert saisi
    #: directement sur `/transferts-internes`, qui n'annonce d'UUID à personne.
    document_uuid: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> TransfertInterne:
    key = idempotency_key or getattr(payload, "idempotency_key", None)
    payload_hash = _payload_hash(payload, idempotency_key=key)
    try:
        if key:
            # Serialize requests sharing the same tenant/key even when the row
            # does not exist yet; the partial unique index is the final guard.
            await db.execute(select(text("pg_advisory_xact_lock(hashtext(:lock_key))")).params(lock_key=f"transfer:{tenant_id}:{key}"))
            existing = await db.scalar(select(TransfertInterne).where(TransfertInterne.organisation_id == tenant_id, TransfertInterne.idempotency_key == key))
            if existing is not None:
                if existing.idempotency_payload_hash != payload_hash:
                    raise HTTPException(status_code=409, detail="Idempotency-Key déjà utilisée avec un payload différent")
                # Rejeu : rien n'a été écrit, mais la transaction doit être
                # refermée pour libérer l'advisory lock. `commit` et non
                # `rollback` : un rollback expire les objets de la session et
                # l'accès aux attributs de `existing` repartirait en lazy IO.
                await db.commit()
                # Pas d'invalidation : un rejeu n'a rien écrit, et purger le
                # cache à chaque double-clic le viderait sans raison.
                return existing

        source_type = payload.source_type.upper()
        destination_type = payload.destination_type.upper()
        devise = payload.devise.upper()
        amount = Decimal(str(payload.montant))
        if source_type not in {"CAISSE", "BANQUE"} or destination_type not in {"CAISSE", "BANQUE"}:
            raise HTTPException(status_code=400, detail="type de compte invalide")
        if devise not in {"USD", "CDF"} or amount <= 0:
            raise HTTPException(status_code=400, detail="montant ou devise invalide")
        source_id = payload.source_id if source_type == "BANQUE" else None
        destination_id = payload.destination_id if destination_type == "BANQUE" else None

        # La date pilote à la fois la période de clôture et l'exercice de
        # l'écriture : elle est contrôlée avant tout mouvement.
        date_transfer = _as_utc(payload.date_transfert or _utcnow())
        await _ensure_periode_ouverte(
            db, tenant_id, date_transfer, operation="Transfert refusé",
            types=(source_type, destination_type),
        )

        source, destination = await _lock_pair(db, tenant_id, source_type, source_id, destination_type, destination_id)
        _ensure_caisse_ouverte(source, source_type, operation="d'enregistrer un transfert")
        _ensure_caisse_ouverte(destination, destination_type, operation="de l'approvisionner")
        if source_type == "BANQUE":
            _ensure_bank_currency(source, devise)
        if destination_type == "BANQUE":
            _ensure_bank_currency(destination, devise)
        if _balance(source, source_type, devise) < amount:
            raise HTTPException(status_code=409, detail="Solde source insuffisant")
        _change(source, source_type, devise, -amount)
        _change(destination, destination_type, devise, amount)

        reference = payload.reference or await generate_document_number(db, "TRF", tenant_id)
        transfer = TransfertInterne(
            organisation_id=tenant_id, source_type=source_type, source_id=source_id,
            destination_type=destination_type, destination_id=destination_id,
            montant=amount, devise=devise, reference=reference, date_transfert=date_transfer,
            statut=STATUT_EXECUTE, execute_par=user.id, idempotency_key=key,
            idempotency_payload_hash=payload_hash, document_uuid=document_uuid,
        )
        db.add(transfer)
        await db.flush()
        if await is_accounting_automatic(db, tenant_id):
            await generer_ecriture_transfert_interne(
                db, organisation_id=tenant_id, sortie_fonds_id=str(transfer.id),
                date_operation=date_transfer.date(), montant=amount, devise=devise,
                compte_origine_bancaire_id=source_id if source_type == "BANQUE" else None,
                compte_destination_bancaire_id=destination_id if destination_type == "BANQUE" else None,
                libelle=reference, created_by=user.id, module_origine="transferts",
            )
        await log_action(
            db,
            user_id=user.id,
            action="TRANSFERT_INTERNE_CREATED",
            target_table="transferts_internes",
            target_id=str(transfer.id),
            new_value={
                "reference": reference,
                "source_type": source_type, "source_id": source_id,
                "destination_type": destination_type, "destination_id": destination_id,
                "montant": str(amount), "devise": devise,
                "date_transfert": date_transfer.isoformat(),
            },
            ip_address=ip_address,
        )
        await db.commit()
        await db.refresh(transfer)
        # Un transfert déplace de la trésorerie : les résumés de rapports
        # mémorisés pour cette organisation ne valent plus. Même geste que
        # `encaissements`, `retours_caisse` et `sorties_fonds` — après le
        # commit, pour ne pas purger un cache au profit d'un état qui pourrait
        # encore être annulé.
        await invalidate_report_summary_cache(tenant_id)
        return transfer
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        mapped = _integrity_to_http(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    except Exception:
        await db.rollback()
        raise


# ---------------------------------------------------------------------------
# Contre-passation
# ---------------------------------------------------------------------------


async def contrepasser_transfer(
    db: AsyncSession,
    *,
    transfer_id: int,
    tenant_id: int,
    user: User,
    motif: str,
    ip_address: str | None = None,
) -> TransfertInterne:
    """Corrige un transfert par un transfert inverse daté du jour.

    Retourne la **ligne inverse** créée, pas l'original : c'est elle qui porte
    l'opération financière du jour, et c'est elle qui a une écriture comptable.
    L'original reste lisible, à son montant et à sa date, avec le statut
    ``CONTREPASSE`` et le motif de la correction.
    """
    motif = (motif or "").strip()
    if len(motif) < 3:
        raise HTTPException(status_code=400, detail="Motif de contre-passation requis (3 caractères minimum)")
    try:
        origine = await db.scalar(
            select(TransfertInterne)
            .where(TransfertInterne.id == transfer_id, TransfertInterne.organisation_id == tenant_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if origine is None:
            raise HTTPException(status_code=404, detail="Transfert introuvable")
        if origine.transfert_origine_id is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Une contre-passation ne se contre-passe pas : saisissez un nouveau "
                    "transfert si la correction elle-même doit être corrigée"
                ),
            )
        if origine.statut != STATUT_EXECUTE:
            raise HTTPException(status_code=409, detail="Transfert déjà contre-passé")

        now = _utcnow()
        # La correction entre dans la période où elle est réellement effectuée :
        # jamais dans celle de l'original, qui peut être clôturée et imprimée.
        # Sens inverse : ce qui était destination redevient source.
        source_type, source_id = origine.destination_type, origine.destination_id
        destination_type, destination_id = origine.source_type, origine.source_id
        await _ensure_periode_ouverte(
            db, tenant_id, now, operation="Contre-passation refusée",
            types=(source_type, destination_type),
        )
        devise = origine.devise
        amount = Decimal(str(origine.montant))

        source, destination = await _lock_pair(db, tenant_id, source_type, source_id, destination_type, destination_id)
        _ensure_caisse_ouverte(source, source_type, operation="de contre-passer un transfert")
        _ensure_caisse_ouverte(destination, destination_type, operation="de contre-passer un transfert")
        if _balance(source, source_type, devise) < amount:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Contre-passation refusée : le solde source ne couvre pas "
                    f"{amount} {devise} aujourd'hui."
                ),
            )
        _change(source, source_type, devise, -amount)
        _change(destination, destination_type, devise, amount)

        reference = await generate_document_number(db, "TRF", tenant_id)
        inverse = TransfertInterne(
            organisation_id=tenant_id, source_type=source_type, source_id=source_id,
            destination_type=destination_type, destination_id=destination_id,
            montant=amount, devise=devise, reference=reference, date_transfert=now,
            statut=STATUT_EXECUTE, execute_par=user.id,
            transfert_origine_id=origine.id,
            # La correction est adressable là où l'original l'était. Un transfert
            # saisi par le chemin `sorties-fonds` y est identifié par son
            # `document_uuid` : sans le sien, la ligne inverse n'apparaîtrait pas
            # sur cet écran, qui montrerait alors un original contre-passé sans
            # la ligne qui le compense — un total de +100 privé de son −100.
            # NULL pour un transfert saisi directement sur `/transferts-internes`,
            # qui n'a jamais annoncé d'UUID à personne : l'inverse non plus.
            document_uuid=uuid.uuid4() if origine.document_uuid is not None else None,
        )
        db.add(inverse)

        origine.statut = STATUT_CONTREPASSE
        origine.contrepasse_le = now
        origine.contrepasse_par = user.id
        origine.motif_contrepassation = motif
        origine.updated_at = now
        await db.flush()

        # L'inverse est un transfert à part entière : son écriture passe par le
        # chemin normal, avec son propre identifiant d'objet et la date du jour.
        # L'écriture d'origine n'est ni touchée ni annulée — elle est compensée,
        # exactement comme la ligne de trésorerie qu'elle traduit.
        if await is_accounting_automatic(db, tenant_id):
            await generer_ecriture_transfert_interne(
                db, organisation_id=tenant_id, sortie_fonds_id=str(inverse.id),
                date_operation=now.date(), montant=amount, devise=devise,
                compte_origine_bancaire_id=source_id if source_type == "BANQUE" else None,
                compte_destination_bancaire_id=destination_id if destination_type == "BANQUE" else None,
                libelle=f"Contre-passation {origine.reference} — {motif}",
                created_by=user.id, module_origine="transferts",
            )
        await log_action(
            db,
            user_id=user.id,
            action="TRANSFERT_INTERNE_REVERSED",
            target_table="transferts_internes",
            target_id=str(origine.id),
            old_value={"statut": STATUT_EXECUTE, "reference": origine.reference},
            new_value={
                "statut": STATUT_CONTREPASSE,
                "motif_contrepassation": motif,
                "contrepassation_id": inverse.id,
                "contrepassation_reference": reference,
                "date_contrepassation": now.isoformat(),
            },
            ip_address=ip_address,
        )
        await db.commit()
        await db.refresh(inverse)
        await invalidate_report_summary_cache(tenant_id)
        return inverse
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        mapped = _integrity_to_http(exc)
        if mapped is not None:
            raise mapped from exc
        raise
    except Exception:
        await db.rollback()
        raise
