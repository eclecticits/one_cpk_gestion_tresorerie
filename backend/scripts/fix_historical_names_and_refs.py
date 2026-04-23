
import asyncio
import uuid
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.remboursement_transport import RemboursementTransport
from app.models.user import User

async def fix_data():
    async for db in get_db():
        print("Début de la correction des données...")
        
        # 1. Correction des noms historiques dans les réquisitions
        print("Correction des noms des validateurs dans les réquisitions...")
        res = await db.execute(select(Requisition).where(Requisition.is_deleted.is_(False)))
        requisitions = res.scalars().all()
        
        for req in requisitions:
            modified = False
            # Validateur (Validation 1)
            if req.validee_par:
                user_res = await db.execute(select(User).where(User.id == req.validee_par))
                user = user_res.scalar_one_or_none()
                if user:
                    full_name = f"{user.prenom or ''} {user.nom or ''}".strip()
                    if req.req_nom_gauche_hist != full_name:
                        req.req_nom_gauche_hist = full_name
                        modified = True
            
            # Approbateur (Validation 2)
            if req.approuvee_par:
                user_res = await db.execute(select(User).where(User.id == req.approuvee_par))
                user = user_res.scalar_one_or_none()
                if user:
                    full_name = f"{user.prenom or ''} {user.nom or ''}".strip()
                    if req.req_nom_droite_hist != full_name:
                        req.req_nom_droite_hist = full_name
                        modified = True
            
            if modified:
                print(f"  -> Réquisition {req.numero_requisition} mise à jour.")

        # 2. Correction des références dans les sorties de fonds
        print("Mise à jour des références des sorties de fonds...")
        res = await db.execute(select(SortieFonds).order_by(SortieFonds.created_at.asc()))
        sorties = res.scalars().all()
        
        used_refs = set()
        
        for sortie in sorties:
            if sortie.requisition_id:
                # Trouver la réquisition
                req_res = await db.execute(select(Requisition).where(Requisition.id == sortie.requisition_id))
                req = req_res.scalar_one_or_none()
                
                if req:
                    base_ref = req.numero_requisition
                    
                    # Si c'est un remboursement de transport
                    if req.type_requisition == "remboursement_transport":
                        remb_res = await db.execute(select(RemboursementTransport).where(RemboursementTransport.requisition_id == req.id))
                        remb = remb_res.scalar_one_or_none()
                        if remb:
                            base_ref = remb.numero_remboursement or remb.reference_numero or base_ref
                    
                    new_ref = base_ref
                    counter = 1
                    # Gérer les doublons pour respecter la contrainte unique
                    while new_ref in used_refs:
                        new_ref = f"{base_ref}-{counter}"
                        counter += 1
                    
                    if sortie.reference_numero != new_ref:
                        print(f"  -> Sortie {sortie.id}: {sortie.reference_numero} -> {new_ref}")
                        sortie.reference_numero = new_ref
                    
                    used_refs.add(new_ref)
            else:
                if sortie.reference_numero:
                    used_refs.add(sortie.reference_numero)

        await db.commit()
        print("Correction terminée avec succès.")
        break

if __name__ == "__main__":
    asyncio.run(fix_data())
