"""Régularisation des écarts de caisse constatés lors d'un comptage physique.

Règle métier
------------
Un comptage physique ne remplace **jamais** le solde théorique du logiciel
(`caisse.solde_usd = solde_physique` est proscrit : cela détruit la traçabilité).
Le logiciel compare, constate l'écart, puis propose une opération financière
identifiable :

* physique > théorique  -> **excédent** -> Encaissement de régularisation
* physique < théorique  -> **déficit**  -> Sortie de régularisation
* physique = théorique  -> aucune opération

C'est cette opération, et elle seule, qui déplace le solde. Si l'utilisateur ne
la confirme pas, rien n'est créé : le solde reste au théorique et l'écart demeure
ouvert, régularisable plus tard. Une régularisation ne bloque donc jamais
l'ouverture ni la clôture de la caisse.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetPoste
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement
from app.models.regularisation_caisse import RegularisationCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.system_settings import SystemSettings
from app.services.document_sequences import generate_document_number

TYPE_SORTIE_REGULARISATION = "regularisation_caisse"
LIBELLE_REGULARISATION = "Régularisation d'écart de caisse"

SOURCE_OUVERTURE = "OUVERTURE"
SOURCE_CLOTURE = "CLOTURE"

SENS_EXCEDENT = "EXCEDENT"
SENS_DEFICIT = "DEFICIT"


class RegularisationImpossible(Exception):
    """La régularisation ne peut pas aboutir — sans empêcher la caisse d'opérer.

    L'appelant doit laisser l'ouverture ou la clôture se terminer et remonter
    `message` à l'utilisateur : l'écart restera simplement non régularisé.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class EcartCaisse:
    devise: str
    solde_theorique: Decimal
    solde_physique: Decimal

    @property
    def montant(self) -> Decimal:
        """Valeur absolue de l'écart, toujours positive."""
        return abs(self.solde_physique - self.solde_theorique)

    @property
    def sens(self) -> str | None:
        delta = self.solde_physique - self.solde_theorique
        if delta > 0:
            return SENS_EXCEDENT
        if delta < 0:
            return SENS_DEFICIT
        return None


async def _poste_regularisation(
    db: AsyncSession, tenant_id: int, sens: str
) -> BudgetPoste:
    res = await db.execute(
        select(SystemSettings).where(SystemSettings.organisation_id == tenant_id).limit(1)
    )
    settings_row = res.scalar_one_or_none()
    poste_id = None
    if settings_row is not None:
        poste_id = (
            settings_row.budget_poste_excedent_caisse_id
            if sens == SENS_EXCEDENT
            else settings_row.budget_poste_deficit_caisse_id
        )
    if not poste_id:
        libelle = "excédent" if sens == SENS_EXCEDENT else "déficit"
        raise RegularisationImpossible(
            f"Aucun poste budgétaire n'est configuré pour les {libelle}s de caisse. "
            "Renseignez-le dans Paramètres avant de régulariser cet écart."
        )
    res = await db.execute(
        select(BudgetPoste).where(
            BudgetPoste.id == poste_id,
            BudgetPoste.organisation_id == tenant_id,
            BudgetPoste.is_deleted.is_(False),
        )
    )
    poste = res.scalar_one_or_none()
    if poste is None:
        raise RegularisationImpossible(
            "Le poste budgétaire configuré pour les écarts de caisse est introuvable "
            "ou a été supprimé. Corrigez le paramétrage avant de régulariser."
        )
    return poste


async def regulariser_ecart(
    db: AsyncSession,
    *,
    tenant_id: int,
    user_id: uuid.UUID | None,
    ecart: EcartCaisse,
    motif: str,
    source_type: str,
    source_id: int,
    source_reference: str | None = None,
) -> RegularisationCaisse:
    """Crée l'opération qui résorbe `ecart` et met le solde de caisse à jour.

    Ne commit pas : l'appelant maîtrise la transaction, de sorte que la
    régularisation et le document qui l'a motivée (ouverture ou clôture) soient
    validés ensemble.

    Lève `RegularisationImpossible` si le paramétrage manque — l'appelant doit
    alors laisser la caisse s'ouvrir ou se clôturer sans régulariser.
    """
    sens = ecart.sens
    if sens is None:
        raise RegularisationImpossible("Aucun écart à régulariser : les montants correspondent.")

    motif_clean = (motif or "").strip()
    if not motif_clean:
        raise RegularisationImpossible("Un motif est obligatoire pour régulariser un écart de caisse.")

    poste = await _poste_regularisation(db, tenant_id, sens)
    montant = ecart.montant
    now = datetime.now(timezone.utc)

    caisse_res = await db.execute(
        select(CaisseCentrale)
        .where(CaisseCentrale.organisation_id == tenant_id)
        .with_for_update()
        .limit(1)
    )
    caisse = caisse_res.scalar_one_or_none()
    if caisse is None:
        raise RegularisationImpossible("Caisse centrale introuvable pour cette organisation.")

    encaissement_id: uuid.UUID | None = None
    sortie_id: uuid.UUID | None = None

    if sens == SENS_EXCEDENT:
        # Excédent : de l'argent en plus dans le tiroir -> encaissement.
        numero = await generate_document_number(db, "ENC", tenant_id)
        encaissement = Encaissement(
            organisation_id=tenant_id,
            numero_recu=numero,
            libelle=LIBELLE_REGULARISATION,
            description=motif_clean,
            type_client="organisation",
            client_nom=LIBELLE_REGULARISATION,
            montant=montant,
            montant_total=montant,
            montant_paye=montant,
            montant_percu=montant,
            devise_perception=ecart.devise,
            taux_change_applique=Decimal("1"),
            canal="CAISSE",
            mode_paiement="cash",
            statut_paiement="complet",
            est_proforma=False,
            date_encaissement=now,
            date_paiement=now,
            budget_poste_id=poste.id,
            budget_poste_code=poste.code,
            budget_poste_libelle=poste.libelle,
            created_by=user_id,
        )
        db.add(encaissement)
        await db.flush()
        encaissement_id = encaissement.id
        if ecart.devise == "USD":
            caisse.solde_usd = (caisse.solde_usd or Decimal("0")) + montant
        else:
            caisse.solde_cdf = (caisse.solde_cdf or Decimal("0")) + montant
    else:
        # Déficit : de l'argent manquant -> sortie.
        numero = await generate_document_number(db, "SOR", tenant_id)
        sortie = SortieFonds(
            organisation_id=tenant_id,
            type_sortie=TYPE_SORTIE_REGULARISATION,
            reference_numero=numero,
            beneficiaire=LIBELLE_REGULARISATION,
            motif=motif_clean,
            montant_paye=montant,
            devise=ecart.devise,
            canal="CAISSE",
            mode_paiement="cash",
            statut="VALIDE",
            date_paiement=now,
            budget_poste_id=poste.id,
            budget_poste_code=poste.code,
            budget_poste_libelle=poste.libelle,
            created_by=user_id,
        )
        db.add(sortie)
        await db.flush()
        sortie_id = sortie.id
        if ecart.devise == "USD":
            caisse.solde_usd = (caisse.solde_usd or Decimal("0")) - montant
        else:
            caisse.solde_cdf = (caisse.solde_cdf or Decimal("0")) - montant

    caisse.derniere_maj = now

    # Imputation budgétaire : l'écart de caisse est un produit ou une charge.
    poste.montant_paye = (poste.montant_paye or Decimal("0")) + montant

    regularisation = RegularisationCaisse(
        organisation_id=tenant_id,
        source_type=source_type,
        source_id=source_id,
        source_reference=source_reference,
        devise=ecart.devise,
        sens=sens,
        montant=montant,
        solde_theorique=ecart.solde_theorique,
        solde_physique=ecart.solde_physique,
        encaissement_id=encaissement_id,
        sortie_fonds_id=sortie_id,
        motif=motif_clean,
        created_by=user_id,
        created_at=now,
    )
    db.add(regularisation)
    await db.flush()
    return regularisation
