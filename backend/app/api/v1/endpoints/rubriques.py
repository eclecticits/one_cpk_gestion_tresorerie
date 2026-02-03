[200~from fastapi import APIRouter

router = APIRouter()

@router.get("/rubriques", operation_id="list_rubriques")
def list_rubriques():
    return {"message": "Liste des rubriques"} @router.get("/requisitions", 
operation_id="list_requisitions") def list_requisitions():
    return {"message": "Liste des réquisitions"

@router.get("/users", operation_id="list_users")
def list_users():
    return {"message": "Liste des utilisateurs"}

@router.get("/paiements", operation_id="list_paiements")
def list_paiements():
    return {"message": "Liste des paiements"}

