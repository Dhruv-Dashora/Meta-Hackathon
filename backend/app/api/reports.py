"""Report routes (scaffold — placeholder)."""

from fastapi import APIRouter

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{incident_id}")
def get_report(incident_id: str) -> dict:
    return {"incident_id": incident_id, "status": "scaffold", "sections": []}
