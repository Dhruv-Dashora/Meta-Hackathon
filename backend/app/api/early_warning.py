"""Early-warning routes (scaffold — placeholder, no AI calls)."""

from fastapi import APIRouter

from app.schemas.early_warning import EarlyWarningRequest, EarlyWarningResponse

router = APIRouter(prefix="/early-warning", tags=["early-warning"])


@router.post("/analyze", response_model=EarlyWarningResponse)
def analyze(payload: EarlyWarningRequest) -> EarlyWarningResponse:
    return EarlyWarningResponse(incident_id="scaffold", findings=[])
