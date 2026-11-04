"""Human verification routes (scaffold — placeholder)."""

from fastapi import APIRouter

router = APIRouter(prefix="/verification", tags=["verification"])


@router.get("/queue")
def queue() -> dict:
    return {"items": []}


@router.post("/{finding_id}")
def review(finding_id: str, payload: dict) -> dict:
    return {"finding_id": finding_id, "review_status": payload.get("decision", "pending")}
