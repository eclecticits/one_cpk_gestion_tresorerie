from fastapi import APIRouter, HTTPException, status

router = APIRouter()

# These are intentionally minimal placeholders to make the project structure explicit.
# They will be replaced by real CRUD endpoints (SQLAlchemy) after importing the real DB schema.

DOMAINS = [
    "users",
    "rubriques",
    "experts-comptables",
    "encaissements",
    "payment-history",
    "requisitions",
    "lignes-requisition",
    "sorties-fonds",
    "remboursements-transport",
    "participants-transport",
    "imports-history",
    "category-changes-history",
    "requisition-approvers",
    "user-roles",
]


@router.get("/stub")
async def list_domains() -> dict:
    return {"domains": DOMAINS, "note": "Implement CRUD endpoints per domain"}


@router.api_route("/{path:path}", methods=["GET", "POST", "PATCH", "PUT", "DELETE"])  # catch-all under /api/v1
async def not_implemented(path: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Endpoint not implemented yet: /api/v1/{path}",
    )
