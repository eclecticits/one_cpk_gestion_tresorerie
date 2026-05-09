from fastapi import APIRouter

router = APIRouter()


@router.get("/rubriques", operation_id="list_rubriques_placeholder")
def list_rubriques() -> dict[str, str]:
    return {"message": "Liste des rubriques"}


@router.get("/requisitions", operation_id="list_requisitions_placeholder")
def list_requisitions() -> dict[str, str]:
    return {"message": "Liste des réquisitions"}


@router.get("/users", operation_id="list_users_placeholder")
def list_users() -> dict[str, str]:
    return {"message": "Liste des utilisateurs"}


@router.get("/paiements", operation_id="list_paiements_placeholder")
def list_paiements() -> dict[str, str]:
    return {"message": "Liste des paiements"}
