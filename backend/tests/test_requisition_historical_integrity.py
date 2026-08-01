import uuid
import importlib
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.user import User
from app.schemas.requisition import LigneRequisitionCreate, RequisitionUpdate
from app.services.requisition_service import update_requisition_logic, validate_requisition_logic


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260801_req_reset_bypass.py"
)
_migration_spec = importlib.util.spec_from_file_location("req_reset_bypass", _MIGRATION_PATH)
assert _migration_spec is not None and _migration_spec.loader is not None
req_reset_bypass = importlib.util.module_from_spec(_migration_spec)
_migration_spec.loader.exec_module(req_reset_bypass)


class _FakeRequest:
    headers: dict = {}
    client = None


def _express_workflow():
    return {
        "preset": "express",
        "steps": {
            "signature_service": {"enabled": False},
            "examen": {"enabled": False},
            "validation_1": {"enabled": True},
            "validation_2": {"enabled": False},
        },
    }


async def _org(db):
    org = Organisation(nom="Historical Test", slug=f"hist-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _user(db, org, *, nom="Validateur", prenom="Alice", role="admin"):
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        nom=nom,
        prenom=prenom,
        role=role,
        organisation_id=org.id,
        active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _service(db, org):
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True)
    db.add(service)
    await db.flush()
    return service


async def _budget_poste(db, org):
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"DEP-{uuid.uuid4().hex[:6]}",
        libelle="Poste historique",
        type="DEPENSE",
        active=True,
        montant_prevu=Decimal("100000"),
        montant_engage=Decimal("0"),
        is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _print_settings(db, org, *, signer="Alice A", rate=Decimal("2800")):
    settings = PrintSettings(
        organisation_id=org.id,
        organization_name="ONEC Snapshot",
        req_titre_officiel="BON HISTORIQUE",
        req_label_gauche="Etabli par",
        req_nom_gauche=signer,
        req_label_droite="Approuve par",
        req_nom_droite="President",
        default_currency="USD",
        secondary_currency="CDF",
        exchange_rate_cdf=rate,
    )
    db.add(settings)
    await db.flush()
    return settings


async def _approved_requisition(db, org, service, user, *, amount=Decimal("2800"), currency="CDF"):
    req = Requisition(
        organisation_id=org.id,
        service_id=service.id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Operation historique",
        mode_paiement="cash",
        type_requisition="classique",
        status="EN_ATTENTE",
        examen_status="EXAMINE",
        montant_total=amount,
        devise=currency,
        created_by=user.id,
        workflow_snapshot=_express_workflow(),
    )
    db.add(req)
    await db.flush()
    db.add(
        LigneRequisition(
            organisation_id=org.id,
            requisition_id=req.id,
            rubrique="Poste historique",
            description="Ligne historique",
            quantite=1,
            montant_unitaire=amount,
            montant_total=amount,
            devise=currency,
        )
    )
    await db.commit()
    return await validate_requisition_logic(
        db=db,
        requisition_id=req.id,
        user=user,
        tenant_id=org.id,
        request=_FakeRequest(),
    )


# Réplique du trigger d'immuabilité (défini en migration, absent du schéma de test
# construit via metadata.create_all). On l'installe pour couvrir l'interaction
# finalisation + snapshot au niveau base.
_TRIGGER_FN_SQL = """
CREATE OR REPLACE FUNCTION prevent_requisition_sensitive_update_after_final()
RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('APPROUVEE', 'PAYEE', 'EN_DECAISSEMENT') AND (
        OLD.signataire_g_nom IS DISTINCT FROM NEW.signataire_g_nom OR
        OLD.signataire_d_nom IS DISTINCT FROM NEW.signataire_d_nom OR
        OLD.exchange_rate_snapshot IS DISTINCT FROM NEW.exchange_rate_snapshot OR
        OLD.base_amount_snapshot IS DISTINCT FROM NEW.base_amount_snapshot OR
        OLD.converted_amount_snapshot IS DISTINCT FROM NEW.converted_amount_snapshot
    ) THEN
        RAISE EXCEPTION 'Réquisition finalisée: modification historique sensible interdite';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


async def _install_immutability_trigger(db):
    await db.execute(text(_TRIGGER_FN_SQL))
    await db.execute(
        text(
            "CREATE TRIGGER trg_requisitions_immutable_after_final "
            "BEFORE UPDATE ON requisitions FOR EACH ROW "
            "EXECUTE FUNCTION prevent_requisition_sensitive_update_after_final()"
        )
    )
    await db.commit()


async def _drop_immutability_trigger(db):
    await db.execute(text("DROP TRIGGER IF EXISTS trg_requisitions_immutable_after_final ON requisitions"))
    await db.execute(text("DROP FUNCTION IF EXISTS prevent_requisition_sensitive_update_after_final()"))
    await db.commit()


async def _install_line_immutability_trigger(db):
    await db.execute(text(req_reset_bypass.LINE_TRIGGER_FUNCTION_WITH_ADMIN_BYPASS))
    await db.execute(
        text(
            "CREATE TRIGGER trg_lignes_requisition_immutable_after_final "
            "BEFORE INSERT OR UPDATE OR DELETE ON lignes_requisition FOR EACH ROW "
            "EXECUTE FUNCTION prevent_ligne_requisition_change_after_final()"
        )
    )
    await db.commit()


async def _drop_line_immutability_trigger(db):
    await db.execute(text("DROP TRIGGER IF EXISTS trg_lignes_requisition_immutable_after_final ON lignes_requisition"))
    await db.execute(text("DROP FUNCTION IF EXISTS prevent_ligne_requisition_change_after_final()"))
    await db.commit()


@pytest.mark.asyncio
async def test_vise_finalisation_ecrit_snapshot_avec_trigger_immuabilite(db_session):
    """Regression : la finalisation (statut -> APPROUVEE) doit écrire le snapshot
    historique dans le MÊME UPDATE, sinon le trigger d'immuabilité rejette (500).
    """
    db = db_session
    await _install_immutability_trigger(db)
    try:
        org = await _org(db)
        service = await _service(db, org)
        user = await _user(db, org)
        await _print_settings(db, org, signer="Alice A", rate=Decimal("2800"))

        # Passe par validate -> APPROUVEE (express) : déclenche ensure_snapshot
        # pendant la transition, avec le trigger actif.
        req = await _approved_requisition(db, org, service, user)

        assert req.status == "APPROUVEE"
        assert req.historical_snapshot_status == "complete"
        assert req.exchange_rate_snapshot is not None
    finally:
        await _drop_immutability_trigger(db)


@pytest.mark.asyncio
async def test_requisition_validation_snapshot_garde_signataire_et_taux(db_session):
    db = db_session
    org = await _org(db)
    service = await _service(db, org)
    user = await _user(db, org)
    settings = await _print_settings(db, org, signer="Alice A", rate=Decimal("2800"))

    req = await _approved_requisition(db, org, service, user)
    assert req.status == "APPROUVEE"
    assert req.historical_snapshot_status == "complete"
    assert req.req_nom_gauche_hist == "Alice A"
    assert Decimal(str(req.exchange_rate_snapshot)) == Decimal("2800.0000")
    assert Decimal(str(req.converted_amount_snapshot)) == Decimal("1.00")

    settings.req_nom_gauche = "Bob B"
    settings.exchange_rate_cdf = Decimal("3000")
    await db.commit()
    await db.refresh(req)

    assert req.req_nom_gauche_hist == "Alice A"
    assert Decimal(str(req.exchange_rate_snapshot)) == Decimal("2800.0000")
    assert Decimal(str(req.converted_amount_snapshot)) == Decimal("1.00")


@pytest.mark.asyncio
async def test_requisition_finalisee_refuse_modification_montant(db_session):
    db = db_session
    org = await _org(db)
    service = await _service(db, org)
    user = await _user(db, org)
    await _print_settings(db, org)
    req = await _approved_requisition(db, org, service, user)

    with pytest.raises(HTTPException) as exc:
        await update_requisition_logic(
            db=db,
            requisition_id=req.id,
            payload=RequisitionUpdate(montant_total=Decimal("9999")),
            user=user,
            tenant_id=org.id,
            request=_FakeRequest(),
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_requisition_finalisee_refuse_ajout_ligne(db_session):
    db = db_session
    org = await _org(db)
    service = await _service(db, org)
    user = await _user(db, org)
    poste = await _budget_poste(db, org)
    await _print_settings(db, org)
    req = await _approved_requisition(db, org, service, user)

    from app.api.v1.endpoints.lignes_requisition import create_lignes_requisition

    with pytest.raises(HTTPException) as exc:
        await create_lignes_requisition(
            payload=[
                LigneRequisitionCreate(
                    requisition_id=req.id,
                    budget_poste_id=poste.id,
                    rubrique="Poste historique",
                    description="Nouvelle ligne interdite",
                    quantite=1,
                    montant_unitaire=Decimal("10"),
                    montant_total=Decimal("10"),
                    devise="USD",
                )
            ],
            db=db,
            user=user,
            tenant_id=org.id,
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_trigger_lignes_requisition_bloque_usage_normal_et_autorise_reset_admin(db_session):
    db = db_session
    await _install_line_immutability_trigger(db)
    try:
        org = await _org(db)
        service = await _service(db, org)
        user = await _user(db, org)
        await _print_settings(db, org)
        org_id = org.id
        service_id = service.id
        user_id = user.id

        req = await _approved_requisition(db, org, service, user)
        line_id = await db.scalar(
            text("SELECT id FROM lignes_requisition WHERE requisition_id = :req_id LIMIT 1"),
            {"req_id": req.id},
        )

        with pytest.raises(Exception, match="Réquisition finalisée: modification des lignes interdite"):
            await db.execute(text("DELETE FROM lignes_requisition WHERE id = :line_id"), {"line_id": line_id})
            await db.commit()
        await db.rollback()

        await db.execute(text("SET LOCAL onec.admin_reset = 'on'"))
        await db.execute(text("DELETE FROM lignes_requisition WHERE id = :line_id"), {"line_id": line_id})
        await db.commit()

        deleted_line = await db.scalar(
            text("SELECT id FROM lignes_requisition WHERE id = :line_id"),
            {"line_id": line_id},
        )
        assert deleted_line is None

        org = await db.get(Organisation, org_id)
        service = await db.get(Service, service_id)
        user = await db.get(User, user_id)
        req_after_reset = await _approved_requisition(db, org, service, user)
        protected_line_id = await db.scalar(
            text("SELECT id FROM lignes_requisition WHERE requisition_id = :req_id LIMIT 1"),
            {"req_id": req_after_reset.id},
        )

        with pytest.raises(Exception, match="Réquisition finalisée: modification des lignes interdite"):
            await db.execute(text("DELETE FROM lignes_requisition WHERE id = :line_id"), {"line_id": protected_line_id})
            await db.commit()
        await db.rollback()
    finally:
        await _drop_line_immutability_trigger(db)
